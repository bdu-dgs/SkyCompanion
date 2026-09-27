import Foundation

/// Resolve user-facing copy from the host app/extension's Localizable catalog.
/// Foundation's fallback returns the English source key in command-line/package tests.
/// No newer macOS availability requirement is imposed on CaptureCore clients.
enum MobileCopy {
    static func text(_ key: String) -> String {
        NSLocalizedString(key, bundle: .main, comment: "SkyCompanion local vision guidance")
    }
    static func format(_ key: String, _ arguments: CVarArg...) -> String {
        String(format: text(key), locale: Locale.current, arguments: arguments)
    }
    static func position(_ direction: MobileDirection) -> String {
        switch direction {
        case .ahead: return text("ahead")
        case .left: return text("on the left")
        case .right: return text("on the right")
        }
    }
}
