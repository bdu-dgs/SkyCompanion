import Foundation

public struct MobilePoint: Codable, Equatable, Sendable {
    public var x: Double
    public var y: Double
    public init(x: Double, y: Double) { self.x = x; self.y = y }
}

/// Coordinates are normalized to the cropped, upright camera image, never wearer space.
public struct MobileDetection: Codable, Equatable, Sendable {
    public var id: String?
    public var label: String
    public var confidence: Double
    public var x: Double
    public var y: Double
    public var width: Double
    public var height: Double
    public var polygon: [MobilePoint]?
    /// External mask components. Their union preserves disconnected visible regions.
    public var polygons: [[MobilePoint]]?
    public init(id: String? = nil, label: String, confidence: Double, x: Double, y: Double,
                width: Double, height: Double, polygon: [MobilePoint]? = nil, polygons: [[MobilePoint]]? = nil) {
        self.id = id; self.label = label; self.confidence = confidence; self.x = x; self.y = y
        self.width = width; self.height = height; self.polygon = polygon; self.polygons = polygons
    }
    public var isValid: Bool {
        !label.isEmpty && [confidence, x, y, width, height].allSatisfy(\.isFinite)
        && (0...1).contains(confidence) && x >= 0 && x < 1 && y >= 0 && y < 1
        && width > 0 && width <= 1 && height > 0 && height <= 1
    }
    public var direction: MobileDirection {
        let center = x + width / 2
        return center < 0.4 ? .left : center > 0.6 ? .right : .ahead
    }
    public func intersectionOverUnion(with other: MobileDetection) -> Double {
        let intersection = max(0, min(x + width, other.x + other.width) - max(x, other.x))
            * max(0, min(y + height, other.y + other.height) - max(y, other.y))
        return intersection / max(1e-9, width * height + other.width * other.height - intersection)
    }
    /// Image geometry only; `nearCandidate` is not a distance estimate.
    public var attention: MobileAttention {
        let bottom = min(1, y + height)
        let near = (bottom >= 0.68 && (height >= 0.12 || width >= 0.10))
            || (bottom >= 0.82 && (height >= 0.04 || width >= 0.06))
            || (bottom >= 0.50 && (height >= 0.60 || (height >= 0.40 && width >= 0.15)))
        let score = 0.55 * bottom + 0.30 * min(1, max(height / 0.6, width / 0.5))
            + 0.15 * min(1, width * height / 0.25)
        return MobileAttention(nearCandidate: near, score: (score * 10_000).rounded() / 10_000)
    }
}

public struct MobileAttention: Codable, Equatable, Sendable {
    public let nearCandidate: Bool
    public let score: Double
}
public enum MobileDirection: String, Codable, Sendable { case left, ahead, right }
public enum MobileDirectionBasis: String, Codable, Sendable { case cameraImage }
public enum MobileRiskLevel: Int, Codable, Comparable, Sendable {
    case none = 0, attention = 1, action = 2, urgent = 3
    public static func < (lhs: Self, rhs: Self) -> Bool { lhs.rawValue < rhs.rawValue }
}
public enum MobilePerceptionHealth: String, Codable, Sendable {
    case available, limited, unavailable, paused
}
public struct MobileFrameResult: Codable, Equatable, Sendable {
    public var sessionID: String
    public var frameID: UInt64
    public var capturedUptimeMS: Double
    /// Changes whenever the crop, orientation, source or model configuration changes.
    public var revision: UInt64
    public var detections: [MobileDetection]
    public var inferenceMS: Double
    public init(sessionID: String, frameID: UInt64, capturedUptimeMS: Double, revision: UInt64 = 0,
                detections: [MobileDetection], inferenceMS: Double = 0) {
        self.sessionID = sessionID; self.frameID = frameID; self.capturedUptimeMS = capturedUptimeMS
        self.revision = revision; self.detections = detections; self.inferenceMS = inferenceMS
    }
    public func isFresh(at nowUptimeMS: Double) -> Bool {
        !sessionID.isEmpty && capturedUptimeMS.isFinite && nowUptimeMS.isFinite
        && capturedUptimeMS <= nowUptimeMS && nowUptimeMS - capturedUptimeMS < 1_500
    }
}
public struct MobileRiskEvidence: Codable, Equatable, Sendable {
    public let overlap: Double
    public let observations: Int
    public let durationMS: Double
    public let kind: String
    public let nearCandidate: Bool
    public let apparentAreaRatio: Double
    public let directionBasis: MobileDirectionBasis
    public let verifiedUrgency: Bool
    public let categoryNamingEnabled: Bool
    public var hazardConsequence: String = "collision"
    public var detectedLabel: String? = nil
}
public struct MobileRiskEvent: Codable, Equatable, Sendable {
    public let id: String
    public let sessionID: String
    public let frameID: UInt64
    public let revision: UInt64
    public let capturedUptimeMS: Double
    public let trackID: String
    public let level: MobileRiskLevel
    public let direction: MobileDirection
    public let text: String
    public let evidence: MobileRiskEvidence
    public var reasonCodes: [String] = []
    public var expiresUptimeMS: Double { capturedUptimeMS + 1_500 }
    public func isFresh(at nowUptimeMS: Double) -> Bool {
        nowUptimeMS.isFinite && capturedUptimeMS.isFinite && nowUptimeMS >= capturedUptimeMS
        && nowUptimeMS < expiresUptimeMS && (level != .urgent || evidence.verifiedUrgency)
    }
}
public enum MobileRiskState: String, Codable, Sendable {
    case unconfigured, confirming, unconfirmed, occupied, stale, paused
}
public enum MobileRiskLifecycle: String, Codable, Sendable { case unknown, observed, occludedUnresolved, imageConflictResolved }
public struct MobileRiskAssessment: Codable, Equatable, Sendable {
    public let state: MobileRiskState
    public let level: MobileRiskLevel
    public let health: MobilePerceptionHealth
    public let text: String
    public let event: MobileRiskEvent?
    public let evidence: MobileRiskEvidence?
    public let direction: MobileDirection?
    public let trackID: String?
    public let lifecycle: MobileRiskLifecycle
    public init(state: MobileRiskState, level: MobileRiskLevel = .none,
                health: MobilePerceptionHealth = .available, text: String, event: MobileRiskEvent? = nil,
                evidence: MobileRiskEvidence? = nil, direction: MobileDirection? = nil, trackID: String? = nil, lifecycle: MobileRiskLifecycle = .unknown) {
        self.state = state; self.level = level; self.health = health; self.text = text
        self.event = event; self.evidence = evidence; self.direction = direction; self.trackID = trackID; self.lifecycle = lifecycle
    }
    public func withoutEvent() -> Self {
        .init(state: state, level: level, health: health, text: text, evidence: evidence,
              direction: direction, trackID: trackID, lifecycle: lifecycle)
    }
}
public struct MobileSceneObject: Codable, Equatable, Sendable {
    public var directions: [MobileDirection]? = nil
    public let kind: String
    public let direction: MobileDirection
    public let count: Int
    public let vertical: String
}
public struct MobileSceneSummary: Codable, Equatable, Sendable {
    public enum Code: String, Codable, Sendable { case visionUnavailable, noStableObjects, sceneSummary }
    public let code: Code
    public let objects: [MobileSceneObject]
    public let text: String
    public let sessionID: String?
    public let frameID: UInt64?
    public let revision: UInt64?
    public let capturedUptimeMS: Double?
    public let directionBasis: MobileDirectionBasis
}

/// Wall-clock stages on the executing device; excludes source transport and speech.
public struct MobileInferenceTimings: Codable, Equatable, Sendable {
    public let preprocessMS: Double
    public let modelMS: Double
    public let decodeMS: Double
    public init(preprocessMS: Double, modelMS: Double, decodeMS: Double) {
        self.preprocessMS = preprocessMS; self.modelMS = modelMS; self.decodeMS = decodeMS
    }
}
