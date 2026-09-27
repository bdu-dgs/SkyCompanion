import Foundation

/// Versioned user policy; applied locally without waiting for a network or language model.
public struct AlertPreferences: Codable, Equatable, Sendable {
    public var schemaVersion = 1
    public var revision = 0
    public var verbosity = "standard"
    public var mutedCategories: [String] = []
    public var repeatIntervalSeconds = 8
    public var urgentAlertsEnabled = true
    public var updatedAtMS: Int64 = 0
    public var appliedRevision: Int?
    public var appliedAtMS: Int64?
    public init() {}
    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version", revision, verbosity
        case mutedCategories = "muted_categories", repeatIntervalSeconds = "repeat_interval_seconds"
        case urgentAlertsEnabled = "urgent_alerts_enabled", updatedAtMS = "updated_at_ms"
        case appliedRevision = "applied_revision", appliedAtMS = "applied_at_ms"
    }
    public static let categories: Set<String> = ["tree", "pole", "person", "vehicle", "bicycle", "stairs", "curb", "obstacle"]
    public var isValid: Bool {
        schemaVersion == 1 && revision >= 0 && ["minimal", "standard", "detailed"].contains(verbosity)
        && (8...120).contains(repeatIntervalSeconds) && urgentAlertsEnabled
        && mutedCategories.count <= Self.categories.count
        && Set(mutedCategories).count == mutedCategories.count
        && mutedCategories.allSatisfy { Self.categories.contains($0) }
        && updatedAtMS >= 0
    }
    public static func category(for label: String?) -> String {
        switch label?.lowercased() {
        case "tree", "bush", "low hanging branch": return "tree"
        case "pole", "utility pole", "sign pole", "street light", "lamp post", "bollard": return "pole"
        case "person", "pedestrian": return "person"
        case "car", "truck", "bus", "train", "motorcycle", "vehicle": return "vehicle"
        case "bicycle", "bike": return "bicycle"
        case "stairs", "stair", "step", "steps", "staircase": return "stairs"
        case "curb": return "curb"
        default: return "obstacle"
        }
    }
    public func allows(level: MobileRiskLevel, label: String?) -> Bool {
        // Never suppress a confirmed action/urgent warning through personalization.
        level >= .action || !mutedCategories.contains(Self.category(for: label))
    }
    public func allowsWalking(_ observation: MobileWalkingObservation) -> Bool {
        // Personalization cannot remove tracking, boundary, or avoidance instructions.
        guard observation.isOrdinarySideReminder else { return true }
        let labels = observation.obstacleLabels.flatMap { $0.isEmpty ? nil : $0 } ?? [""]
        return labels.contains { !mutedCategories.contains(Self.category(for: $0)) }
    }
    public func speech(walking observation: MobileWalkingObservation) -> String {
        guard observation.action != nil else { return "" }
        if verbosity == "minimal", observation.isOrdinarySideReminder, let direction = observation.caution {
            return MobileAlertSpeech.caution(direction: direction)
        }
        if verbosity == "detailed" {
            return observation.speech + " Based on the camera view."
        }
        return observation.speech
    }
    public func speech(direction: MobileDirection, consequence: String, level: MobileRiskLevel) -> String {
        let short = MobileAlertSpeech.caution(direction: direction)
        if level == .urgent { return short + " Check your path now." }
        switch verbosity {
        case "minimal": return short
        case "detailed":
            let noun: String
            switch consequence {
            case "surface", "drop": noun = "ground-level change"
            case "trip": noun = "low obstacle"
            case "overhead": noun = "overhead obstacle"
            case "vehicle": noun = "vehicle"
            default: noun = "obstacle"
            }
            return short + " Possible \(noun) in the camera view. Check your path."
        default: return MobileAlertSpeech.obstacle(direction: direction)
        }
    }
}
