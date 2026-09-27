import AVFoundation
import Speech
import UIKit
import CaptureCore

@MainActor
final class LocalVoiceController: NSObject, ObservableObject, AVSpeechSynthesizerDelegate {
    @Published private(set) var listening = false
    @Published private(set) var starting = false
    @Published private(set) var status = String(localized: "Microphone off")
    @Published private(set) var lastSpoken = ""
    @Published private(set) var muted = false
    @Published private(set) var soundChecked = false
    @Published var voiceID = LocalVoiceController.savedEnglishVoiceID() {
        didSet { UserDefaults.standard.set(voiceID, forKey: "skycompanion.voice.identifier") }
    }
    @Published var rate: Float = UserDefaults.standard.object(forKey: "skycompanion.voice.rate") as? Float ?? 0.48 {
        didSet { UserDefaults.standard.set(rate, forKey: "skycompanion.voice.rate") }
    }
    var onCommand: ((MobileVoiceCommand) -> Void)?
    var onNavigationCommand: ((NavigationVoiceCommand) -> Void)?
    var backgroundNavigationActive = false
    var onUnavailable: ((String) -> Void)?
    var onPlayback: ((String, Double) -> Void)?
    var onDiagnostic: ((String) -> Void)?
    private let synth = AVSpeechSynthesizer()
    private let listener = CommandListener()
    private var pcmSpeech = false
    private var utterance: AVSpeechUtterance?
    private var utteranceStarted: (() -> Void)?
    private var utteranceBackgroundAllowed = false
    private var deadline = 0.0
    private var priority = -1
    private var commandResponse = false
    private var commandUtterance = false
    var commandPending = false
    private var generation = UUID()
    private var listeningGeneration = UUID()
    private var expiry: Task<Void, Never>?
    private var observers: [NSObjectProtocol] = []
    var foreground = true
    private var videoPlaybackActive = false
    private static func savedEnglishVoiceID() -> String {
        let saved = UserDefaults.standard.string(forKey: "skycompanion.voice.identifier") ?? ""
        guard let voice = AVSpeechSynthesisVoice(identifier: saved), voice.language.hasPrefix("en") else { return "" }
        return saved
    }
    var commandLocale: String { "en-US" }
    // Kept for the companion trip protocol; this app now runs exclusively in English.
    var chineseCommands: Bool { false }
    var listeningStatus: String { String(localized: "Listening on this iPhone · English") }
    var statusCommandHint: String {
        String(localized: "Say “SkyCompanion, are you working?” to check assistance.")
    }
    var installedVoices: [AVSpeechSynthesisVoice] {
        AVSpeechSynthesisVoice.speechVoices().filter {
            $0.language.hasPrefix("en") && !$0.voiceTraits.contains(.isNoveltyVoice)
        }.sorted {
            if $0.quality != $1.quality { return $0.quality.rawValue > $1.quality.rawValue }
            if ($0.language == "en-US") != ($1.language == "en-US") { return $0.language == "en-US" }
            if ($0.name == "Samantha") != ($1.name == "Samantha") { return $0.name == "Samantha" }
            return $0.identifier < $1.identifier
        }
    }
    var protectingCommand: Bool { commandPending || commandUtterance || (utterance != nil && commandResponse) }
    var activeSpeechText: String? { utterance?.speechString }
    var activeSpeechPriority: Int? { utterance == nil ? nil : priority }
    var selectedVoice: AVSpeechSynthesisVoice? {
        preferredVoice()
    }
    private func preferredVoice() -> AVSpeechSynthesisVoice? {
        let voices = installedVoices
        if let requested = voices.first(where: { $0.identifier == voiceID }) {
            // Keep the chosen voice character, upgrading its downloaded quality when available.
            return voices.first(where: { $0.name == requested.name && $0.language == requested.language
                && $0.quality.rawValue >= requested.quality.rawValue }) ?? requested
        }
        return voices.first // Premium, then enhanced, then the available basic voice.
    }
    var usingBasicVoice: Bool { selectedVoice?.quality == .default }
    var voiceDownloadHelp: String {
        String(localized: "Basic voice in use. In iPhone Settings → Accessibility → Spoken Content → Voices, download an English Enhanced or Premium voice, then return here.")
    }
    func voiceLabel(_ voice: AVSpeechSynthesisVoice) -> String {
        let quality = voice.quality == .premium ? String(localized: "Premium") :
            voice.quality == .enhanced ? String(localized: "Enhanced") : String(localized: "Standard")
        return "\(voice.name) · \(voice.language) · \(quality)"
    }
    var voiceDescription: String {
        selectedVoice.map(voiceLabel) ?? String(localized: "No local voice available for this language")
    }
    var hasEnhancedVoice: Bool { installedVoices.contains { $0.quality != .default } }
    var speechAvailable: Bool {
        let recognizer = SFSpeechRecognizer(locale: Locale(identifier: commandLocale))
        return recognizer?.supportsOnDeviceRecognition == true && recognizer?.isAvailable == true
    }
    var now: Double { ProcessInfo.processInfo.systemUptime * 1_000 }

    override init() {
        super.init()
        // Persist migration from a previously selected non-English voice.
        UserDefaults.standard.set(voiceID, forKey: "skycompanion.voice.identifier")
        synth.delegate = self
        listener.onCommand = { [weak self] command in
            guard let self else { return }
            self.onCommand?(command)
            if self.utterance == nil { self.resumeListeningAfterSpeech() }
        }
        listener.onNavigationCommand = { [weak self] command in
            guard let self else { return }
            self.onNavigationCommand?(command)
            if self.utterance == nil { self.resumeListeningAfterSpeech() }
        }
        listener.onCommandUtterance = { [weak self] active in self?.commandUtterance = active }
        listener.onAudioReset = { [weak self] in self?.cancelSpeech() }
        listener.onDiagnostic = { [weak self] text in self?.onDiagnostic?(text) }
        listener.onFailure = { [weak self] message in self?.unavailable(message) }
        let center = NotificationCenter.default
        observers.append(center.addObserver(forName: AVSpeechSynthesizer.availableVoicesDidChangeNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.objectWillChange.send() }
        })
        observers.append(center.addObserver(forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.objectWillChange.send() }
        })
        observers.append(center.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: .main) { [weak self] note in
            guard let kind = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                  kind == AVAudioSession.InterruptionType.began.rawValue else { return }
            Task { @MainActor in self?.unavailable(String(localized: "Audio interrupted. Return to SkyCompanion to restart assistance.")) }
        })
        observers.append(center.addObserver(forName: AVAudioSession.routeChangeNotification, object: nil, queue: .main) { [weak self] note in
            guard let raw = note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt,
                  raw == AVAudioSession.RouteChangeReason.oldDeviceUnavailable.rawValue else { return }
            Task { @MainActor in self?.unavailable(String(localized: "Headphones disconnected. Check the output before restarting.")) }
        })
    }

    func startListening() async -> Bool {
        guard foreground, !starting else { return false }
        if listening { return true }
        let attempt = UUID(); listeningGeneration = attempt
        starting = true; status = String(localized: "Checking microphone and on-device speech…")
        let microphone = await AVAudioApplication.requestRecordPermission()
        let speech = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
        }
        guard listeningGeneration == attempt else { return false }
        starting = false
        guard foreground, microphone, speech == .authorized, speechAvailable, selectedVoice != nil else {
            status = String(localized: "Microphone permission and on-device speech for the selected language are required. Check Settings; no cloud fallback is used.")
            return false
        }
        do {
            try listener.start(locale: commandLocale); listening = true
            status = listeningStatus
            return true
        } catch { listener.stop(); status = error.localizedDescription; return false }
    }

    func startRecordingAudio(id: String, channel: LoopbackChannel) {
        guard listening else { return }
        listener.recordingAudio.start(id: id, channel: channel)
    }
    var recordingAudioDiagnostics: String { listener.recordingAudio.diagnostics + " " + listener.audioDiagnostics }

    func checkAudioAfterBroadcastChange() {
        guard listening else { return }
        do { try listener.ensureAudioRunning(); onDiagnostic?("Broadcast audio check; " + listener.audioDiagnostics) }
        catch { unavailable("Audio could not restart. Restart voice assistance. " + error.localizedDescription) }
    }

    func finishRecordingAudio() async {
        await withCheckedContinuation { continuation in
            listener.recordingAudio.finish { continuation.resume() }
        }
    }
    func stopRecordingAudio() { listener.recordingAudio.stop() }

    func stopListening() {
        listeningGeneration = UUID(); starting = false; listening = false
        listener.stop(); cancelSpeech()
        if !videoPlaybackActive { try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation) }
        status = String(localized: "Microphone off")
    }

    /// AVPlayer and TTS share one audio session, even when the movie is muted.
    func beginVideoPlayback() throws {
        if listening { try listener.ensureAudioRunning() }
        else {
            let audio = AVAudioSession.sharedInstance()
            try audio.setCategory(.playback, mode: .default, options: [.mixWithOthers])
            try audio.setActive(true)
        }
        videoPlaybackActive = true
    }

    func endVideoPlayback() {
        videoPlaybackActive = false
        if !listening && utterance == nil {
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }

    private func unavailable(_ text: String) {
        stopListening(); status = text; onUnavailable?(text)
    }

    func setMuted(_ value: Bool, announce: Bool = true) {
        muted = value; cancelSpeech()
        guard announce else { return }
        speak(value ? String(localized: "Alerts muted. Listening remains on.") : String(localized: "Alerts enabled."), priority: 0, control: true)
    }

    func soundCheck() {
        guard foreground else { return }
        soundChecked = false
        let sample = "Hi. This is your Sky Companion voice preview. I'll keep reminders short."
        speak(sample, priority: 0, expires: now + 10_000, control: true)
    }

    @discardableResult
    func speak(_ text: String, priority incoming: Int = 0, expires: Double? = nil, control: Bool = false,
               onStarted: (() -> Void)? = nil, backgroundAllowed: Bool = false,
               onExpired: (() -> Void)? = nil) -> Bool {
        guard foreground || listening || backgroundNavigationActive || backgroundAllowed, !muted || control, !text.isEmpty,
              MobileGuidanceGate.mayStartSpeech(incoming: incoming, current: activeSpeechPriority, explicitRequest: control, protectingCommand: protectingCommand) else { return false }
        let until = expires ?? now + 3_000
        guard until.isFinite, until > now else { return false }
        cancelSpeech()
        guard let speechVoice = preferredVoice() else {
            status = String(localized: "No local voice for this response is available. Install the matching voice in iPhone Settings.")
            onUnavailable?(status); return false
        }
        do {
            if listening { try listener.ensureAudioRunning() }
            else {
                // A completed interruption may have deactivated the shared session.
                // Do not infer activation from the presence of a paused AVPlayer.
                if !videoPlaybackActive {
                    try AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
                }
                try AVAudioSession.sharedInstance().setActive(true)
            }
            onDiagnostic?("Speech requested; " + listener.audioDiagnostics)
            listener.suspendRecognition()
            let speech = AVSpeechUtterance(string: text)
            speech.voice = speechVoice
            speech.rate = min(0.60, max(0.35, rate))
            speech.pitchMultiplier = 1.0
            // Let the chosen voice model supply prosody. No added onset delay for warnings.
            speech.preUtteranceDelay = 0
            speech.postUtteranceDelay = 0
            utterance = speech; deadline = until; priority = incoming; commandResponse = control
            utteranceStarted = onStarted
            utteranceBackgroundAllowed = backgroundAllowed
            let token = generation
            expiry = Task { [weak self] in
                guard let self else { return }
                do { try await Task.sleep(nanoseconds: UInt64(max(0, until-self.now)*1_000_000)) } catch { return }
                if self.generation == token {
                    let failedOutput = self.pcmSpeech
                    self.onDiagnostic?("Speech start timed out; " + self.listener.audioDiagnostics)
                    self.cancelSpeech()
                    self.status = String(localized: "Speech expired before it could start.")
                    if let onExpired { onExpired() }
                    else if failedOutput { self.unavailable("Audio output did not start. Restart voice assistance and play the sound check.") }
                }
            }
            status = String(localized: "Preparing speech…")
            if listening {
                pcmSpeech = true
                let player = listener.speechPlayer
                let playback = player.begin(start: { [weak self] in
                    Task { @MainActor in self?.speechDidStart(speech) }
                }, finish: { [weak self] in
                    Task { @MainActor in
                        guard let self, self.utterance === speech else { return }
                        self.cancelSpeech(); self.status = self.listening ? self.listeningStatus : String(localized: "Microphone off")
                    }
                }, failure: { [weak self] message in
                    Task { @MainActor in
                        guard let self, self.utterance === speech else { return }
                        self.cancelSpeech(); self.status = message; self.onUnavailable?(message)
                    }
                })
                synth.write(speech) { buffer in player.append(buffer, token: playback) }
            } else {
                pcmSpeech = false; synth.speak(speech)
            }
            return true
        } catch {
            cancelSpeech(); status = String.localizedStringWithFormat(String(localized: "Speech failed: %@"), error.localizedDescription)
            onUnavailable?(status); return false
        }
    }

    func cancelSpeech() {
        generation = UUID(); expiry?.cancel(); expiry = nil
        utteranceStarted = nil; utteranceBackgroundAllowed = false
        utterance = nil; priority = -1; commandResponse = false; pcmSpeech = false
        listener.speechPlayer.stop(); synth.stopSpeaking(at: .immediate)
        resumeListeningAfterSpeech()
    }

    private func resumeListeningAfterSpeech() {
        let token = generation
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: 500_000_000)
            guard let self, self.generation == token, self.utterance == nil else { return }
            if self.listening { self.listener.resumeRecognition() }
            else if !self.videoPlaybackActive { try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation) }
        }
    }

    private func speechDidStart(_ speech: AVSpeechUtterance) {
        guard utterance === speech else { return }
        guard now < deadline, foreground || listening || backgroundNavigationActive else { cancelSpeech(); return }
        expiry?.cancel(); expiry = nil
        lastSpoken = speech.speechString; status = String(localized: "Speaking on this iPhone")
        let started = utteranceStarted; utteranceStarted = nil
        started?(); onPlayback?(speech.speechString, now)
        // Software playback start; actual hearing still needs the sound check.
    }
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didStart speech: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard let self, !self.pcmSpeech else { return }
            self.speechDidStart(speech)
        }
    }
    func confirmSoundHeard() { soundChecked = true }
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish speech: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard let self, !self.pcmSpeech, self.utterance === speech else { return }
            self.cancelSpeech(); self.status = self.listening ? self.listeningStatus : String(localized: "Microphone off")
        }
    }
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel speech: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            if self?.pcmSpeech == false, self?.utterance === speech { self?.cancelSpeech() }
        }
    }
}
