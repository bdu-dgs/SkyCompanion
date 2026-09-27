import Foundation

@MainActor
final class ConnectionModel: ObservableObject {
    @Published private(set) var configuration: CaptureConfiguration?
    @Published private(set) var status = "Check the Mac connection before sharing."
    @Published private(set) var checking = false
    @Published private(set) var canBroadcast = false
    private let resolver = ReceiverResolver()

    init() {
        do { configuration = try .load() }
        catch { status = error.localizedDescription }
    }

    func checkConnection() async {
        guard let configuration, !checking else { return }
        checking = true; canBroadcast = false
        status = "Looking for the paired Mac using its address, fallback IP and Bonjour. Allow local network access when prompted."
        defer { checking = false }
        do {
            let receiver = try await resolver.resolve(configuration)
            self.configuration = receiver.configuration
            guard receiver.modelState == "ready" else {
                status = receiver.modelState == "error"
                    ? "Mac pairing succeeded, but the analysis model failed to load. Check the desktop page."
                    : "Mac pairing succeeded. The analysis model is still loading; check again shortly."
                return
            }
            canBroadcast = true
            status = "Connected. YOLO is ready. Receiver: \(receiver.configuration.serverURL.absoluteString). You can now start the screen broadcast."
        } catch {
            status = "Connection failed: \(error.localizedDescription)\nCheck that both devices use the same Wi-Fi, the Mac service is running, and the app has local network permission in Settings."
        }
    }
}
