import AVFoundation
import Foundation
import Speech

/// Optional user-started, on-device command listening supports an audio background session.
/// ReplayKit never captures the microphone; no audio is saved or sent to the server.
@MainActor
final class VoiceModel: NSObject, ObservableObject, AVSpeechSynthesizerDelegate {
    @Published private(set) var enabled = false
    @Published private(set) var connected = false
    @Published private(set) var output = "off"
    @Published private(set) var status = "Phone voice is off. Keep SkyCompanionCapture open to receive alerts."
    @Published private(set) var lastSpoken = ""

    @Published private(set) var assistanceActive = false
    @Published private(set) var assistanceStarting = false
    @Published private(set) var microphoneStatus = "Microphone off"
    @Published private(set) var controlStatus = ""
    private let listener = CommandListener()
    private let synthesizer = AVSpeechSynthesizer()
    private var speechGeneration = UUID()
    private var assistanceGeneration = UUID()
    private var activeSpeech: AVSpeechUtterance?
    private var muted = false
    private var interruptedAssistance = false
    private var foreground = true
    private var mayReceive: Bool { foreground || assistanceActive }

    private var gate = VoiceEventGate()
    private var generation = UUID()
    private var session: URLSession?
    private var socket: URLSessionWebSocketTask?
    private var receiveTask: Task<Void, Never>?
    private var heartbeatTask: Task<Void, Never>?
    private var configuration: CaptureConfiguration?
    private let resolver = ReceiverResolver()
    struct InstalledVoice: Identifiable {
        let id: String
        let label: String
    }
    @Published private(set) var installedVoices: [InstalledVoice] = []
    @Published var selectedVoiceID = UserDefaults.standard.string(forKey: "skycompanion.voice.identifier") ?? "" {
        didSet { UserDefaults.standard.set(selectedVoiceID, forKey: "skycompanion.voice.identifier") }
    }
    @Published var speechRate: Float = UserDefaults.standard.object(forKey: "skycompanion.voice.rate") as? Float ?? 0.48 {
        didSet { UserDefaults.standard.set(speechRate, forKey: "skycompanion.voice.rate") }
    }
    private var speechStartDeadlineMS: Double?
    private var speechStarted = false
    private var startDeadlineTask: Task<Void, Never>?
    private var playingEventID: String?
    private var playingPriority: String?
    private var observers: [NSObjectProtocol] = []

    override init() {
        super.init()
        let center = NotificationCenter.default
        synthesizer.delegate = self
        refreshVoices()
        listener.onCommand = { [weak self] command in
            guard let self else { return }
            if command == .stop { self.stopAssistance(); return }
            Task {
                await self.command(command.rawValue)
                if self.activeSpeech == nil && self.assistanceActive {
                    self.releasePlaybackSession()
                }
            }
        }
        listener.onFailure = { [weak self] message in
            self?.stopAssistance()
            self?.microphoneStatus = message + " Return to SkyCompanion and start again."
        }
        observers.append(center.addObserver(forName: AVAudioSession.interruptionNotification,
                                             object: nil, queue: .main) { [weak self] notification in
            let raw = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            let options = notification.userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt ?? 0
            Task { @MainActor in
                guard let self else { return }
                if raw == AVAudioSession.InterruptionType.began.rawValue {
                    self.interruptedAssistance = self.assistanceActive
                    self.stopAssistance()
                    self.microphoneStatus = "Audio interrupted. Old alerts will not replay."
                } else if self.interruptedAssistance {
                    self.interruptedAssistance = false
                    if self.foreground && AVAudioSession.InterruptionOptions(rawValue: options).contains(.shouldResume) {
                        await self.startAssistance(configuration: self.configuration)
                    } else {
                        self.microphoneStatus = "Return to SkyCompanion and restart voice assistance after the interruption."
                    }
                }
            }
        })
        observers.append(center.addObserver(forName: AVAudioSession.routeChangeNotification,
                                             object: nil, queue: .main) { [weak self] notification in
            guard let raw = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt,
                  AVAudioSession.RouteChangeReason(rawValue: raw) == .oldDeviceUnavailable else { return }
            Task { @MainActor in
                self?.stopAssistance()
                self?.status = "Headphones disconnected. Voice assistance stopped; check output and restart."
            }
        })
    }

    func enable(configuration: CaptureConfiguration?) {
        guard let configuration else {
            status = "Voice needs the same local pairing configuration as screen capture."
            return
        }
        self.configuration = configuration
        enabled = true
        if foreground { connect() }
    }

    func disable() {
        stopAssistance()
        enabled = false
        disconnect()
        status = "Phone voice is off."
    }

    func setForeground(_ active: Bool) {
        foreground = active
        if active {
            if enabled { connect() }
        } else if !assistanceActive {
            disconnect()
            if enabled { status = "Foreground receiver paused. Start voice assistance before switching apps." }
        }
    }

    func testSound() {
        guard foreground else { return }
        // The deliberate sound check cannot preempt an actual obstacle alert.
        guard VoiceEventGate.mayInterrupt(incomingPriority: "test", currentPriority: playingPriority) else {
            status = "An obstacle alert is playing. Sound check skipped."
            return
        }
        beginSpeech("Sound check. Camera view alerts are enabled. Your direction is unverified.",
                    eventID: nil, priority: "test", deadlineMS: nowMS + 1_500)
    }

    private var nowMS: Double { ProcessInfo.processInfo.systemUptime * 1_000 }
    private var phoneSelected: Bool { output == "phone" || output == "both" }

    private func connect() {
        guard enabled, mayReceive, let configuration, receiveTask == nil else { return }
        let settings = URLSessionConfiguration.ephemeral
        settings.timeoutIntervalForRequest = 5
        settings.waitsForConnectivity = false
        let session = URLSession(configuration: settings)
        self.session = session
        let epoch = generation
        receiveTask = Task { [weak self] in
            guard let self else { return }
            var failedAttempts = 0
            while self.enabled && self.mayReceive && self.generation == epoch && !Task.isCancelled {
                self.status = "Finding paired receiver: known addresses and Bonjour…"
                do {
                    let resolved = try await self.resolver.resolve(configuration)
                    guard !Task.isCancelled, self.generation == epoch, self.mayReceive else { break }
                    self.configuration = resolved.configuration
                    self.status = "Receiver verified. Connecting phone voice…"
                    var request = URLRequest(url: resolved.configuration.voiceURL)
                    request.setValue("Bearer \(configuration.token)", forHTTPHeaderField: "Authorization")
                    let socket = session.webSocketTask(with: request)
                    self.socket = socket
                    socket.resume()
                    let openedAt = self.nowMS
                    self.heartbeatTask = Task { [weak self, weak socket] in
                        var lastPing = openedAt
                        while !Task.isCancelled {
                            do { try await Task.sleep(nanoseconds: 1_000_000_000) }
                            catch { return }
                            guard let self, let socket, self.socket === socket else { return }
                            if !self.connected && self.nowMS - openedAt > 5_000 {
                                socket.cancel(with: .goingAway, reason: nil)
                                return
                            }
                            guard self.connected, self.nowMS - lastPing >= 5_000 else { continue }
                            lastPing = self.nowMS
                            // One ping per five seconds, bounded by a 2.5-second watchdog.
                            let timeout = Task { [weak self, weak socket] in
                                do { try await Task.sleep(nanoseconds: 2_500_000_000) }
                                catch { return }
                                guard let self, let socket, self.socket === socket else { return }
                                socket.cancel(with: .goingAway, reason: nil)
                            }
                            socket.sendPing { error in
                                timeout.cancel()
                                if error != nil { socket.cancel(with: .goingAway, reason: nil) }
                            }
                        }
                    }
                    while !Task.isCancelled {
                        let message = try await socket.receive()
                        guard self.socket === socket, self.mayReceive, self.generation == epoch else { break }
                        let data: Data
                        switch message {
                        case .string(let value): data = Data(value.utf8)
                        case .data(let value): data = value
                        @unknown default: continue
                        }
                        self.handle(data)
                        if self.connected { failedAttempts = 0 }
                    }
                } catch {
                    if !Task.isCancelled && self.mayReceive && self.generation == epoch {
                        self.status = "Voice connection failed: \(error.localizedDescription). Retrying; old alerts are discarded."
                    }
                }
                guard self.generation == epoch else { break }
                self.heartbeatTask?.cancel(); self.heartbeatTask = nil
                self.stopAudio(stage: "interrupted")
                self.connected = false
                self.output = "off"
                self.socket?.cancel(with: .goingAway, reason: nil); self.socket = nil
                failedAttempts += 1
                let delay = ReceiverConnectionPolicy.retryDelay(attempt: failedAttempts)
                do { try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000)) }
                catch { break }
            }
            if self.generation == epoch { self.receiveTask = nil }
        }
    }

    private func disconnect() {
        generation = UUID()
        stopAudio(stage: "interrupted")
        receiveTask?.cancel(); receiveTask = nil
        heartbeatTask?.cancel(); heartbeatTask = nil
        socket?.cancel(with: .normalClosure, reason: nil); socket = nil
        session?.invalidateAndCancel(); session = nil
        connected = false
        output = "off"
    }

    private struct Envelope: Decodable {
        let type: String
        let output: String?
        let event: VoiceEvent?
    }

    private func handle(_ data: Data) {
        guard let message = try? JSONDecoder().decode(Envelope.self, from: data) else { return }
        switch message.type {
        case "voice_state":
            guard let route = message.output, ["off", "mac", "phone", "both"].contains(route) else { return }
            if !connected { sendCapability() }
            connected = true
            output = route
            if !phoneSelected { stopAudio(stage: "interrupted") }
            status = phoneSelected
                ? "Phone alerts connected. Check microphone status before switching apps."
                : "Connected. Choose Phone or Both below to receive alerts."
        case "voice_stop":
            stopAudio(stage: "interrupted")
            status = "Playback stopped. Waiting for a new, valid alert."
        case "voice_event":
            guard let event = message.event else { return }
            switch gate.receive(event, nowMS: nowMS, enabled: enabled && mayReceive && phoneSelected && !muted) {
            case .play(let deadline):
                acknowledge(event.id, stage: "received")
                beginSpeech(event.safeText, eventID: event.id, priority: event.priority, deadlineMS: deadline)
            case .expired:
                acknowledge(event.id, stage: "expired")
            case .disabled, .invalid:
                acknowledge(event.id, stage: "failed")
            case .duplicate:
                break
            }
        default: break
        }
    }

    func refreshVoices() {
        let voices = AVSpeechSynthesisVoice.speechVoices().filter { $0.language.hasPrefix("en-") }
            .sorted { a, b in
                if a.quality.rawValue != b.quality.rawValue { return a.quality.rawValue > b.quality.rawValue }
                if (a.language == "en-US") != (b.language == "en-US") { return a.language == "en-US" }
                return a.name.localizedStandardCompare(b.name) == .orderedAscending
            }
        installedVoices = voices.map { voice in
            let quality = voice.quality == .premium ? "Premium" : voice.quality == .enhanced ? "Enhanced" : "Standard"
            return InstalledVoice(id: voice.identifier, label: "\(voice.name) · \(voice.language) · \(quality)")
        }
        if !selectedVoiceID.isEmpty && !installedVoices.contains(where: { $0.id == selectedVoiceID }) { selectedVoiceID = "" }
    }

    private var preferredVoice: AVSpeechSynthesisVoice? {
        if !selectedVoiceID.isEmpty, let voice = AVSpeechSynthesisVoice(identifier: selectedVoiceID) { return voice }
        if let first = installedVoices.first { return AVSpeechSynthesisVoice(identifier: first.id) }
        return AVSpeechSynthesisVoice(language: "en-US")
    }

    private func beginSpeech(_ text: String, eventID: String?, priority: String, deadlineMS: Double) {
        guard VoiceEventGate.mayInterrupt(incomingPriority: priority, currentPriority: playingPriority) else {
            if let eventID { acknowledge(eventID, stage: "failed") }
            return
        }
        stopAudio(stage: "interrupted")
        guard mayReceive, VoiceEventGate.canStart(deadlineMS: deadlineMS, nowMS: nowMS) else {
            if let eventID { acknowledge(eventID, stage: "expired") }
            return
        }
        do {
            if !assistanceActive {
                let audio = AVAudioSession.sharedInstance()
                try audio.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
                try audio.setActive(true)
            }
            listener.suspendRecognition()
            guard VoiceEventGate.canStart(deadlineMS: deadlineMS, nowMS: nowMS) else {
                if let eventID { acknowledge(eventID, stage: "expired") }
                releasePlaybackSession()
                return
            }
            let utterance = AVSpeechUtterance(string: text)
            utterance.voice = preferredVoice
            utterance.rate = min(0.60, max(0.35, speechRate))
            activeSpeech = utterance
            playingEventID = eventID
            playingPriority = priority
            speechStartDeadlineMS = deadlineMS
            speechStarted = false
            // Cancel queued/cold-start synthesis if it misses the original observation deadline.
            startDeadlineTask = Task { [weak self, weak utterance] in
                guard let self else { return }
                let remaining = max(0, deadlineMS - self.nowMS)
                do { try await Task.sleep(nanoseconds: UInt64(remaining * 1_000_000)) } catch { return }
                guard self.activeSpeech === utterance, !self.speechStarted else { return }
                self.stopAudio(stage: "expired")
                self.status = "Speech start expired; waiting for a fresh alert."
            }
            synthesizer.speak(utterance)
            lastSpoken = text
            status = "Preparing phone speech…"
        } catch {
            stopAudio(stage: "failed")
            if let eventID { acknowledge(eventID, stage: "failed") }
            status = "Phone speech could not start."
        }
    }

    func startAssistance(configuration: CaptureConfiguration?) async {
        guard foreground, !assistanceActive, !assistanceStarting else { return }
        guard let configuration else { microphoneStatus = "Pair with a receiver first."; return }
        assistanceStarting = true
        let attempt = UUID(); assistanceGeneration = attempt
        microphoneStatus = "Requesting microphone and on-device speech permissions…"
        let microphone = await AVAudioApplication.requestRecordPermission()
        let speech: SFSpeechRecognizerAuthorizationStatus = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
        }
        guard assistanceGeneration == attempt else { return }
        assistanceStarting = false
        guard foreground, microphone, speech == .authorized else {
            microphoneStatus = "Microphone and Speech Recognition permissions are required. Open Settings, then retry in SkyCompanion."
            return
        }
        do {
            try listener.start()
            assistanceActive = true
            sendCapability()
            self.configuration = configuration
            enable(configuration: configuration)
            microphoneStatus = "Listening on this phone · English · microphone stays on across apps"
            await command("voice_output", extra: ["output": "phone"])
            speakStatus("Voice assistance is listening. Say SkyCompanion repeat, SkyCompanion why, SkyCompanion got it, or SkyCompanion mute.")
        } catch {
            listener.stop()
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
            microphoneStatus = "Could not start on-device English recognition: \(error.localizedDescription)"
        }
    }

    func stopAssistance() {
        assistanceGeneration = UUID()
        assistanceStarting = false
        assistanceActive = false
        sendCapability()
        listener.stop()
        stopAudio(stage: "interrupted")
        microphoneStatus = "Microphone off. Foreground alerts can still play while SkyCompanion is open."
        if !foreground { disconnect() }
    }

    func configure(_ configuration: CaptureConfiguration?) { self.configuration = configuration }

    func command(_ command: String, extra: [String: Any] = [:]) async {
        // Mute is immediate even if the network has just failed; listening remains enabled.
        if command == "mute" { muted = true; stopAudio(stage: "interrupted") }
        if command == "unmute" { muted = false }
        guard let configuration else { controlStatus = "Missing receiver configuration."; return }
        let epoch = generation
        var payload = extra; payload["command"] = command
        do {
            let resolved = try await resolver.resolve(configuration)
            guard generation == epoch else { return }
            self.configuration = resolved.configuration
            let started = nowMS
            var request = URLRequest(url: resolved.configuration.serverURL.appendingPathComponent("api/live/mobile/command"))
            request.httpMethod = "POST"
            request.timeoutInterval = 3
            request.setValue("Bearer \(configuration.token)", forHTTPHeaderField: "Authorization")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            // Only read-only resolution retries. A command POST is sent once, never replayed.
            request.httpBody = try JSONSerialization.data(withJSONObject: payload)
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                  let result = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  result["ok"] as? Bool == true else { throw URLError(.badServerResponse) }
            controlStatus = "Receiver accepted: \(command)."
            if let state = result["state"] as? [String: Any],
               let voice = state["voice"] as? [String: Any],
               let route = voice["output"] as? String { output = route }
            if let route = extra["output"] as? String { muted = route == "off"; output = route }
            // A delayed HTTP response must not replay a scene description after its useful lifetime.
            guard generation == epoch, nowMS - started < 1_500 else { return }
            if let reply = result["speech"] as? [String: Any], let code = reply["code"] as? String {
                var objects: [VoiceSceneObject]?
                if let rawObjects = reply["objects"], let encoded = try? JSONSerialization.data(withJSONObject: rawObjects) {
                    objects = try? JSONDecoder().decode([VoiceSceneObject].self, from: encoded)
                }
                guard let text = VoiceReply.text(code: code, direction: reply["direction"] as? String, objects: objects,
                                                 reasonCodes: reply["reason_codes"] as? [String]) else { return }
                var deadline = nowMS + 1_500
                if ["unconfirmed_obstacle", "no_confirmed_obstacle", "scene_summary", "no_stable_objects", "risk_explanation"].contains(code) {
                    guard let capture = reply["captured_uptime_ms"] as? Double,
                          let maxAge = reply["max_observation_age_ms"] as? Double,
                          capture.isFinite, maxAge.isFinite, maxAge > 0, maxAge <= 1_500,
                          nowMS >= capture, nowMS - capture < maxAge else {
                        controlStatus = "Description expired. Ask again for a fresh view."
                        return
                    }
                    deadline = min(deadline, capture + maxAge)
                    if let ttl = reply["ttl_ms"] as? Double {
                        guard ttl.isFinite, ttl > 0, ttl <= 1_500 else { return }
                        deadline = min(deadline, nowMS + ttl)
                    }
                }
                speakStatus(text, deadlineMS: deadline)
            } else if command == "mute" { speakStatus("Alerts muted. Listening remains on. Say SkyCompanion unmute to resume.") }
            else if command == "unmute" { speakStatus("Alerts enabled.") }
        } catch {
            controlStatus = "Receiver command failed. Check connection and retry."
            if command == "mute" { speakStatus("Phone alerts muted locally. Receiver unavailable.") }
            else { speakStatus("Receiver unavailable. Command not confirmed.") }
        }
    }

    func armTestAnalysis() async {
        await command("start", extra: ["arm_next_capture": true, "roi": [0, 0, 1, 1],
            "corridor": [[0.35, 0.45], [0.65, 0.45], [0.9, 1.0], [0.1, 1.0]]])
    }

    private func speakStatus(_ text: String, deadlineMS: Double? = nil) {
        guard mayReceive else { return }
        beginSpeech(text, eventID: nil, priority: "query", deadlineMS: deadlineMS ?? nowMS + 1_500)
    }

    private func releasePlaybackSession() {
        speechGeneration = UUID()
        let epoch = speechGeneration
        if assistanceActive {
            // Discard own voice and acoustic tail; reset recognition rather than concatenating it.
            Task { [weak self] in
                try? await Task.sleep(nanoseconds: 500_000_000)
                guard let self, self.speechGeneration == epoch,
                      self.activeSpeech == nil, self.assistanceActive else { return }
                self.listener.resumeRecognition()
            }
        } else {
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard let self, self.activeSpeech === utterance else { return }
            self.stopAudio(stage: "completed")
            self.status = "Ready for a new valid alert."
        }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            // stopAudio clears identity before cancelling; an old callback cannot resume STT over a new alert.
            guard let self, self.activeSpeech === utterance else { return }
            self.stopAudio(stage: "interrupted")
        }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didStart utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard let self, self.activeSpeech === utterance else { return }
            guard let deadline = self.speechStartDeadlineMS,
                  VoiceEventGate.canStart(deadlineMS: deadline, nowMS: self.nowMS), self.mayReceive else {
                self.stopAudio(stage: "expired")
                return
            }
            self.speechStarted = true
            self.startDeadlineTask?.cancel(); self.startDeadlineTask = nil
            if let eventID = self.playingEventID { self.acknowledge(eventID, stage: "started") }
            self.status = "Speaking on this phone."
        }
    }

    private func stopAudio(stage: String) {
        let eventID = playingEventID
        playingEventID = nil; playingPriority = nil
        speechStarted = false; speechStartDeadlineMS = nil
        startDeadlineTask?.cancel(); startDeadlineTask = nil
        if let eventID { acknowledge(eventID, stage: stage) }
        activeSpeech = nil
        synthesizer.stopSpeaking(at: .immediate)
        releasePlaybackSession()
    }

    private func sendCapability() {
        guard let socket else { return }
        let payload = ["type": "voice_capability", "capability": assistanceActive ? "active_speech_session" : "foreground_only"]
        guard let data = try? JSONSerialization.data(withJSONObject: payload) else { return }
        Task { try? await socket.send(.string(String(decoding: data, as: UTF8.self))) }
    }

    private func acknowledge(_ eventID: String, stage: String) {
        guard let socket,
              let data = try? JSONSerialization.data(withJSONObject: [
                "type": "voice_ack", "event_id": eventID, "stage": stage
              ]) else { return }
        Task { try? await socket.send(.string(String(decoding: data, as: UTF8.self))) }
    }


}

/// Thread-safe sink: the audio render callback never mutates UI or stores audio.
private final class SpeechBufferSink: @unchecked Sendable {
    private let lock = NSLock()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    func set(_ value: SFSpeechAudioBufferRecognitionRequest?) { lock.lock(); request = value; lock.unlock() }
    func append(_ buffer: AVAudioPCMBuffer) { lock.lock(); defer { lock.unlock() }; request?.append(buffer) }
}

@MainActor
private final class CommandListener {
    var onCommand: ((VoiceCommand) -> Void)?
    var onFailure: ((String) -> Void)?
    private let engine = AVAudioEngine()
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let sink = SpeechBufferSink()
    private var recognition: SFSpeechRecognitionTask?
    private var renewal: Task<Void, Never>?
    private var running = false
    private var suspended = false
    private var tapInstalled = false
    private var epoch = UUID()
    private var failures = 0
    private var commandCommit: Task<Void, Never>?

    func start() throws {
        guard let recognizer, recognizer.isAvailable, recognizer.supportsOnDeviceRecognition else {
            throw NSError(domain: "SkyCompanionSpeech", code: 1, userInfo: [NSLocalizedDescriptionKey:
                "On-device English recognition is unavailable. No cloud fallback is used."])
        }
        let audio = AVAudioSession.sharedInstance()
        try audio.setCategory(.playAndRecord, mode: .voiceChat,
                              options: [.mixWithOthers, .defaultToSpeaker, .allowBluetoothHFP])
        try audio.setActive(true)
        let input = engine.inputNode
        try input.setVoiceProcessingEnabled(true)
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else { throw URLError(.cannotDecodeRawData) }
        let sink = self.sink
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in sink.append(buffer) }
        tapInstalled = true
        engine.prepare()
        try engine.start()
        running = true; suspended = false; failures = 0
        beginRecognition()
    }

    func stop() {
        running = false; suspended = false
        resetRecognition()
        engine.stop()
        if tapInstalled { engine.inputNode.removeTap(onBus: 0); tapInstalled = false }
    }
    func suspendRecognition() { suspended = true; resetRecognition() }
    func resumeRecognition() {
        guard running, engine.isRunning else { return }
        suspended = false; beginRecognition()
    }
    private func resetRecognition() {
        epoch = UUID(); sink.set(nil)
        renewal?.cancel(); renewal = nil
        commandCommit?.cancel(); commandCommit = nil
        recognition?.cancel(); recognition = nil
    }
    private func beginRecognition() {
        guard running, !suspended else { return }
        resetRecognition()
        let current = epoch
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = true
        request.taskHint = .confirmation
        request.contextualStrings = ["SkyCompanion repeat", "SkyCompanion mute", "SkyCompanion unmute", "SkyCompanion describe", "SkyCompanion stop listening",
                                     "SkyCompanion why", "SkyCompanion got it", "SkyCompanion quieter", "SkyCompanion normal alerts", "SkyCompanion wrong alert",
                                     "SkyCompanion what is ahead", "SkyCompanion what obstacles are ahead",
                                     "SkyCompanion what is around me", "SkyCompanion what obstacles are around me"]
        sink.set(request)
        recognition = recognizer?.recognitionTask(with: request) { [weak self] result, error in
            let transcript = result?.bestTranscription.formattedString
            let final = result?.isFinal ?? false
            Task { @MainActor in
                guard let self, self.epoch == current, self.running, !self.suspended else { return }
                if let transcript {
                    self.failures = 0
                    self.commandCommit?.cancel()
                    if let command = VoiceCommand.parse(transcript) {
                        // Wait for a stable whole utterance; reject a longer continuation.
                        self.commandCommit = Task { [weak self] in
                            if !final { try? await Task.sleep(nanoseconds: 800_000_000) }
                            guard !Task.isCancelled, let self, self.epoch == current else { return }
                            self.suspendRecognition()
                            self.onCommand?(command)
                        }
                        return
                    }
                }
                if final || error != nil {
                    if error != nil { self.failures += 1 }
                    guard self.failures < 3 else { self.onFailure?("Speech recognition stopped after repeated failures."); return }
                    self.scheduleRenewal(after: error == nil ? 0.2 : 1.5, epoch: current)
                }
            }
        }
        scheduleRenewal(after: 50, epoch: current)
    }
    private func scheduleRenewal(after seconds: Double, epoch expected: UUID) {
        renewal?.cancel()
        renewal = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000)) } catch { return }
            guard let self, self.epoch == expected, self.running, !self.suspended else { return }
            self.beginRecognition()
        }
    }
}
