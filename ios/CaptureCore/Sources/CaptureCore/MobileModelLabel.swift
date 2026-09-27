import Foundation

/// Model class IDs/order stay in the manifest. Translate vocabulary at the
/// detection boundary so existing risk/scene rules receive their canonical names.
public enum MobileModelLabel {
    public static func runtime(_ source: String) -> String {
        switch source {
        // Color predictions do not establish crossing permission.
        case "traffic_light_red", "traffic_light_green", "traffic_light_unknown": return "traffic light"
        case "streetlight", "traffic_light_pole": return "light pole"
        case "utility_pole", "signpost", "column": return "pole"
        case "planter": return "potted plant"
        case "street_kiosk": return "kiosk"
        case "hanging_obstacle": return "overhead obstacle"
        case "low_branch": return "low hanging branch"
        case "protruding_sign": return "hanging sign"
        case "open_manhole": return "hole"
        default: return source.replacingOccurrences(of: "_", with: " ")
        }
    }
}
