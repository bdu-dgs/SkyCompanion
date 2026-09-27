import Foundation
import CoreGraphics
import CaptureCore

struct CaptureRegion: Codable, Equatable {
    var x: Double = 0
    var y: Double = 0
    var width: Double = 1
    var height: Double = 1
    var valid: Bool {
        [x, y, width, height].allSatisfy(\.isFinite) && x >= 0 && y >= 0 &&
        width > 0.05 && height > 0.05 && x + width <= 1.00001 && y + height <= 1.00001
    }
    var rect: CGRect { CGRect(x: x, y: y, width: width, height: height) }
    var summary: String {
        String(format: "Left %.0f%% · Top %.0f%% · Width %.0f%% · Height %.0f%%", x*100, y*100, width*100, height*100)
    }
    static func saved(in defaults: UserDefaults = .standard) -> CaptureRegion? {
        guard let data = defaults.data(forKey: "skycompanion.drone.videoArea"),
              let region = try? JSONDecoder().decode(Self.self, from: data), region.valid else { return nil }
        return region
    }
    func save(in defaults: UserDefaults = .standard) {
        guard valid, let data = try? JSONEncoder().encode(self) else { return }
        defaults.set(data, forKey: "skycompanion.drone.videoArea")
    }
}

/// Draft edits are separate from the last explicitly applied rectangle.
struct CaptureAreaSelection {
    var draft: CaptureRegion
    private(set) var applied: CaptureRegion?
    init(saved: CaptureRegion? = nil) {
        let valid = saved.flatMap { $0.valid ? $0 : nil }
        draft = valid ?? CaptureRegion(); applied = valid
    }
    @discardableResult mutating func apply() -> Bool {
        guard draft.valid else { return false }
        applied = draft; return true
    }
    mutating func reopen() {
        if let applied { draft = applied }
    }
}

struct LocalCaptureSettings: Codable {
    var sessionID: String
    var revision: UInt64
    var region: CaptureRegion
    var corridor: [MobilePoint]
    var analyze: Bool
    var requestPreview: Bool = false
    var recordingContainsLocalVideo: Bool = false
    var recordingRegion: CaptureRegion? = nil
    var captureEvidence: Bool = false
    var depthEnabled: Bool = false
    var pathConfiguration: LocalPathConfiguration?
    var wearerConfiguration: LocalWearerConfiguration?
}

/// Small, bounded packets stay on this phone. A new connection requires a new handshake.
struct LocalPacket: Codable {
    var type: String
    var handshakeRole: String?
    var nonce: String?
    var proof: String?
    var contextSessionID: String?
    var contextRevision: UInt64?
    var settings: LocalCaptureSettings?
    var frame: MobileFrameResult?
    var risk: MobileRiskAssessment?
    var summary: MobileSceneSummary?
    var message: String?
    var preview: Data?
    var sourcePreview: Data?
    var appliedRegion: CaptureRegion?
    var evidenceImage: Data?
    var uptimeMS: Double = ProcessInfo.processInfo.systemUptime * 1_000
    var recordingID: String?
    var recordingAudio: LocalRecordingAudio?
    var memoryMB: Double?
    var inferenceTimings: MobileInferenceTimings?
    var depth: MobileDepthResult?
    var path: MobilePathObservation?
    var walking: MobileWalkingObservation?
    var wearer: MobileWearerObservation?
    var failure: String?
}

struct DevicePairing: Decodable {
    let token: String
    static let port: UInt16 = 18743
    static func load() throws -> DevicePairing {
        guard let url = Bundle.main.url(forResource: "DevicePairing", withExtension: "json") else {
            throw LocalFailure.message(String(localized: "This installation is missing its local pairing resource. Rebuild SkyCompanion."))
        }
        let config = try JSONDecoder().decode(Self.self, from: Data(contentsOf: url))
        guard config.token.count >= 32 else { throw LocalFailure.message(String(localized: "Invalid local pairing resource.")) }
        return config
    }
}

enum LocalFailure: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}
