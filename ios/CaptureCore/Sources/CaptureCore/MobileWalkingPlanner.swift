import Foundation

public enum MobileWalkingAction: String, Codable, Sendable {
    case straight, left, right, checkPath
    public var text: String {
        switch self {
        case .straight: return MobileCopy.text("Go straight.")
        case .left: return MobileCopy.text("Keep left.")
        case .right: return MobileCopy.text("Keep right.")
        case .checkPath: return MobileCopy.text("Check your path.")
        }
    }
}
public struct MobileWalkingObservation: Codable, Sendable {
    public let sessionID: String
    public let revision: UInt64
    public let frameID: UInt64
    public let capturedUptimeMS: Double
    public let caution: MobileDirection?
    public let action: MobileWalkingAction?
    public let confirmed: Bool
    public let event: Bool
    public let reason: String
    /// Historical reminder classification only; does not alter movement decisions.
    public var obstacleRelated: Bool = false
    /// Labels of relevant detections, retained separately from spoken direction/action.
    /// Nil preserves decoding of observations recorded before category personalization.
    public var obstacleLabels: [String]? = nil
    public var isOrdinarySideReminder: Bool {
        confirmed && obstacleRelated && action == .straight && (caution == .left || caution == .right)
    }
    public var severity: MobileRiskLevel {
        switch action {
        case .checkPath, .left, .right: return .action
        case .straight: return .attention
        case nil: return .none
        }
    }
    public var speech: String {
        guard let action else { return "" }
        let first = caution.map { MobileAlertSpeech.caution(direction: $0) } ?? MobileCopy.text("Position unknown.")
        return first + " " + action.text
    }
}

/// Experimental image-space planner for an explicitly confirmed, unmirrored rear-following view.
/// Routes must stay inside the registered, manually confirmed traversable region.
/// Image clearance is not metric clearance or a verified walking-safety claim.
public struct MobileWalkingPlanner {
    private var lineage = ""
    private var lastTime = -Double.infinity
    private var candidate = "", candidateSince = 0.0, count = 0
    private var announced = "", lastAnnouncement = -Double.infinity
    private var previousObstacles: [MobileDetection] = []
    private var lostObstacle = false
    private var preferred: MobileWalkingAction?
    private var lastAction: MobileWalkingAction?
    public init() {}
    public mutating func update(frame: MobileFrameResult, path: MobilePathObservation?, rearFollowing: Bool, now: Double) -> MobileWalkingObservation {
        let key = "\(frame.sessionID):\(frame.revision)"
        if key != lineage { self = Self(); lineage = key }
        let priorTime = lastTime
        let fresh = frame.isFresh(at: now) && frame.capturedUptimeMS > lastTime
        if fresh { lastTime = frame.capturedUptimeMS }
        func observation(_ direction: MobileDirection?, _ action: MobileWalkingAction?, _ confirmed: Bool, _ event: Bool, _ reason: String,
                         obstacleRelated: Bool = false, obstacleLabels: [String]? = nil) -> MobileWalkingObservation {
            .init(sessionID:frame.sessionID, revision:frame.revision, frameID:frame.frameID,
                  capturedUptimeMS:frame.capturedUptimeMS, caution:direction, action:action, confirmed:confirmed, event:event,
                  reason:reason, obstacleRelated:obstacleRelated, obstacleLabels:obstacleLabels)
        }
        guard rearFollowing else { return observation(nil,nil,false,false,"Rear-following view not confirmed") }
        guard fresh, let path, path.sessionID == frame.sessionID, path.revision == frame.revision,
              path.frameID == frame.frameID, path.capturedUptimeMS == frame.capturedUptimeMS,
              path.state == .inside || path.state == .nearBoundary || path.state == .outside,
              let person = path.person, person.isValid, let foot = path.foot,
              MobilePathMonitor.validBoundary(path.boundary) else {
            candidate = ""; count = 0
            let alert = announced != "unknown"
            announced = "unknown"; lastAction = nil
            return observation(nil,.checkPath,false,alert,"User/path unavailable; no walking instruction")
        }
        let half = max(0.035,min(0.08,person.width*0.65))
        let ahead = max(0.18,min(0.36,person.height*1.4))
        let shift = half*3.5
        let ignored:Set<String> = ["sidewalk","road","crosswalk","floor","ceiling","sky","traffic light"]
        let allObstacles = frame.detections.filter {
            $0.isValid && $0.confidence >= 0.30 && !ignored.contains($0.label)
                && $0.label != "curb" && !($0 == person)
        }
        // Quiet curb detections remain uncertain route boundaries, never cleared turns.
        let boundaryHints = frame.detections.filter {
            $0.isValid && $0.confidence >= 0.30 && $0.label == "curb"
        }
        // Bound the forward/near-side neighborhood to the selected wearer, never the whole image.
        let obstacles = allObstacles.filter {
            $0.y < foot.y+half && $0.y+$0.height > foot.y-ahead
                && $0.x < foot.x+shift+half && $0.x+$0.width > foot.x-shift-half
        }
        // A disappearance does not prove that a previously occupied route became clear.
        if previousObstacles.contains(where: { old in !allObstacles.contains(where: { $0.intersectionOverUnion(with:old) >= 0.15 }) }) { lostObstacle = true }
        previousObstacles = obstacles
        let front = obstacles.filter { $0.y < foot.y-half && $0.x < foot.x+half && $0.x+$0.width > foot.x-half }
        let leftSide = obstacles.filter { $0.y+$0.height >= foot.y-half && $0.x+$0.width <= foot.x-half }
        let rightSide = obstacles.filter { $0.y+$0.height >= foot.y-half && $0.x >= foot.x+half }
        let routeBlockers = obstacles + boundaryHints
        func route(_ action: MobileWalkingAction) -> Double? {
            let offset = action == .left ? -shift : action == .right ? shift : 0
            var clearance = Double.infinity
            for step in 0...12 {
                let t = Double(step)/12
                let center = MobilePoint(x:foot.x+offset*min(1,t*2),y:foot.y-ahead*t)
                for lateral in stride(from: -1.0, through: 1.0, by: 0.2) {
                    let p = MobilePoint(x:center.x+lateral*half,y:center.y)
                    guard (0...1).contains(p.x), (0...1).contains(p.y), MobilePathMonitor.contains(p,polygon:path.boundary) else { return nil }
                    clearance = min(clearance,MobilePathMonitor.edgeDistance(p,polygon:path.boundary))
                    // Inflate all detected obstacle boxes; low-confidence objects still block a route.
                    if routeBlockers.contains(where: { p.x >= $0.x-0.015 && p.x <= $0.x+$0.width+0.015 && p.y >= $0.y-0.015 && p.y <= $0.y+$0.height+0.015 }) { return nil }
                }
            }
            return clearance
        }
        var direction:MobileDirection?, action:MobileWalkingAction?
        var obstacleRelated = false
        var reason = "No relevant obstacle; no repeated instruction"
        if lostObstacle {
            obstacleRelated = true
            direction = front.isEmpty ? nil : .ahead; action = .checkPath
            reason = "Earlier obstacle disappeared; reselect person/path before moving guidance resumes"
        } else if path.state == .outside || (path.state == .nearBoundary && front.isEmpty) {
            let center = path.boundary.map(\.x).reduce(0,+)/Double(path.boundary.count)
            direction = foot.x < center-0.025 ? .left : foot.x > center+0.025 ? .right : .ahead
            action = .checkPath; reason = "Person near or outside the confirmed path boundary"
        } else if !front.isEmpty {
            obstacleRelated = true
            direction = .ahead
            let left = route(.left), right = route(.right)
            if let left, let right {
                if preferred == .left { action = .left }
                else if preferred == .right { action = .right }
                else { action = left >= right ? .left : .right }
            } else if left != nil { action = .left }
            else if right != nil { action = .right }
            else { action = .checkPath }
            reason = "Forward obstacle; compare continuous left/right routes inside confirmed region"
        } else if !leftSide.isEmpty || !rightSide.isEmpty {
            obstacleRelated = true
            // Side warnings permit straight only when the WHOLE forward corridor is available.
            direction = leftSide.isEmpty ? .right : .left
            action = route(.straight) != nil ? .straight : .checkPath
            reason = "Near-side obstacle; forward corridor independently checked"
        }
        let signature = "\(direction?.rawValue ?? "unknown"):\(action?.rawValue ?? "none")"
        if signature != candidate || lastTime-priorTime > 800 {
            candidate = signature; candidateSince = lastTime; count = 1
        } else { count += 1 }
        let stable = count >= 3 && lastTime-candidateSince >= 700
        if !stable, let prior = lastAction, prior != .checkPath, prior != action, action != nil {
            lastAction = .checkPath; announced = "checking"; lastAnnouncement = lastTime
            return observation(direction,.checkPath,true,true,"Earlier walking instruction revoked while a changed route is confirmed")
        }
        // Unsafe/unknown revokes a prior walking instruction immediately.
        let confirmed = stable || action == .checkPath
        let alert = action != nil && confirmed && signature != announced
            && (action == .checkPath || action != lastAction || lastTime-lastAnnouncement >= 8_000 || announced == "unknown")
        if alert { announced = signature; lastAction = action; lastAnnouncement = lastTime; if action == .left || action == .right { preferred = action } }
        if stable && action == nil { announced = ""; preferred = nil; lastAction = nil }
        return observation(direction,action,confirmed,alert,reason,obstacleRelated:obstacleRelated,
                           obstacleLabels: Array(Set(obstacles.map(\.label))).sorted())
    }
}
