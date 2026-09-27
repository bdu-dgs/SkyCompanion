import Foundation
import Combine
import CoreLocation
import MapKit
import CaptureCore

struct NavigationDestinationCandidate: Identifiable {
    let id: UUID
    let name: String
    let detail: String
}

/// Owns walking navigation without launching Maps. All speech goes through the
/// app's shared scheduler; this controller never creates an audio session.
@MainActor
final class NavigationController: NSObject, ObservableObject, @preconcurrency CLLocationManagerDelegate {
    @Published private(set) var status = "Navigation off"
    @Published private(set) var destination = ""
    @Published private(set) var isActive = false
    @Published private(set) var candidates: [NavigationDestinationCandidate] = []
    @Published private(set) var currentInstruction = ""
    @Published private(set) var remainingMeters: Double = 0
    @Published private(set) var guidanceNotice = ""
    var onPrompt: ((String) -> Bool)?
    var onAnnouncement: ((String) -> Void)?
    var onInvalidateGuidance: (() -> Void)?

    private let manager = CLLocationManager()
    private var search: MKLocalSearch?
    private var directions: MKDirections?
    private var requestTask: Task<Void, Never>?
    private var generation = UUID()
    private var latestLocation: CLLocation?
    private var pendingQuery: String?
    private var candidateItems: [UUID: MKMapItem] = [:]
    private var selectedItem: MKMapItem?
    private var progress: NavigationProgress?
    private var origin = MKMapPoint()
    private var metersPerMapPoint: Double = 1
    private var steps: [(distance: Double, instruction: String)] = []
    private var lastRouteRequest = Date.distantPast
    private var routeLoading = false

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBestForNavigation
        manager.distanceFilter = 2
        manager.activityType = .fitness
        manager.pausesLocationUpdatesAutomatically = false
        manager.showsBackgroundLocationIndicator = true
    }

    func start(destination query: String) {
        let query = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { announce("Say a destination to start navigation."); return }
        stop()
        destination = query
        pendingQuery = query
        isActive = true
        status = "Finding your location…"
        guard CLLocationManager.locationServicesEnabled() else {
            fail("Location Services are off. Enable them in iPhone Settings."); return
        }
        switch manager.authorizationStatus {
        case .notDetermined: manager.requestWhenInUseAuthorization()
        case .authorizedAlways, .authorizedWhenInUse: beginLocationUpdates()
        case .denied, .restricted: fail("Allow location access in iPhone Settings to navigate.")
        @unknown default: fail("Location permission is unavailable.")
        }
    }

    func stop() {
        onInvalidateGuidance?()
        generation = UUID()
        requestTask?.cancel(); requestTask = nil
        search?.cancel(); search = nil
        directions?.cancel(); directions = nil
        manager.stopUpdatingLocation()
        manager.allowsBackgroundLocationUpdates = false
        isActive = false
        pendingQuery = nil; selectedItem = nil; latestLocation = nil
        candidates = []; candidateItems = [:]
        progress = nil; steps = []; routeLoading = false
        currentInstruction = ""; remainingMeters = 0; guidanceNotice = ""
        status = "Navigation off"
    }

    func selectCandidate(number: Int) {
        guard candidates.indices.contains(number - 1) else {
            announce("Choose a destination number from the list."); return
        }
        selectCandidate(id: candidates[number - 1].id)
    }

    func selectCandidate(id: UUID) {
        guard isActive, let item = candidateItems[id] else { return }
        selectedItem = item
        destination = item.name ?? destination
        candidates = []; candidateItems = [:]
        if let location = latestLocation, isFresh(location) {
            requestRoute(to: item, from: location, rerouting: false)
        } else { status = "Waiting for an accurate location…" }
    }

    private func beginLocationUpdates() {
        guard isActive else { return }
        // Setting this without the background mode would raise an iOS exception.
        let modes = Bundle.main.object(forInfoDictionaryKey: "UIBackgroundModes") as? [String] ?? []
        manager.allowsBackgroundLocationUpdates = modes.contains("location")
        manager.startUpdatingLocation()
        if manager.accuracyAuthorization == .reducedAccuracy {
            status = "Enable Precise Location in Settings for turn guidance."
            announce(status)
        }
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        guard isActive else { return }
        switch manager.authorizationStatus {
        case .authorizedAlways, .authorizedWhenInUse: beginLocationUpdates()
        case .denied, .restricted: fail("Allow location access in iPhone Settings to navigate.")
        default: break
        }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        guard isActive else { return }
        onInvalidateGuidance?()
        if (error as? CLError)?.code == .denied {
            fail("Location permission was removed. Navigation stopped.")
        } else {
            status = "Location unavailable. Turn guidance paused."
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard isActive, let location = locations.last else { return }
        guard isFresh(location) else {
            onInvalidateGuidance?()
            status = "Waiting for an accurate location. Turn guidance paused."
            return
        }
        if let previous = latestLocation, location.timestamp <= previous.timestamp { return }
        latestLocation = location
        if location.horizontalAccuracy > 12 { onInvalidateGuidance?() }
        if let query = pendingQuery {
            pendingQuery = nil
            findDestination(query, near: location)
            return
        }
        guard !routeLoading else { return }
        if progress == nil, candidates.isEmpty, let item = selectedItem {
            guard Date().timeIntervalSince(lastRouteRequest) >= 30 else { return }
            requestRoute(to: item, from: location, rerouting: false)
            return
        }
        guard var tracker = progress else { return }
        let update = tracker.update(point: point(location.coordinate), accuracy: location.horizontalAccuracy,
                                    timestamp: location.timestamp.timeIntervalSince1970, now: Date().timeIntervalSince1970)
        remainingMeters = update.remaining
        if update.arrived {
            let name = destination
            stop()
            status = "Arrived at \(name)"
            announce("Arrived.")
            return
        }
        if update.offRoute {
            onInvalidateGuidance?()
            status = "Off route. Turn guidance paused."
            if update.shouldReroute, Date().timeIntervalSince(lastRouteRequest) >= 30, let item = selectedItem {
                progress = tracker
                requestRoute(to: item, from: location, rerouting: true)
                return
            }
        } else if update.usable {
            status = location.horizontalAccuracy <= 12 ? walkingStatus : "Improving location accuracy. Turn guidance paused."
            currentInstruction = steps.last(where: { $0.distance <= tracker.traveled + 3 })?.instruction ?? "Follow the walking route."
            if let prompt = update.prompt, onPrompt?(prompt.text) == true { tracker.acknowledge(prompt) }
        }
        progress = tracker
    }

    private func isFresh(_ location: CLLocation) -> Bool {
        let age = Date().timeIntervalSince(location.timestamp)
        return location.horizontalAccuracy >= 0 && location.horizontalAccuracy <= 20 && age >= -1 && age <= 8
    }

    private func findDestination(_ query: String, near location: CLLocation) {
        status = "Searching for \(query)…"
        let request = MKLocalSearch.Request()
        request.naturalLanguageQuery = query
        request.region = MKCoordinateRegion(center: location.coordinate, latitudinalMeters: 20_000, longitudinalMeters: 20_000)
        let search = MKLocalSearch(request: request)
        self.search = search
        let token = generation
        requestTask = Task { [weak self] in
            do {
                let response = try await search.start()
                guard let self, self.generation == token, !Task.isCancelled else { return }
                self.search = nil
                let items = Array(response.mapItems.sorted {
                    ($0.placemark.location?.distance(from: location) ?? .infinity) < ($1.placemark.location?.distance(from: location) ?? .infinity)
                }.prefix(3))
                guard !items.isEmpty else { self.fail("No destination found. Try a name and city or a full address."); return }
                self.candidates = items.map { item in
                    let id = UUID()
                    self.candidateItems[id] = item
                    let distance = item.placemark.location?.distance(from: location) ?? 0
                    let address = [item.placemark.thoroughfare, item.placemark.locality].compactMap { $0 }.joined(separator: ", ")
                    return NavigationDestinationCandidate(id: id, name: item.name ?? query,
                        detail: "\(address) · \(String(format: "%.1f", distance / 1000)) km")
                }
                // A unique nearby match can start directly. Multiple or remote matches
                // need an explicit numbered selection (also supported by voice).
                if items.count == 1, (items[0].placemark.location?.distance(from: location) ?? .infinity) <= 50_000 {
                    self.selectCandidate(number: 1)
                } else {
                    self.status = "Choose a destination. Say “SkyCompanion, choose one”, “choose two”, or “choose three”."
                    let names = self.candidates.enumerated().map { "\($0.offset + 1), \($0.element.name), \($0.element.detail)" }.joined(separator: ". ")
                    self.announce("Choose a destination. \(names). Say SkyCompanion, choose one, two, or three.")
                }
            } catch {
                guard let self, self.generation == token, !Task.isCancelled else { return }
                self.fail("Destination search failed. Check your connection and try again.")
            }
        }
    }

    private func requestRoute(to item: MKMapItem, from location: CLLocation, rerouting: Bool) {
        onInvalidateGuidance?()
        routeLoading = true
        lastRouteRequest = Date()
        status = rerouting ? "Recalculating walking route…" : "Planning walking route…"
        // Invalidate the old route immediately; never speak instructions while rerouting.
        progress = nil
        currentInstruction = ""
        remainingMeters = 0
        guidanceNotice = ""
        let request = MKDirections.Request()
        request.source = MKMapItem(placemark: MKPlacemark(coordinate: location.coordinate))
        request.destination = item
        request.transportType = .walking
        request.requestsAlternateRoutes = false
        let directions = MKDirections(request: request)
        self.directions = directions
        let token = generation
        requestTask = Task { [weak self] in
            do {
                let response = try await directions.calculate()
                guard let self, self.generation == token, !Task.isCancelled else { return }
                self.routeLoading = false; self.directions = nil
                guard let route = response.routes.first, route.polyline.pointCount > 1 else {
                    self.fail("No walking route is available for this destination."); return
                }
                self.install(route)
                self.status = self.walkingStatus
                self.announce(rerouting ? "Route updated." : "Navigation started to \(self.destination).")
            } catch {
                guard let self, self.generation == token, !Task.isCancelled else { return }
                self.routeLoading = false; self.directions = nil
                self.status = "Route unavailable. Check your connection. Retrying with the next location update."
                self.announce("Route unavailable. Navigation guidance paused.")
            }
        }
    }

    private func install(_ route: MKRoute) {
        let mapPoints = route.polyline.points()
        origin = mapPoints[0]
        metersPerMapPoint = MKMetersPerMapPointAtLatitude(origin.coordinate.latitude)
        let points = (0..<route.polyline.pointCount).map { index in
            NavigationPoint(x: (mapPoints[index].x - origin.x) * metersPerMapPoint,
                            y: (mapPoints[index].y - origin.y) * metersPerMapPoint)
        }
        var distance = 0.0
        var cumulative = [0.0]
        for index in points.indices.dropFirst() { cumulative.append(cumulative.last! + points[index - 1].distance(to: points[index])) }
        var maneuvers: [NavigationManeuver] = []
        var unsupportedInstructions = false
        steps = []
        for step in route.steps where step.polyline.pointCount > 0 {
            let start = point(step.polyline.points()[0].coordinate)
            // Step maneuver occurs at the beginning of its polyline. Match in route
            // order rather than assuming Apple's step.distance equals geometry length.
            let index = points.indices.filter { cumulative[$0] >= distance - 2 }.min {
                points[$0].distance(to: start) < points[$1].distance(to: start)
            }
            if let index { distance = max(distance, cumulative[index]) }
            steps.append((distance, step.instructions))
            if let kind = NavigationManeuver.Kind.from(instruction: step.instructions) {
                maneuvers.append(.init(distance: distance, kind: kind))
            } else if !step.instructions.isEmpty {
                let instruction = step.instructions.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
                let passive = ["head ", "continue ", "walk ", "proceed ", "start ", "arrive", "destination", "your destination"]
                if !passive.contains(where: { instruction.hasPrefix($0) }) { unsupportedInstructions = true }
            }
        }
        guidanceNotice = unsupportedInstructions
            ? "Limited voice guidance: some route steps require reading the on-screen directions."
            : ""
        progress = NavigationProgress(points: points, maneuvers: maneuvers)
        remainingMeters = progress?.totalDistance ?? route.distance
        currentInstruction = steps.first(where: { !$0.instruction.isEmpty })?.instruction ?? "Follow the walking route."
    }

    private func point(_ coordinate: CLLocationCoordinate2D) -> NavigationPoint {
        let mapPoint = MKMapPoint(coordinate)
        return .init(x: (mapPoint.x - origin.x) * metersPerMapPoint, y: (mapPoint.y - origin.y) * metersPerMapPoint)
    }

    private func announce(_ text: String) { onAnnouncement?(text) }
    private var walkingStatus: String { guidanceNotice.isEmpty ? "Walking to \(destination)" : "Walking to \(destination) · Limited voice guidance" }
    private func fail(_ text: String) { stop(); status = text; announce(text) }
}
