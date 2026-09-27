import Foundation
import os

/// Owns the network in the extension process, independently of the host app.
/// All mutable state below belongs to queue. A socket is replaced on any timeout;
/// stale callbacks are ignored by identity and never cross a session boundary.
final class BroadcastTransport: @unchecked Sendable {
    var onReadyChanged: ((Bool) -> Void)?
    var onFatalError: ((String) -> Void)?

    private let configuration: CaptureConfiguration
    private let resolver = ReceiverResolver()
    private var resolveTask: Task<Void, Never>?
    private var connectionEpoch = UUID()
    private let queue = DispatchQueue(label: "skycompanion.capture.transport", qos: .userInitiated)
    private let logger = Logger(subsystem: "SkyCompanionCapture", category: "broadcast")
    private let session: URLSession
    private var socket: URLSessionWebSocketTask?
    private var sessionID: String?
    private var timer: DispatchSourceTimer?
    private var reconnectWork: DispatchWorkItem?
    private var connectionStartedMS: Double = 0
    private var lastHeartbeatMS: Double = 0
    private var lastServerMessageMS: Double = 0
    private var retryCount = 0
    private var stopped = true
    private var paused = false
    private var window = FrameWindow()
    // URLSession can queue control messages too. Bound the control path to one
    // active send; heartbeat writes must not accumulate on a blocked connection.
    private var heartbeatInFlight = false
    private var pingStartedMS: Double?

    init(configuration: CaptureConfiguration) {
        self.configuration = configuration
        let settings = URLSessionConfiguration.ephemeral
        settings.timeoutIntervalForRequest = 10
        settings.waitsForConnectivity = false
        settings.urlCache = nil
        self.session = URLSession(configuration: settings)
    }

    func start() {
        queue.async { [self] in
            guard self.stopped else { return }
            self.stopped = false
            self.paused = false
            let timer = DispatchSource.makeTimerSource(queue: self.queue)
            timer.schedule(deadline: .now(), repeating: .milliseconds(250), leeway: .milliseconds(30))
            timer.setEventHandler { [weak self] in self?.tick() }
            self.timer = timer
            timer.resume()
            self.connect()
        }
    }

    func submit(_ frame: CaptureFrame) {
        queue.async {
            guard !self.stopped, !self.paused, self.sessionID != nil else { return }
            self.window.offer(frame)
            self.sendLatest()
        }
    }

    func pause() {
        queue.async {
            self.paused = true
            self.window.discardPendingAndReceipts()
            self.sendLifecycle("paused")
        }
    }

    func resume() {
        queue.async {
            self.paused = false
            self.window.discardPendingAndReceipts()
            self.sendLifecycle("resumed")
        }
    }

    func finish() {
        // ReplayKit may terminate this process as soon as broadcastFinished returns.
        // Mark state synchronously and enqueue a best-effort ended packet. A socket
        // close and the server heartbeat watchdog remain authoritative fallbacks.
        queue.sync {
            guard !stopped else { return }
            stopped = true
            timer?.cancel()
            timer = nil
            reconnectWork?.cancel()
            reconnectWork = nil
            resolveTask?.cancel()
            resolveTask = nil
            connectionEpoch = UUID()
            onReadyChanged?(false)
            window.clear()
            guard let socket, let sessionID else {
                cleanup()
                return
            }
            send(["type": "ended", "session_id": sessionID], over: socket) { [weak self] in
                self?.queue.async { self?.cleanup() }
            }
            queue.asyncAfter(deadline: .now() + 0.3) { [weak self] in self?.cleanup() }
        }
    }

    private func connect() {
        guard !stopped else { return }
        reconnectWork = nil
        sessionID = nil
        window.clear()
        heartbeatInFlight = false
        pingStartedMS = nil
        onReadyChanged?(false)
        resolveTask?.cancel()
        let epoch = UUID()
        connectionEpoch = epoch
        logger.notice("Resolving paired receiver before opening screen source.")
        resolveTask = Task { [weak self] in
            guard let self else { return }
            do {
                let resolved = try await self.resolver.resolve(self.configuration)
                guard !Task.isCancelled else { return }
                self.queue.async {
                    guard !self.stopped, self.connectionEpoch == epoch else { return }
                    self.resolveTask = nil
                    self.openSocket(configuration: resolved.configuration)
                }
            } catch {
                guard !Task.isCancelled else { return }
                self.queue.async {
                    guard !self.stopped, self.connectionEpoch == epoch else { return }
                    self.resolveTask = nil
                    self.logger.notice("Receiver resolution failed: \(error.localizedDescription, privacy: .public)")
                    self.scheduleReconnect()
                }
            }
        }
    }

    private func openSocket(configuration: CaptureConfiguration) {
        var request = URLRequest(url: configuration.sourceURL)
        request.setValue("Bearer \(configuration.token)", forHTTPHeaderField: "Authorization")
        let task = session.webSocketTask(with: request)
        task.maximumMessageSize = 64 * 1_024 // Server sends metadata, not images.
        socket = task
        connectionStartedMS = nowMS
        lastServerMessageMS = nowMS
        task.resume()
        receive(from: task)
        send(["type": "hello", "source": "screen_video_test", "device": "iPhone"], over: task)
    }

    private func receive(from task: URLSessionWebSocketTask) {
        task.receive { [weak self, weak task] result in
            guard let self, let task else { return }
            self.queue.async {
                guard !self.stopped, self.socket === task else { return }
                switch result {
                case .failure:
                    self.connectionLost(task)
                case .success(let message):
                    let data: Data
                    switch message {
                    case .string(let text): data = Data(text.utf8)
                    case .data(let bytes): data = bytes
                    @unknown default:
                        self.connectionLost(task)
                        return
                    }
                    guard let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                        self.connectionLost(task)
                        return
                    }
                    self.lastServerMessageMS = self.nowMS
                    self.handle(value, from: task)
                    if !self.stopped, self.socket === task { self.receive(from: task) }
                }
            }
        }
    }

    private func handle(_ message: [String: Any], from task: URLSessionWebSocketTask) {
        guard let type = message["type"] as? String else { return }
        if type == "session" {
            guard sessionID == nil, let id = message["session_id"] as? String, !id.isEmpty else {
                connectionLost(task)
                return
            }
            sessionID = id
            retryCount = 0
            window.clear()
            lastHeartbeatMS = 0
            onReadyChanged?(true)
            if paused { sendLifecycle("paused") }
            tick()
            return
        }
        if type == "error" {
            logger.error("Receiver reported a protocol or session error; ending broadcast.")
            fatal("The receiver rejected the broadcast. Check the Mac service, then check the connection again before sharing.")
            return
        }
        guard let id = message["session_id"] as? String, id == sessionID,
              let frameID = message["frame_id"] as? Int else { return }
        switch type {
        case "accepted":
            if window.accept(frameID: frameID) { sendLatest() }
        case "display_ack":
            if let latency = window.displayLatency(frameID: frameID, nowMS: nowMS), latency.isFinite {
                send(["type": "latency", "session_id": id, "frame_id": frameID, "roundtrip_ms": latency], over: task)
            }
        default: break
        }
    }

    private func sendLatest() {
        guard !stopped, !paused, let socket, let sessionID,
              let frame = window.take(nowMS: nowMS) else { return }
        send(["type": "frame", "session_id": sessionID, "frame_id": frame.id,
              "captured_ms": frame.capturedMS, "width": frame.width, "height": frame.height,
              "orientation": frame.orientation, "image_b64": frame.jpeg.base64EncodedString()], over: socket)
    }

    private func tick() {
        guard !stopped, let socket else { return }
        let now = nowMS
        guard let sessionID else {
            if now - connectionStartedMS > 6_000 { connectionLost(socket) }
            return
        }
        if window.acknowledgementExpired(nowMS: now) {
            connectionLost(socket)
            return
        }
        // If video is static/paused, no accepted messages are expected. A periodic
        // WebSocket ping checks the reverse path without treating duplicate pixels
        // as a failure. Use a timestamp watchdog so ping calls cannot accumulate.
        if let pingStartedMS, now - pingStartedMS > 2_500 {
            connectionLost(socket)
            return
        }
        if pingStartedMS == nil, now - lastServerMessageMS > 5_000 {
            pingStartedMS = now
            socket.sendPing { [weak self, weak socket] error in
                guard let self, let socket else { return }
                self.queue.async {
                    guard self.socket === socket else { return }
                    if error != nil { self.connectionLost(socket) }
                    else {
                        self.pingStartedMS = nil
                        self.lastServerMessageMS = self.nowMS
                    }
                }
            }
        }
        guard now - lastHeartbeatMS >= 1_000 else { return }
        if heartbeatInFlight {
            if now - lastHeartbeatMS > 2_500 { connectionLost(socket) }
            return
        }
        heartbeatInFlight = true
        lastHeartbeatMS = now
        send(["type": "heartbeat", "session_id": sessionID], over: socket) { [weak self, weak socket] in
            guard let self, let socket else { return }
            self.queue.async {
                if self.socket === socket { self.heartbeatInFlight = false }
            }
        }
    }

    private func sendLifecycle(_ type: String) {
        guard !stopped, let socket, let sessionID else { return }
        send(["type": type, "session_id": sessionID], over: socket)
    }

    private func send(_ object: [String: Any], over task: URLSessionWebSocketTask, completion: (() -> Void)? = nil) {
        guard let data = try? JSONSerialization.data(withJSONObject: object) else { return }
        task.send(.string(String(decoding: data, as: UTF8.self))) { [weak self, weak task] error in
            completion?()
            guard error != nil, let self, let task else { return }
            self.queue.async {
                if !self.stopped, self.socket === task { self.connectionLost(task) }
            }
        }
    }

    private func connectionLost(_ failed: URLSessionWebSocketTask) {
        guard !stopped, socket === failed else { return }
        socket = nil
        sessionID = nil
        window.clear()
        heartbeatInFlight = false
        pingStartedMS = nil
        failed.cancel(with: .goingAway, reason: nil)
        onReadyChanged?(false)
        scheduleReconnect()
    }

    private func scheduleReconnect() {
        guard !stopped else { return }
        reconnectWork?.cancel()
        retryCount += 1
        logger.notice("Screen source disconnected; retry \(self.retryCount, privacy: .public).")
        let delay = ReceiverConnectionPolicy.retryDelay(attempt: retryCount)
        let work = DispatchWorkItem { [weak self] in self?.connect() }
        reconnectWork = work
        queue.asyncAfter(deadline: .now() + delay, execute: work)
    }

    private func fatal(_ message: String) {
        stopped = true
        timer?.cancel()
        timer = nil
        reconnectWork?.cancel()
        reconnectWork = nil
        onReadyChanged?(false)
        cleanup()
        // ReplayKit may synchronously call lifecycle callbacks after finishWithError.
        // Invoke it outside the transport queue so finish() cannot deadlock.
        let report = onFatalError
        DispatchQueue.global(qos: .userInitiated).async { report?(message) }
    }

    private func cleanup() {
        resolveTask?.cancel()
        resolveTask = nil
        connectionEpoch = UUID()
        socket?.cancel(with: .normalClosure, reason: nil)
        socket = nil
        sessionID = nil
        window.clear()
        session.invalidateAndCancel()
    }

    private var nowMS: Double { ProcessInfo.processInfo.systemUptime * 1_000 }
}
