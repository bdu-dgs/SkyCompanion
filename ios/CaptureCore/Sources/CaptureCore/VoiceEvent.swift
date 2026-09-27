import Foundation

/// Protocol data only. Spoken content comes from a local whitelist, never remote `text`.
public struct VoiceEvent: Decodable, Equatable {
    public enum Direction: String, Decodable { case ahead, left, right }
    public let id: String
    public let direction: Direction
    public let asset: String
    public let priority: String
    public let ttlMS: Double
    public let categoryNamingEnabled: Bool
    public let capturedUptimeMS: Double?
    public let maxObservationAgeMS: Double?
    public let schemaVersion: Int?
    public let speechCode: String?
    public let directionFrame: String?
    public let riskLevel: String?

    enum CodingKeys: String, CodingKey {
        case id, direction, asset, priority
        case ttlMS = "ttl_ms"
        case categoryNamingEnabled = "category_naming_enabled"
        case capturedUptimeMS = "captured_uptime_ms"
        case maxObservationAgeMS = "max_observation_age_ms"
        case schemaVersion = "schema_version"
        case speechCode = "speech_code"
        case directionFrame = "direction_frame"
        case riskLevel = "risk_level"
    }

    public init(id: String, direction: Direction, asset: String, priority: String = "obstacle",
                ttlMS: Double, categoryNamingEnabled: Bool = false,
                capturedUptimeMS: Double? = nil, maxObservationAgeMS: Double? = nil,
                schemaVersion: Int? = 2, speechCode: String? = "camera_obstacle",
                directionFrame: String? = "camera_image", riskLevel: String? = "R1") {
        self.id = id; self.direction = direction; self.asset = asset; self.priority = priority
        self.ttlMS = ttlMS; self.categoryNamingEnabled = categoryNamingEnabled
        self.capturedUptimeMS = capturedUptimeMS; self.maxObservationAgeMS = maxObservationAgeMS
        self.schemaVersion = schemaVersion; self.speechCode = speechCode
        self.directionFrame = directionFrame; self.riskLevel = riskLevel
    }

    private static let riskNouns = ["camera_obstacle": "obstacle", "camera_surface": "ground change",
                                    "camera_overhead": "overhead obstruction", "camera_vehicle": "vehicle conflict"]
    public static let healthPhrases = [
        "perception_unavailable": "Visual guidance is unavailable. Check your surroundings.",
        "perception_restored": "Live observations have resumed. Your direction and distance remain unverified.",
        "direction_unverified": "Your direction is unverified. Locations refer to the camera view."
    ]

    public var isAllowed: Bool {
        guard !id.isEmpty, id.count <= 128, !categoryNamingEnabled,
              ttlMS.isFinite, ttlMS <= 1_500 else { return false }
        // A legacy sound check is explicit and cannot become a production risk alert.
        if schemaVersion == nil || schemaVersion == 1 {
            return priority == "test" && asset == "stop_obstacle_\(direction.rawValue)"
        }
        guard schemaVersion == 2, let speechCode else { return false }
        if priority == "health" {
            return Self.healthPhrases[speechCode] != nil && asset == "health_\(speechCode)"
                && direction == .ahead && directionFrame == "unavailable" && riskLevel == nil
                && capturedUptimeMS == nil && maxObservationAgeMS == nil
        }
        guard ["obstacle", "urgent", "test"].contains(priority),
              Self.riskNouns[speechCode] != nil, directionFrame == "camera_image",
              ["R0", "R1", "R2", "R3"].contains(riskLevel ?? ""),
              asset == "risk_\(speechCode)_\(direction.rawValue)" else { return false }
        if priority != "test" {
            guard (priority == "urgent" && riskLevel == "R3")
                    || (priority == "obstacle" && ["R1", "R2"].contains(riskLevel ?? "")) else { return false }
            guard let capture = capturedUptimeMS, let maxAge = maxObservationAgeMS,
                  capture.isFinite, maxAge.isFinite, maxAge > 0, maxAge <= 1_500 else { return false }
        }
        return true
    }

    public var safeText: String {
        if let speechCode, let health = Self.healthPhrases[speechCode], priority == "health" { return health }
        let noun = Self.riskNouns[speechCode ?? ""] ?? "obstacle"
        let location = direction == .ahead ? "ahead" : "on the \(direction.rawValue)"
        return "Caution. Possible \(noun) \(location) in the camera view. Your direction is unverified."
    }
}

/// No backlog. Lower priority replies and tests cannot interrupt risk alerts.
/// TTL is a start deadline; a sentence that has already started may finish.
public struct VoiceEventGate {
    public enum Decision: Equatable {
        case play(deadlineMS: Double)
        case duplicate, expired, disabled, invalid
    }
    private var seenIDs: Set<String> = []
    private var order: [String] = []
    private let historyLimit: Int

    public init(historyLimit: Int = 256) { self.historyLimit = max(1, historyLimit) }

    public mutating func receive(_ event: VoiceEvent, nowMS: Double, enabled: Bool) -> Decision {
        guard event.isAllowed, nowMS.isFinite else { return .invalid }
        guard !seenIDs.contains(event.id) else { return .duplicate }
        // Remember disabled/expired events too: a route change cannot replay them later.
        seenIDs.insert(event.id); order.append(event.id)
        while order.count > historyLimit { seenIDs.remove(order.removeFirst()) }
        guard enabled else { return .disabled }
        guard event.ttlMS > 0 else { return .expired }
        var deadline = nowMS + event.ttlMS
        if let capture = event.capturedUptimeMS {
            let maxAge = event.maxObservationAgeMS ?? 1_500
            guard capture.isFinite, maxAge.isFinite, maxAge > 0, maxAge <= 1_500,
                  capture <= nowMS, nowMS - capture < maxAge else { return .expired }
            deadline = min(deadline, capture + maxAge)
        } else if event.maxObservationAgeMS != nil { return .invalid }
        return .play(deadlineMS: deadline)
    }

    public static func mayInterrupt(incomingPriority: String, currentPriority: String?) -> Bool {
        let ranks = ["test": 0, "query": 1, "health": 2, "obstacle": 2, "urgent": 3]
        guard let incoming = ranks[incomingPriority] else { return false }
        guard let currentPriority else { return true }
        guard let current = ranks[currentPriority] else { return false }
        if incomingPriority == "health" && currentPriority == "obstacle" { return false }
        return incoming >= current
    }

    public static func canStart(deadlineMS: Double, nowMS: Double) -> Bool {
        nowMS.isFinite && deadlineMS.isFinite && nowMS < deadlineMS
    }
}
