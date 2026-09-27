import Foundation
import Network
import CryptoKit

/// This transport is IPC, never a background execution entitlement or wake-up mechanism.
final class LoopbackChannel: @unchecked Sendable {
    enum Role { case app, broadcast }
    var onPacket: ((LocalPacket) -> Void)?
    var onState: ((Bool, String) -> Void)?
    private let queue = DispatchQueue(label: "skycompanion.local.ipc")
    private let role: Role
    private let token: String
    private var listener: NWListener?
    private var connection: NWConnection?
    private var timer: DispatchSourceTimer?
    private var received = Data()
    private var authorized = false
    private var localNonce = ""
    private var peerNonce: String?
    private var roleName: String { role == .app ? "app" : "broadcast" }
    private var peerRole: String { role == .app ? "broadcast" : "app" }
    private var lastReceived = ProcessInfo.processInfo.systemUptime
    private var epoch = UUID()
    private var pendingSend = false
    private var latestResult: LocalPacket?
    private let maxPacket = 1_048_576

    init(role: Role, token: String) { self.role = role; self.token = token }

    func start() {
        queue.async { [self] in
            stopInternal(notify: false)
            do {
                if role == .app {
                    let parameters = NWParameters.tcp
                    parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: DevicePairing.port)!)
                    let server = try NWListener(using: parameters)
                    listener = server
                    server.newConnectionHandler = { [weak self, weak server] candidate in
                        guard let self, let server, self.listener === server else { candidate.cancel(); return }
                        guard self.connection == nil else { candidate.cancel(); return }
                        self.attach(candidate)
                    }
                    server.stateUpdateHandler = { [weak self, weak server] state in
                        guard let self, let server, self.listener === server else { return }
                        if case .failed(let error) = state { self.fail(error.localizedDescription) }
                        if case .ready = state { self.onState?(false, String(localized: "Ready for a broadcast on this phone.")) }
                    }
                    server.start(queue: queue)
                } else {
                    attach(NWConnection(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: DevicePairing.port)!, using: .tcp))
                }
            } catch { fail(error.localizedDescription) }
        }
    }

    func send(_ packet: LocalPacket, completion: ((Bool) -> Void)? = nil) {
        queue.async { [self] in
            guard authorized else { completion?(false); return }
            // Frames never build an unbounded queue behind an unavailable consumer.
            if packet.type == "result", pendingSend, completion == nil { latestResult = packet; return }
            write(packet, completion: completion)
        }
    }

    func stop() { queue.async { [self] in stopInternal() } }

    private func attach(_ candidate: NWConnection) {
        connection = candidate; received.removeAll(keepingCapacity: false)
        authorized = false; lastReceived = ProcessInfo.processInfo.systemUptime
        peerNonce = nil
        var generator = SystemRandomNumberGenerator()
        localNonce = (0..<32).map { _ in String(format: "%02x", UInt8.random(in: .min ... .max, using: &generator)) }.joined()
        let attempt = UUID(); epoch = attempt
        candidate.stateUpdateHandler = { [weak self, weak candidate] state in
            guard let self, self.epoch == attempt, candidate === self.connection else { return }
            switch state {
            case .ready:
                self.write(LocalPacket(type: "hello", handshakeRole: self.roleName, nonce: self.localNonce))
                self.receive(attempt)
                let timer = DispatchSource.makeTimerSource(queue: self.queue)
                timer.schedule(deadline: .now() + 0.5, repeating: 0.5)
                timer.setEventHandler { [weak self] in
                    guard let self else { return }
                    // App transitions may delay scheduling without ending the broadcast.
                    // Vision freshness remains independently capped at 1.5 seconds.
                    let timeout = self.authorized ? 8.0 : 2.5
                    if ProcessInfo.processInfo.systemUptime - self.lastReceived > timeout {
                        self.fail(String(localized: "The local session stopped responding. Return to SkyCompanion and restart."))
                    } else if self.authorized { self.write(LocalPacket(type: "heartbeat")) }
                }
                self.timer = timer; timer.resume()
            case .failed(let error): self.fail(error.localizedDescription)
            case .cancelled: self.fail(String(localized: "Local session ended."))
            default: break
            }
        }
        candidate.start(queue: queue)
    }

    private func receive(_ attempt: UUID) {
        connection?.receive(minimumIncompleteLength: 1, maximumLength: 65_536) { [weak self] data, _, done, error in
            guard let self, self.epoch == attempt else { return }
            if let data {
                self.received.append(data)
                while let end = self.received.firstIndex(of: 10) {
                    let line = self.received.prefix(upTo: end)
                    guard line.count < self.maxPacket else { self.fail(String(localized: "Local packet exceeded the size limit.")); return }
                    self.received.removeSubrange(...end)
                    guard let packet = try? JSONDecoder().decode(LocalPacket.self, from: line),
                          packet.uptimeMS.isFinite else { self.fail(String(localized: "Invalid local packet.")); return }
                    if !self.authorized {
                        guard self.authenticate(packet) else { self.fail(String(localized: "Local pairing failed.")); return }
                    } else if packet.type == "hello" || packet.type == "authenticate" {
                        self.fail(String(localized: "Unexpected local handshake replay.")); return
                    } else if packet.type != "heartbeat" { self.onPacket?(packet) }
                    self.lastReceived = ProcessInfo.processInfo.systemUptime
                }
                guard self.received.count < self.maxPacket else { self.fail(String(localized: "Local packet exceeded the size limit.")); return }
            }
            if done || error != nil { self.fail(error?.localizedDescription ?? String(localized: "Local session disconnected.")) }
            else { self.receive(attempt) }
        }
    }

    /// The shared key never travels over TCP. Both roles prove knowledge of it against
    /// fresh nonces, with direction binding to prevent echo/reflection and replay.
    private func authenticate(_ packet: LocalPacket) -> Bool {
        if packet.type == "hello" {
            guard peerNonce == nil, packet.handshakeRole == peerRole,
                  let nonce = packet.nonce, Self.decodeHex(nonce)?.count == 32 else { return false }
            peerNonce = nonce
            let data = transcript(senderRole: roleName, senderNonce: localNonce,
                                  receiverRole: peerRole, receiverNonce: nonce)
            let mac = HMAC<SHA256>.authenticationCode(for: data, using: SymmetricKey(data: Data(token.utf8)))
            let proof = mac.map { String(format: "%02x", $0) }.joined()
            write(LocalPacket(type: "authenticate", handshakeRole: roleName, proof: proof))
            return true
        }
        guard packet.type == "authenticate", packet.handshakeRole == peerRole,
              let peerNonce, let proof = packet.proof, let bytes = Self.decodeHex(proof), bytes.count == 32 else { return false }
        let data = transcript(senderRole: peerRole, senderNonce: peerNonce,
                              receiverRole: roleName, receiverNonce: localNonce)
        guard HMAC<SHA256>.isValidAuthenticationCode(bytes, authenticating: data,
                                                   using: SymmetricKey(data: Data(token.utf8))) else { return false }
        authorized = true
        onState?(true, String(localized: "Connected on this phone."))
        return true
    }

    private func transcript(senderRole: String, senderNonce: String, receiverRole: String, receiverNonce: String) -> Data {
        Data(["skycompanion-loopback-v1", senderRole, senderNonce, receiverRole, receiverNonce].joined(separator: "\n").utf8)
    }

    private static func decodeHex(_ value: String) -> Data? {
        guard value.count == 64, value.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else { return nil }
        var result = Data(); result.reserveCapacity(32)
        var index = value.startIndex
        while index < value.endIndex {
            let end = value.index(index, offsetBy: 2)
            guard let byte = UInt8(value[index..<end], radix: 16) else { return nil }
            result.append(byte); index = end
        }
        return result
    }

    private func write(_ packet: LocalPacket, completion: ((Bool) -> Void)? = nil) {
        guard let connection else { completion?(false); return }
        guard var data = try? JSONEncoder().encode(packet), data.count < maxPacket else {
            fail(String(localized: "Local result could not be encoded within the packet limit. Return to SkyCompanion to restart."))
            completion?(false)
            return
        }
        data.append(10)
        let isResult = packet.type == "result"
        if isResult { pendingSend = true }
        let attempt = epoch
        connection.send(content: data, completion: .contentProcessed { [weak self] error in
            guard let self, self.epoch == attempt else { completion?(false); return }
            if let error { completion?(false); self.fail(error.localizedDescription); return }
            completion?(true)
            if isResult {
                self.pendingSend = false
                if let latest = self.latestResult { self.latestResult = nil; self.write(latest) }
            }
        })
    }

    private func fail(_ message: String, notify: Bool = true) {
        epoch = UUID(); authorized = false; peerNonce = nil; localNonce = ""; timer?.cancel(); timer = nil
        connection?.stateUpdateHandler = nil; connection?.cancel(); connection = nil
        received.removeAll(); latestResult = nil; pendingSend = false
        if notify { onState?(false, message) }
    }

    private func stopInternal(notify: Bool = true) {
        listener?.stateUpdateHandler = nil; listener?.cancel(); listener = nil
        fail(String(localized: "Session ended."), notify: notify)
    }
}
