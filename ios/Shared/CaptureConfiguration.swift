import Foundation
import CryptoKit
import Network

struct CaptureConfiguration: Decodable, Sendable {
    let serverURL: URL
    let token: String
    let fallbackServerURLs: [URL]
    let receiverID: String?

    private enum CodingKeys: String, CodingKey {
        case serverURL = "server_url", token
        case fallbackServerURLs = "fallback_server_urls"
        case receiverID = "receiver_id"
    }

    init(serverURL: URL, token: String, fallbackServerURLs: [URL] = [], receiverID: String? = nil) {
        self.serverURL = serverURL; self.token = token
        self.fallbackServerURLs = fallbackServerURLs; self.receiverID = receiverID
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init(serverURL: try c.decode(URL.self, forKey: .serverURL), token: try c.decode(String.self, forKey: .token),
                  fallbackServerURLs: try c.decodeIfPresent([URL].self, forKey: .fallbackServerURLs) ?? [],
                  receiverID: try c.decodeIfPresent(String.self, forKey: .receiverID))
        guard Self.validServerURL(serverURL), token.count >= 16,
              fallbackServerURLs.count <= 8, fallbackServerURLs.allSatisfy(Self.validServerURL),
              receiverID == nil || receiverID == Self.identifier(for: token) else { throw ConfigurationError.invalid }
    }

    static func validServerURL(_ url: URL) -> Bool {
        ["http", "https"].contains(url.scheme) && !(url.host ?? "").isEmpty &&
        url.user == nil && url.password == nil && url.query == nil && url.fragment == nil
    }

    static func identifier(for token: String) -> String {
        SHA256.hash(data: Data(token.utf8)).prefix(8).map { String(format: "%02x", $0) }.joined()
    }
    var expectedReceiverID: String { receiverID ?? Self.identifier(for: token) }

    static func load(bundle: Bundle = .main) throws -> CaptureConfiguration {
        guard let url = bundle.url(forResource: "LocalCaptureConfig", withExtension: "json") else { throw ConfigurationError.missing }
        return try JSONDecoder().decode(Self.self, from: Data(contentsOf: url))
    }

    func replacingServerURL(_ url: URL) -> CaptureConfiguration {
        CaptureConfiguration(serverURL: url, token: token,
                             fallbackServerURLs: ReceiverConnectionPolicy.uniqueURLs([serverURL] + fallbackServerURLs).filter { $0 != url },
                             receiverID: receiverID)
    }
    var healthURL: URL { serverURL.appendingPathComponent("api/live/health") }
    var mobileStateURL: URL { serverURL.appendingPathComponent("api/live/mobile/state") }
    var voiceURL: URL { socketURL(path: "api/live/voice") }
    var sourceURL: URL { socketURL(path: "api/live/source") }
    private func socketURL(path: String) -> URL {
        var parts = URLComponents(url: serverURL.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        parts.scheme = serverURL.scheme == "https" ? "wss" : "ws"
        return parts.url!
    }
}

/// Pure policies shared by the app, voice receiver and broadcast extension.
enum ReceiverConnectionPolicy {
    static func uniqueURLs(_ urls: [URL]) -> [URL] {
        var seen = Set<String>()
        return urls.filter { url in
            guard CaptureConfiguration.validServerURL(url) else { return false }
            let key = url.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            return seen.insert(key).inserted
        }
    }
    static func candidates(configuration: CaptureConfiguration, lastSuccessful: URL?) -> [URL] {
        uniqueURLs(([lastSuccessful].compactMap { $0 }) + [configuration.serverURL] + configuration.fallbackServerURLs)
    }
    static func retryDelay(attempt: Int) -> Double { min(8, pow(2, Double(max(0, min(attempt - 1, 3))))) }
    static func matches(receiverID: String?, expected: String) -> Bool { receiverID == expected }
    static func endpointURL(host: String, port: UInt16, scheme: String = "http") -> URL? {
        guard ["http", "https"].contains(scheme), port > 0, !host.isEmpty else { return nil }
        var parts = URLComponents(); parts.scheme = scheme
        parts.host = host.contains(":") && !host.hasPrefix("[") ? "[\(host)]" : host
        parts.port = Int(port)
        guard let url = parts.url, CaptureConfiguration.validServerURL(url) else { return nil }
        return url
    }
}

struct ResolvedReceiver: Sendable {
    let configuration: CaptureConfiguration
    let modelState: String
}

struct ReceiverConnectionError: LocalizedError {
    let details: [String]
    var errorDescription: String? { details.joined(separator: "\n") }
}

/// Every returned address passed health + authenticated, side-effect-free state GET.
/// A remembered address is a candidate, never a declaration that it is still connected.
actor ReceiverResolver {
    func resolve(_ configuration: CaptureConfiguration) async throws -> ResolvedReceiver {
        let cacheKey = "skycompanion.receiver.verifiedURL." + configuration.expectedReceiverID
        let cached = UserDefaults.standard.string(forKey: cacheKey).flatMap(URL.init(string:))
        let known = ReceiverConnectionPolicy.candidates(configuration: configuration, lastSuccessful: cached)
        let discovery = Task { await BonjourReceiverDiscovery.find(receiverID: configuration.expectedReceiverID) }
        defer { discovery.cancel() }
        var failures: [String] = []
        for url in known {
            try Task.checkCancellation()
            do {
                let value = try await verify(configuration.replacingServerURL(url))
                UserDefaults.standard.set(url.absoluteString, forKey: cacheKey)
                return value
            } catch is CancellationError { throw CancellationError() }
            catch { failures.append("\(url.host ?? "receiver"): \(error.localizedDescription)") }
        }
        let found = await discovery.value
        for url in ReceiverConnectionPolicy.uniqueURLs(found.urls).filter({ !known.contains($0) }) {
            try Task.checkCancellation()
            do {
                let value = try await verify(configuration.replacingServerURL(url))
                UserDefaults.standard.set(url.absoluteString, forKey: cacheKey)
                return value
            } catch is CancellationError { throw CancellationError() }
            catch { failures.append("\(url.host ?? "receiver"): \(error.localizedDescription)") }
        }
        if let detail = found.detail { failures.append(detail) }
        if found.urls.isEmpty { failures.append("Bonjour: No paired receiver found; the configured address and fallback IP were also tried.") }
        throw ReceiverConnectionError(details: failures)
    }

    private func verify(_ configuration: CaptureConfiguration) async throws -> ResolvedReceiver {
        let settings = URLSessionConfiguration.ephemeral
        settings.timeoutIntervalForRequest = 2; settings.timeoutIntervalForResource = 2.5
        settings.waitsForConnectivity = false; settings.urlCache = nil
        let session = URLSession(configuration: settings)
        defer { session.invalidateAndCancel() }
        var health: [String: Any]
        do {
            var request = URLRequest(url: configuration.healthURL)
            request.timeoutInterval = 2; request.cachePolicy = .reloadIgnoringLocalCacheData
            let (data, response) = try await session.data(for: request)
            guard (response as? HTTPURLResponse)?.statusCode == 200,
                  let value = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  value["protocol_version"] as? Int == 1, value["configured"] as? Bool == true else {
                throw ReceiverConnectionError(details: ["Health check: Invalid service protocol or pairing configuration."])
            }
            health = value
            if let identity = value["receiver_id"] as? String,
               identity != configuration.expectedReceiverID {
                throw ReceiverConnectionError(details: ["Receiver identity mismatch; pairing credentials were not sent."])
            }
        } catch is CancellationError { throw CancellationError() }
        catch { throw ReceiverConnectionError(details: ["Health check: \(error.localizedDescription)"] ) }
        do {
            var request = URLRequest(url: configuration.mobileStateURL)
            request.timeoutInterval = 2; request.cachePolicy = .reloadIgnoringLocalCacheData
            request.setValue("Bearer \(configuration.token)", forHTTPHeaderField: "Authorization")
            let (data, response) = try await session.data(for: request)
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard status == 200, (try? JSONSerialization.jsonObject(with: data)) is [String: Any] else {
                throw ReceiverConnectionError(details: [status == 401 || status == 403 ? "Pairing rejected. Update the app configuration." : "Pairing check returned HTTP \(status)."])
            }
        } catch is CancellationError { throw CancellationError() }
        catch { throw ReceiverConnectionError(details: ["Pairing verification: \(error.localizedDescription)"] ) }
        let model = health["model"] as? [String: Any]
        return ResolvedReceiver(configuration: configuration, modelState: model?["state"] as? String ?? "unknown")
    }
}

/// Network.framework resolves only an advertised matching service. No LAN scanning.
private final class BonjourReceiverDiscovery: @unchecked Sendable {
    struct Result: Sendable { let urls: [URL]; let detail: String? }
    private let queue = DispatchQueue(label: "skycompanion.receiver.discovery")
    private let expected: String
    private var browser: NWBrowser?
    private var connections: [NWConnection] = []
    private var endpoints = Set<NWEndpoint>()
    private var continuation: CheckedContinuation<Result, Never>?
    private var finished = false
    private var found: [URL] = []
    private var detail: String?

    private func diagnostic(_ text: String) {
        if ProcessInfo.processInfo.environment["SKYCOMPANION_DISCOVERY_DIAGNOSTICS"] == "1" { FileHandle.standardError.write(Data(("Bonjour diagnostic: " + text + "\n").utf8)) }
    }

    private init(receiverID: String) { expected = receiverID }
    static func find(receiverID: String) async -> Result {
        let probe = BonjourReceiverDiscovery(receiverID: receiverID)
        return await withTaskCancellationHandler(operation: {
            await withCheckedContinuation { continuation in
                probe.queue.async {
                    guard !probe.finished else { continuation.resume(returning: Result(urls: [], detail: nil)); return }
                    probe.continuation = continuation
                    probe.start()
                }
            }
        }, onCancel: { probe.queue.async { probe.finish() } })
    }
    private func start() {
        let parameters = NWParameters.tcp
        parameters.includePeerToPeer = false
        let browser = NWBrowser(for: .bonjourWithTXTRecord(type: "_skycompanion-live._tcp", domain: "local."), using: parameters)
        self.browser = browser
        browser.stateUpdateHandler = { [weak self] state in
            guard let self, !self.finished else { return }
            self.diagnostic("browser \(state)")
            switch state {
            case .failed(let error): self.detail = "Bonjour: \(error.localizedDescription)"; self.finish()
            case .waiting(let error): self.detail = "Bonjour: \(error.localizedDescription)"
            default: break
            }
        }
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            guard let self, !self.finished else { return }
            for result in results {
                if case .bonjour(let txt) = result.metadata { self.diagnostic("result \(result.endpoint), receiver ID \(txt["receiver_id"] ?? "missing")") }
                guard case .bonjour(let txt) = result.metadata,
                      ReceiverConnectionPolicy.matches(receiverID: txt["receiver_id"], expected: self.expected),
                      [nil, "/"].contains(txt["path"]), self.endpoints.count < 3,
                      self.endpoints.insert(result.endpoint).inserted else { continue }
                let scheme = txt["scheme"] ?? "http"
                guard ["http", "https"].contains(scheme) else { continue }
                let connection = NWConnection(to: result.endpoint, using: .tcp)
                self.connections.append(connection)
                connection.stateUpdateHandler = { [weak self, weak connection] state in
                    guard let self, let connection, !self.finished else { return }
                    self.diagnostic("connection \(state), endpoint \(String(describing: connection.currentPath?.remoteEndpoint))")
                    if case .ready = state, case .hostPort(let host, let port) = connection.currentPath?.remoteEndpoint,
                       let url = ReceiverConnectionPolicy.endpointURL(host: host.debugDescription, port: port.rawValue, scheme: scheme) {
                        self.found.append(url); self.finish()
                    }
                }
                connection.start(queue: self.queue)
            }
        }
        browser.start(queue: queue)
        queue.asyncAfter(deadline: .now() + 3) { [weak self] in self?.finish() }
    }
    private func finish() {
        guard !finished else { return }
        finished = true
        browser?.cancel(); browser = nil
        connections.forEach { $0.cancel() }; connections.removeAll()
        continuation?.resume(returning: Result(urls: found, detail: detail)); continuation = nil
    }
}

enum ConfigurationError: LocalizedError {
    case missing, invalid
    var errorDescription: String? {
        switch self {
        case .missing: return "Development configuration is missing. Generate it on the Mac and reinstall the app."
        case .invalid: return "Invalid development configuration. Check the Mac service address and pairing configuration, then reinstall."
        }
    }
}
