import Foundation

/// Meter-based route geometry, independent of MapKit so progress can be replay-tested.
public struct NavigationPoint: Equatable, Sendable {
    public var x: Double
    public var y: Double
    public init(x: Double, y: Double) { self.x = x; self.y = y }
    public func distance(to other: Self) -> Double { hypot(x - other.x, y - other.y) }
}

public struct NavigationManeuver: Equatable, Sendable {
    public enum Kind: String, Sendable {
        case left, right, keepLeft, keepRight, bearLeft, bearRight, cross, uTurn
        public var instruction: String {
            switch self {
            case .left: return "Turn left."
            case .right: return "Turn right."
            case .keepLeft: return "Keep left."
            case .keepRight: return "Keep right."
            case .bearLeft: return "Bear left."
            case .bearRight: return "Bear right."
            case .cross: return "Cross street."
            case .uTurn: return "Turn around."
            }
        }
        public var advance: String {
            switch self {
            case .left: return "About to turn left."
            case .right: return "About to turn right."
            case .keepLeft: return "Keep left ahead."
            case .keepRight: return "Keep right ahead."
            case .bearLeft: return "About to bear left."
            case .bearRight: return "About to bear right."
            case .cross: return "Crossing ahead."
            case .uTurn: return "About to turn around."
            }
        }
        /// Only recognizes explicit maneuver language from Apple's instructions.
        /// Unknown/localized text is left to the route UI, never guessed by an LLM.
        public static func from(instruction: String) -> Self? {
            let text = instruction.lowercased()
            if text.contains("u-turn") || text.contains("turn around") { return .uTurn }
            if text.range(of: #"^keep\s+(to the\s+)?left\b"#, options: .regularExpression) != nil { return .keepLeft }
            if text.range(of: #"^keep\s+(to the\s+)?right\b"#, options: .regularExpression) != nil { return .keepRight }
            if text.range(of: #"^(bear|slight|turn slightly)\s+(to the\s+)?left\b"#, options: .regularExpression) != nil { return .bearLeft }
            if text.range(of: #"^(bear|slight|turn slightly)\s+(to the\s+)?right\b"#, options: .regularExpression) != nil { return .bearRight }
            if text.range(of: #"^(turn|sharp)\s+(sharply\s+)?(to the\s+)?left\b"#, options: .regularExpression) != nil { return .left }
            if text.range(of: #"^(turn|sharp)\s+(sharply\s+)?(to the\s+)?right\b"#, options: .regularExpression) != nil { return .right }
            if text.range(of: #"^cross\s"#, options: .regularExpression) != nil { return .cross }
            return nil
        }
    }
    public var distance: Double
    public var kind: Kind
    public init(distance: Double, kind: Kind) { self.distance = distance; self.kind = kind }
}

public struct NavigationPrompt: Equatable, Sendable {
    public let id: String
    public let text: String
}

public struct NavigationProgressUpdate: Sendable {
    public var usable = false
    public var offRoute = false
    public var shouldReroute = false
    public var arrived = false
    public var remaining: Double = 0
    public var prompt: NavigationPrompt?
}

public struct NavigationProgress: Sendable {
    public let points: [NavigationPoint]
    public let maneuvers: [NavigationManeuver]
    public let totalDistance: Double
    public private(set) var traveled: Double = 0
    private let cumulative: [Double]
    private var delivered: Set<String> = []
    private var lastTimestamp: Double?
    private var offRouteSince: Double?
    private var offRouteCount = 0
    private var arrivalCount = 0

    public init(points: [NavigationPoint], maneuvers: [NavigationManeuver]) {
        self.points = points
        self.maneuvers = maneuvers.sorted { $0.distance < $1.distance }
        var lengths = [0.0]
        for index in points.indices.dropFirst() {
            lengths.append(lengths.last! + points[index - 1].distance(to: points[index]))
        }
        self.cumulative = lengths
        self.totalDistance = lengths.last ?? 0
    }

    /// A skipped prompt stays eligible only while the *new* location is in its valid window.
    public mutating func acknowledge(_ prompt: NavigationPrompt) { delivered.insert(prompt.id) }

    public mutating func update(point: NavigationPoint, accuracy: Double, timestamp: Double, now: Double) -> NavigationProgressUpdate {
        var result = NavigationProgressUpdate()
        result.remaining = max(0, totalDistance - traveled)
        guard points.count > 1, accuracy >= 0, accuracy <= 20,
              now - timestamp <= 8, now >= timestamp - 1,
              lastTimestamp.map({ timestamp > $0 }) ?? true else { return result }
        let elapsed = lastTimestamp.map { timestamp - $0 } ?? 0
        lastTimestamp = timestamp
        result.usable = true

        // Limit matching to reachable progress, preventing a nearby later leg of a
        // hairpin/loop from skipping several instructions. Large gaps trigger rerouting.
        let maxAdvance = max(60, min(160, elapsed * 3 + accuracy * 2))
        var bestDistance = Double.infinity
        var bestProgress = traveled
        for index in 1..<points.count {
            guard cumulative[index] >= traveled - 25,
                  cumulative[index - 1] <= traveled + maxAdvance else { continue }
            let start = points[index - 1], end = points[index]
            let dx = end.x - start.x, dy = end.y - start.y
            let squared = dx * dx + dy * dy
            guard squared > 0 else { continue }
            let t = max(0, min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / squared))
            let progress = cumulative[index - 1] + sqrt(squared) * t
            guard progress <= traveled + maxAdvance else { continue }
            let distance = point.distance(to: .init(x: start.x + t * dx, y: start.y + t * dy))
            if distance < bestDistance { bestDistance = distance; bestProgress = progress }
        }
        if bestDistance > max(25, accuracy * 1.8) || bestProgress < traveled - 20 {
            result.offRoute = true
            offRouteCount += 1
            if offRouteSince == nil { offRouteSince = timestamp }
            result.shouldReroute = offRouteCount >= 3 && timestamp - (offRouteSince ?? timestamp) >= 8
            arrivalCount = 0
            return result
        }
        offRouteSince = nil; offRouteCount = 0
        traveled = max(traveled, bestProgress)
        result.remaining = max(0, totalDistance - traveled)
        if result.remaining <= 12 && point.distance(to: points.last!) <= 15 && accuracy <= 12 {
            arrivalCount += 1
            result.arrived = arrivalCount >= 2
            return result
        }
        arrivalCount = 0
        // Tighter accuracy near a turn prevents approximate-location steering.
        guard accuracy <= 12 else { return result }
        for (index, maneuver) in maneuvers.enumerated() {
            let ahead = maneuver.distance - traveled
            guard ahead >= -5 else { continue }
            let immediateID = "\(index)-turn"
            if ahead <= 12 {
                if !delivered.contains(immediateID) {
                    result.prompt = .init(id: immediateID, text: maneuver.kind.instruction)
                }
                return result
            }
            let advanceID = "\(index)-advance"
            if ahead <= 40, !delivered.contains(advanceID), !delivered.contains(immediateID) {
                result.prompt = .init(id: advanceID, text: maneuver.kind.advance)
            }
            return result
        }
        return result
    }
}
