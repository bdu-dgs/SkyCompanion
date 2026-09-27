import Foundation

public struct LocalPathConfiguration: Codable, Sendable {
    public var referenceJPEG: Data
    public var person: MobileDetection
    public var boundary: [MobilePoint]
    public var kind: String
    public var rearFollowing: Bool
    public init(referenceJPEG: Data, person: MobileDetection, boundary: [MobilePoint], kind: String, rearFollowing: Bool = false) {
        self.referenceJPEG = referenceJPEG; self.person = person; self.boundary = boundary; self.kind = kind; self.rearFollowing = rearFollowing
    }
}

public enum MobilePathState: String, Codable, Sendable {
    case unknown, confirming, inside, nearBoundary, outside
}
public struct MobilePathObservation: Codable, Sendable {
    public let sessionID: String
    public let revision: UInt64
    public let frameID: UInt64
    public let capturedUptimeMS: Double
    public let state: MobilePathState
    public let reason: String
    public let foot: MobilePoint?
    public let boundary: [MobilePoint]
    public let eventText: String?
    public let processingMS: Double
    public var person: MobileDetection? = nil
    public init(frame: MobileFrameResult, state: MobilePathState, reason: String,
                foot: MobilePoint?, boundary: [MobilePoint], eventText: String?, processingMS: Double = 0) {
        sessionID = frame.sessionID; revision = frame.revision; frameID = frame.frameID
        capturedUptimeMS = frame.capturedUptimeMS; self.state = state; self.reason = reason
        self.foot = foot; self.boundary = boundary; self.eventText = eventText; self.processingMS = processingMS
    }
}

/// Confirmed image-region membership, NOT heading, route planning or permission to cross.
public struct MobilePathMonitor {
    private var candidate: MobilePathState = .unknown
    private var candidateSince = 0.0
    private var count = 0
    private var lastTime = -Double.infinity
    private var lineage = ""
    private var announced: MobilePathState = .unknown
    private var lastAlert = -Double.infinity
    public init() {}
    public mutating func update(frame: MobileFrameResult, foot: MobilePoint?, boundary: [MobilePoint],
                                reliable: Bool, now: Double, reason: String = "", processingMS: Double = 0) -> MobilePathObservation {
        let key = "\(frame.sessionID):\(frame.revision)"
        if key != lineage { self = Self(); lineage = key }
        let previousTime = lastTime
        guard reliable, frame.isFresh(at: now), frame.capturedUptimeMS > lastTime,
              let foot, foot.x.isFinite, foot.y.isFinite, (0...1).contains(foot.x), (0...1).contains(foot.y),
              Self.validBoundary(boundary) else {
            candidate = .unknown; count = 0
            let text = announced != .unknown ? "Path position unavailable. Check the selected person and path." : nil
            announced = .unknown
            return .init(frame: frame, state: .unknown, reason: reason.isEmpty ? "Tracking or path registration is unreliable." : reason,
                         foot: nil, boundary: [], eventText: text, processingMS: processingMS)
        }
        lastTime = frame.capturedUptimeMS
        let inside = Self.contains(foot, polygon: boundary)
        let separation = Self.edgeDistance(foot, polygon: boundary)
        // Normalized image margin is deliberately not a distance in meters.
        let raw: MobilePathState = separation < 0.025 ? .nearBoundary : inside ? .inside : .outside
        if raw != candidate || lastTime - previousTime > 800 {
            candidate = raw; candidateSince = lastTime; count = 1
        } else { count += 1 }
        guard count >= 3, lastTime-candidateSince >= 700 else {
            return .init(frame: frame, state: .confirming, reason: "Confirming across fresh observations.",
                         foot: foot, boundary: boundary, eventText: nil, processingMS: processingMS)
        }
        var text: String?
        if raw != announced, (lastTime-lastAlert >= 8_000 || raw == .outside) {
            switch raw {
            case .nearBoundary: text = "Selected person near the confirmed path boundary."
            case .outside: text = "Selected person appears outside the confirmed path. Check position."
            case .inside:
                if announced == .outside || announced == .nearBoundary { text = "Selected person appears within the confirmed region again. This does not confirm a clear route." }
            default: break
            }
            announced = raw
            if text != nil { lastAlert = lastTime }
        }
        return .init(frame: frame, state: raw, reason: "Footpoint relative to a manually confirmed image region; experimental.",
                     foot: foot, boundary: boundary, eventText: text, processingMS: processingMS)
    }
    public static func validBoundary(_ p: [MobilePoint]) -> Bool {
        guard p.count == 4, p.allSatisfy({ $0.x.isFinite && $0.y.isFinite && (0...1).contains($0.x) && (0...1).contains($0.y) }) else { return false }
        var signs: [Double] = []
        for i in 0..<4 {
            let a = p[i], b = p[(i+1)%4], c = p[(i+2)%4]
            signs.append((b.x-a.x)*(c.y-b.y)-(b.y-a.y)*(c.x-b.x))
        }
        let area = abs((0..<4).reduce(0.0) { $0 + p[$1].x*p[($1+1)%4].y-p[($1+1)%4].x*p[$1].y })/2
        return area >= 0.015 && (signs.allSatisfy { $0 > 0.0001 } || signs.allSatisfy { $0 < -0.0001 })
    }
    public static func contains(_ p: MobilePoint, polygon: [MobilePoint]) -> Bool {
        guard polygon.count >= 3 else { return false }
        var inside = false; var j = polygon.count-1
        for i in polygon.indices {
            let a = polygon[i], b = polygon[j]
            if (a.y > p.y) != (b.y > p.y), p.x < (b.x-a.x)*(p.y-a.y)/(b.y-a.y)+a.x { inside.toggle() }
            j = i
        }
        return inside
    }
    public static func edgeDistance(_ p: MobilePoint, polygon: [MobilePoint]) -> Double {
        guard polygon.count > 1 else { return .infinity }
        return polygon.indices.map { i -> Double in
            let a = polygon[i], b = polygon[(i+1)%polygon.count], dx = b.x-a.x, dy = b.y-a.y
            let t = min(1, max(0, ((p.x-a.x)*dx+(p.y-a.y)*dy)/max(1e-12,dx*dx+dy*dy)))
            return hypot(p.x-a.x-t*dx, p.y-a.y-t*dy)
        }.min() ?? .infinity
    }
}
