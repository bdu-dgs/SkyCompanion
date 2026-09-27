import Foundation

/// Short speech only. Camera-relative detections do not authorize wearer-relative steering.
/// Keep the full hazard evidence in the assessment for the screen and diagnostics.
public enum MobileAlertSpeech {
    public static func caution(direction: MobileDirection) -> String {
        switch direction {
        case .left: return MobileCopy.text("Caution left.")
        case .right: return MobileCopy.text("Caution right.")
        case .ahead: return MobileCopy.text("Caution front.")
        }
    }
    public static func obstacle(direction: MobileDirection) -> String {
        caution(direction: direction) + " " + MobileCopy.text("Check your path.")
    }
    public static func cameraObstacle(direction: MobileDirection) -> String {
        switch direction {
        case .left: return "Caution. Camera left."
        case .right: return "Caution. Camera right."
        case .ahead: return "Caution. Camera front."
        }
    }
}
