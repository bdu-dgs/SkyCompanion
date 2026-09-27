import Foundation

/// Read-only Mac integration probe. Never prints the token or creates a source session.
@main
struct ResolverProbe {
    static func main() async throws {
        guard CommandLine.arguments.count == 3 else { throw ReceiverConnectionError(details: ["Usage: resolver-probe <config path> <fallback|bonjour|wrong-identity|wrong-pairing>"]) }
        let original = try JSONDecoder().decode(CaptureConfiguration.self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
        let mode = CommandLine.arguments[2]
        let missing = URL(string: "http://skycompanion-connectivity-probe.invalid:8000")!
        let config: CaptureConfiguration
        switch mode {
        case "fallback": config = CaptureConfiguration(serverURL: missing, token: original.token, fallbackServerURLs: [original.serverURL], receiverID: original.expectedReceiverID)
        case "bonjour": config = CaptureConfiguration(serverURL: missing, token: original.token, receiverID: original.expectedReceiverID)
        case "wrong-identity": config = CaptureConfiguration(serverURL: original.serverURL, token: original.token, receiverID: "0000000000000000")
        case "wrong-pairing": config = CaptureConfiguration(serverURL: original.serverURL, token: "deliberately-invalid-test-pairing", receiverID: original.expectedReceiverID)
        default: throw ReceiverConnectionError(details: ["Unknown probe mode"])
        }
        // This command-line executable has its own defaults domain, not the iPhone's.
        UserDefaults.standard.removeObject(forKey: "skycompanion.receiver.verifiedURL." + config.expectedReceiverID)
        let started = Date()
        do {
            let value = try await ReceiverResolver().resolve(config)
            guard !mode.hasPrefix("wrong-") else { throw ReceiverConnectionError(details: ["FAIL: invalid receiver accepted"]) }
            print("PASS \(mode): verified \(value.configuration.serverURL.absoluteString), model=\(value.modelState), elapsed=\(String(format: "%.2f", Date().timeIntervalSince(started)))s")
        } catch {
            if mode.hasPrefix("wrong-") {
                let text = error.localizedDescription
                let expected = mode == "wrong-identity" ? "identity mismatch" : "Pairing rejected"
                guard text.contains(expected) else { throw error }
                print("PASS \(mode): rejected before declaring connection, elapsed=\(String(format: "%.2f", Date().timeIntervalSince(started)))s")
            } else { throw error }
        }
    }
}
