import Foundation

/// Deliberate, whole-utterance commands only; no substring match against ambient speech.
public enum VoiceCommand: String {
    case repeatAlert = "repeat", mute, unmute, describe, stop, explain, acknowledge, quiet, normal
    case reportFalseAlert = "report_false_alert"
    public static func parse(_ transcript: String) -> VoiceCommand? {
        let words = transcript.lowercased().components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { !$0.isEmpty }.joined(separator: " ")
        return ["skycompanion repeat": .repeatAlert, "skycompanion repeat alert": .repeatAlert,
                "skycompanion mute": .mute, "skycompanion unmute": .unmute,
                "skycompanion describe": .describe, "skycompanion describe ahead": .describe,
                "skycompanion what is ahead": .describe, "skycompanion what s ahead": .describe,
                "skycompanion what obstacles are ahead": .describe,
                "skycompanion what is around me": .describe,
                "skycompanion what obstacles are around me": .describe,
                "skycompanion why": .explain, "skycompanion got it": .acknowledge,
                "skycompanion quieter": .quiet, "skycompanion normal alerts": .normal,
                "skycompanion wrong alert": .reportFalseAlert,
                "skycompanion stop listening": .stop][words]
    }
}

public struct VoiceSceneObject: Decodable {
    public let kind: String
    public let direction: String
    public let count: Int
    public let vertical: String
    public init(kind: String, direction: String, count: Int, vertical: String) {
        self.kind = kind; self.direction = direction; self.count = count; self.vertical = vertical
    }
}

public enum VoiceReply {
    public static func text(code: String, direction: String?, objects: [VoiceSceneObject]? = nil,
                            reasonCodes: [String]? = nil) -> String? {
        switch code {
        case "scene_summary":
            guard let objects, !objects.isEmpty, objects.count <= 3 else { return nil }
            let nouns = ["person": ("a person", "people"), "car": ("a car", "cars"),
                         "bicycle": ("a bicycle", "bicycles"), "motorcycle": ("a motorcycle", "motorcycles"),
                         "bus": ("a bus", "buses"), "truck": ("a truck", "trucks"),
                         "traffic_light": ("a traffic light", "traffic lights"), "chair": ("a chair", "chairs"),
                         "bench": ("a bench", "benches"), "table": ("a table", "tables"),
                         "dog": ("a dog", "dogs"), "plant": ("a plant", "plants"),
                         "obstacle": ("a possible obstacle", "possible obstacles")]
            var phrases: [String] = []
            for object in objects {
                guard let noun = nouns[object.kind], (1...3).contains(object.count),
                      ["left", "ahead", "right"].contains(object.direction),
                      ["upper", "middle", "lower"].contains(object.vertical) else { return nil }
                let quantity = object.count == 1 ? noun.0 : (object.count == 2 ? "two " : "several ") + noun.1
                var location = object.direction == "ahead" ? "ahead" : "on the " + object.direction
                if object.vertical == "upper" { location += ", in the upper part of the view" }
                phrases.append(quantity + " " + location)
            }
            let listing = phrases.count == 1 ? phrases[0] : phrases.dropLast().joined(separator: ", ") + ", and " + phrases.last!
            return "In the camera view: " + listing + "."
        case "no_stable_objects": return "I cannot identify objects reliably in the current view."
        case "unconfirmed_obstacle":
            guard let direction, ["ahead", "left", "right"].contains(direction) else { return nil }
            return "Possible obstacle in camera view, \(direction). Type unconfirmed. I cannot see outside this view."
        case "no_confirmed_obstacle": return "No confirmed obstacle in the selected camera view. I cannot see outside this view. This does not mean the path is clear."
        case "vision_unavailable", "perception_unavailable": return VoiceEvent.healthPhrases["perception_unavailable"]
        case "perception_restored", "direction_unverified": return VoiceEvent.healthPhrases[code]
        case "risk_explanation":
            let allowed: Set<String> = ["image_corridor_overlap", "persistent_observation", "apparent_near_image_proxy",
                "surface_change_candidate", "drop_candidate", "overhead_alignment_candidate", "vehicle_candidate",
                "camera_direction_only", "metric_distance_unknown", "occluded_unresolved", "image_conflict_resolved",
                "no_confirmed_conflict", "corridor_unconfigured", "evidence_stale", "validated_ttc_budget",
                "new_relevance", "risk_upgrade", "direction_change"]
            guard let reasonCodes, !reasonCodes.isEmpty, reasonCodes.count <= allowed.count,
                  reasonCodes.allSatisfy({ allowed.contains($0) }) else { return nil }
            var text = "The alert is based on observations in the selected camera view. Its distance and direction relative to you are unknown."
            if reasonCodes.contains("image_corridor_overlap") && reasonCodes.contains("persistent_observation") {
                text = "This object overlaps the selected camera corridor across several observations. Its distance and direction relative to you are unknown."
            }
            if reasonCodes.contains("occluded_unresolved") { text += " The earlier obstacle is no longer visible. It has not been confirmed resolved." }
            return text
        case "risk_unresolved": return "The earlier obstacle is no longer visible. It has not been confirmed resolved."
        case "risk_acknowledged": return "Alert acknowledged. This does not mean the obstacle is resolved."
        case "quiet_enabled": return "Quieter alerts enabled. Higher risk alerts remain on."
        case "quiet_disabled": return "Normal alerts enabled."
        case "false_alert_saved": return "False alert report saved for review."
        case "false_alert_no_evidence", "no_evidence": return "There is no recent alert evidence to report."
        case "no_recent_alert": return "No recent valid alert to repeat."
        default: return nil
        }
    }
}
