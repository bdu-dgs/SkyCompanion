import Foundation
import AVFoundation
import Speech
import CaptureCore

/// Thread-safe sink: the audio render callback never mutates UI or stores audio.
private final class SpeechBufferSink: @unchecked Sendable {
    private let lock = NSLock()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    func set(_ value: SFSpeechAudioBufferRecognitionRequest?) { lock.lock(); request = value; lock.unlock() }
    func append(_ buffer: AVAudioPCMBuffer) { lock.lock(); defer { lock.unlock() }; request?.append(buffer) }
}

@MainActor
final class CommandListener {
    var onCommand: ((MobileVoiceCommand) -> Void)?
    var onNavigationCommand: ((NavigationVoiceCommand) -> Void)?
    var onFailure: ((String) -> Void)?
    var onAudioReset: (() -> Void)?
    var onDiagnostic: ((String) -> Void)?
    private var configurationObserver: NSObjectProtocol?
    private var recovery: Task<Void, Never>?
    private var recoveryWindow = 0.0
    private var recoveryAttempts = 0
    var onCommandUtterance: ((Bool) -> Void)?
    private let engine = AVAudioEngine()
    let recordingAudio = RecordingAudioRelay()
    let speechPlayer = SpeechPCMPlayer()
    private var outputTapInstalled = false
    private var speechGraphInstalled = false
    private var recognizer: SFSpeechRecognizer?
    private let sink = SpeechBufferSink()
    private var recognition: SFSpeechRecognitionTask?
    private var renewal: Task<Void, Never>?
    private var running = false
    private var suspended = false
    private var tapInstalled = false
    private var epoch = UUID()
    private var failures = 0
    private var commandCommit: Task<Void, Never>?
    private var commandDebounce = MobileCommandDebounce()
    private var reportedWake = false

    init() {
        configurationObserver = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.scheduleAudioRecovery() }
        }
    }

    var audioDiagnostics: String {
        let audio = AVAudioSession.sharedInstance()
        let outputs = audio.currentRoute.outputs.map { "\($0.portType.rawValue):\($0.portName)" }.joined(separator: ",")
        let inputs = audio.currentRoute.inputs.map { "\($0.portType.rawValue):\($0.portName)" }.joined(separator: ",")
        return "engineRunning=\(engine.isRunning), listeningRequested=\(running), recognitionSuspended=\(suspended), volume=\(audio.outputVolume), input=\(inputs), output=\(outputs), sampleRate=\(audio.sampleRate)"
    }

    private func scheduleAudioRecovery() {
        guard running, !engine.isRunning else { return }
        let now = ProcessInfo.processInfo.systemUptime
        if now - recoveryWindow > 5 { recoveryWindow = now; recoveryAttempts = 0 }
        recoveryAttempts += 1
        guard recoveryAttempts <= 3 else {
            onFailure?("Audio repeatedly stopped. Restart voice assistance and check the output device.")
            return
        }
        onDiagnostic?("Audio configuration changed; " + audioDiagnostics)
        // Cancel pending observations, not replay them after the hardware restarts.
        onAudioReset?()
        recovery?.cancel()
        recovery = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 200_000_000)
            guard !Task.isCancelled, let self, self.running else { return }
            do { try self.ensureAudioRunning() }
            catch { self.onFailure?("Audio could not restart. Restart voice assistance. " + error.localizedDescription) }
        }
    }

    func ensureAudioRunning() throws {
        guard running else { return }
        if !engine.isRunning {
            resetRecognition()
            try startAudioEngine()
            if !suspended { beginRecognition() }
            onDiagnostic?("Audio engine recovered; " + audioDiagnostics)
        }
    }

    func start(locale: String) throws {
        recognizer = SFSpeechRecognizer(locale: Locale(identifier: locale))
        guard let recognizer, recognizer.isAvailable, recognizer.supportsOnDeviceRecognition else {
            throw NSError(domain: "SkyCompanionSpeech", code: 1, userInfo: [NSLocalizedDescriptionKey:
                String(localized: "On-device recognition for the selected language is unavailable. No cloud fallback is used.")])
        }
        try startAudioEngine()
        running = true; suspended = false; failures = 0
        onDiagnostic?("Audio engine started; " + audioDiagnostics)
        beginRecognition()
    }

    private func startAudioEngine() throws {
        engine.stop()
        if outputTapInstalled { speechPlayer.mixer.removeTap(onBus: 0); outputTapInstalled = false }
        if tapInstalled { engine.inputNode.removeTap(onBus: 0); tapInstalled = false }
        let audio = AVAudioSession.sharedInstance()
        try audio.setCategory(.playAndRecord, mode: .voiceChat,
                              options: [.mixWithOthers, .defaultToSpeaker, .allowBluetoothHFP])
        try audio.setActive(true)
        try audio.setAllowHapticsAndSystemSoundsDuringRecording(true)
        let input = engine.inputNode
        if !input.isVoiceProcessingEnabled { try input.setVoiceProcessingEnabled(true) }
        // Keep echo cancellation without strongly ducking AVPlayer's original sound.
        input.voiceProcessingOtherAudioDuckingConfiguration = .init(enableAdvancedDucking: false, duckingLevel: .min)
        if !speechGraphInstalled {
            engine.attach(speechPlayer.node); engine.attach(speechPlayer.mixer)
            engine.connect(speechPlayer.node, to: speechPlayer.mixer, format: speechPlayer.format)
            engine.connect(speechPlayer.mixer, to: engine.mainMixerNode, format: speechPlayer.format)
            speechGraphInstalled = true
        }
        let relay = recordingAudio
        let player = speechPlayer
        speechPlayer.onActive = { active in relay.setSpeechActive(active) }
        speechPlayer.mixer.installTap(onBus: 0, bufferSize: 1024, format: speechPlayer.format) { buffer, time in
            relay.capture(buffer, at: time, source: .speech)
            player.didRender(buffer)
        }
        outputTapInstalled = true
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else { throw URLError(.cannotDecodeRawData) }
        let sink = self.sink
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, time in
            sink.append(buffer)
            relay.capture(buffer, at: time, source: .microphone)
        }
        tapInstalled = true
        engine.prepare()
        try engine.start()
    }

    func stop() {
        recovery?.cancel(); recovery = nil
        running = false; suspended = false
        resetRecognition()
        recordingAudio.stop(); speechPlayer.stop()
        engine.stop()
        if outputTapInstalled { speechPlayer.mixer.removeTap(onBus: 0); outputTapInstalled = false }
        if tapInstalled { engine.inputNode.removeTap(onBus: 0); tapInstalled = false }
    }
    func suspendRecognition() { suspended = true; resetRecognition() }
    func resumeRecognition() {
        guard running, engine.isRunning else { return }
        suspended = false; beginRecognition()
    }
    private func resetRecognition() {
        onCommandUtterance?(false)
        epoch = UUID(); sink.set(nil)
        renewal?.cancel(); renewal = nil
        commandCommit?.cancel(); commandCommit = nil
        commandDebounce = MobileCommandDebounce(); reportedWake = false
        recognition?.cancel(); recognition = nil
    }
    private func beginRecognition() {
        guard running, !suspended else { return }
        resetRecognition()
        let current = epoch
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = true
        request.taskHint = .dictation
        request.contextualStrings = ["SkyCompanion status", "SkyCompanion are you working", "SkyCompanion repeat", "SkyCompanion mute", "SkyCompanion unmute", "SkyCompanion describe", "SkyCompanion stop listening",
                                     "SkyCompanion why", "SkyCompanion got it", "SkyCompanion quieter", "SkyCompanion normal alerts", "SkyCompanion wrong alert",
                                     "SkyCompanion what is ahead", "SkyCompanion what obstacles are ahead",
                                     "SkyCompanion what is around me", "SkyCompanion what obstacles are around me",
                                     "SkyCompanion path", "SkyCompanion path status", "SkyCompanion pause analysis", "SkyCompanion resume analysis", "SkyCompanion end assistance",
                                     "SkyCompanion navigate to", "SkyCompanion take me to", "SkyCompanion directions to",
                                     "SkyCompanion cancel navigation", "SkyCompanion stop navigation", "SkyCompanion navigation status",
                                     "SkyCompanion option one", "SkyCompanion option two", "SkyCompanion option three"]
            .flatMap { [$0, $0.replacingOccurrences(of: "SkyCompanion", with: "Sky Companion")] }
        sink.set(request)
        recognition = recognizer?.recognitionTask(with: request) { [weak self] result, error in
            let transcription = result?.bestTranscription
            var transcript = transcription?.formattedString
            if let transcription {
                let start = MobileSpeechInput.utteranceStart(in: transcription.segments.map {
                    .init(text: $0.substring, timestamp: $0.timestamp, duration: $0.duration)
                })
                if start > 0 {
                    let offset = transcription.segments[start].substringRange.location
                    let original = transcription.formattedString as NSString
                    if offset < original.length { transcript = original.substring(from: offset) }
                }
            }
            let commandTranscript = transcript
            let final = result?.isFinal ?? false
            Task { @MainActor in
                guard let self, self.epoch == current, self.running, !self.suspended else { return }
                if let transcript = commandTranscript {
                    let woke = MobileSpeechInput.startsWakePhrase(transcript)
                    self.onCommandUtterance?(woke)
                    if woke && !self.reportedWake {
                        self.reportedWake = true
                        self.onDiagnostic?("Voice wake phrase detected; waiting for a complete command.")
                    }
                    self.failures = 0
                    if let command = NavigationVoiceCommand.parse(transcript) {
                        guard self.commandDebounce.shouldSchedule(key: "navigation:" + transcript, isFinal: final) else { return }
                        self.commandCommit?.cancel()
                        // A destination is open-ended: each partial result restarts this delay,
                        // preserving the entire address instead of committing the first place name.
                        let delay: UInt64
                        if case .destination = command { delay = 1_400_000_000 }
                        else { delay = final ? 0 : 800_000_000 }
                        self.commandCommit = Task { [weak self] in
                            if delay > 0 { try? await Task.sleep(nanoseconds: delay) }
                            guard !Task.isCancelled, let self, self.epoch == current else { return }
                            self.suspendRecognition()
                            self.onDiagnostic?("Voice navigation command accepted.")
                            self.onNavigationCommand?(command)
                        }
                        return
                    }
                    if let command = MobileVoiceCommand.parse(transcript) {
                        guard self.commandDebounce.shouldSchedule(key: command.rawValue, isFinal: final) else { return }
                        self.commandCommit?.cancel()
                        // Wait for a stable whole utterance; reject a longer continuation.
                        self.commandCommit = Task { [weak self] in
                            if !final { try? await Task.sleep(nanoseconds: 800_000_000) }
                            guard !Task.isCancelled, let self, self.epoch == current else { return }
                            self.suspendRecognition()
                            self.onDiagnostic?("Voice command accepted: \(command.rawValue).")
                            self.onCommand?(command)
                        }
                        return
                    }
                    self.commandCommit?.cancel(); self.commandCommit = nil
                    _ = self.commandDebounce.shouldSchedule(key: nil, isFinal: final)
                    if final && woke { self.onDiagnostic?("Voice wake phrase heard, but the complete command was not matched.") }
                }
                if final || error != nil {
                    self.onCommandUtterance?(false)
                    if let error {
                        self.failures += 1
                        let failure = error as NSError
                        self.onDiagnostic?("Local speech recognition error: \(failure.domain) \(failure.code).")
                    }
                    guard self.failures < 3 else { self.onFailure?(String(localized: "Speech recognition stopped after repeated failures.")); return }
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
