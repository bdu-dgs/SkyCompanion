import Foundation
import SwiftUI
import AVFoundation
import CaptureCore
import Combine
import ImageIO
import AudioToolbox
import CryptoKit
import Photos

@MainActor
final class LocalSessionModel: NSObject, ObservableObject {
    enum Phase: String { case idle = "Not started", preparing = "Preparing", preview = "Confirm video area", armed = "Ready — switch to DJI Fly", starting = "Starting analysis…", running = "Analyzing", paused = "Paused", unavailable = "Unavailable" }
    enum Source: String, CaseIterable { case drone = "DJI Fly", video = "Local video" }
    @Published private(set) var phase: Phase = .idle
    @Published private(set) var message = String(localized: "All scene processing happens on this iPhone.")
    @Published private(set) var connected = false
    @Published private(set) var broadcastPrepared = false
    private var broadcastRequest = UUID()
    @Published private(set) var recordingStatus = "Stop Recording saves screen video to Photos."
    @Published private(set) var savingRecording = false
    @Published private(set) var recordingActive = false
    private var recordingCompletion: CheckedContinuation<String, Never>?
    private var recordingTimeout: Task<Void, Never>?
    // Historical confirmation only. Never used for scene guidance or speech.
    @Published private(set) var analyzedFrameCount = 0
    @Published private(set) var lastAnalysisDate: Date?
    @Published private(set) var analysisAttempted = false
    @Published private(set) var frame: MobileFrameResult?
    @Published private(set) var assessment: MobileRiskAssessment?
    @Published private(set) var summary: MobileSceneSummary?
    @Published private(set) var preview: UIImage?
    /// A paired local-video inspection snapshot; never used for live speech or risk decisions.
    @Published private(set) var inspection: LocalPacket?
    @Published private(set) var log: [String] = []
    @Published private(set) var depthResult: MobileDepthResult?
    @Published private(set) var pathObservation: MobilePathObservation?
    @Published private(set) var walkingObservation: MobileWalkingObservation?
    private var walkingSpeech: String?
    private var lastOrdinaryWalkingAt = -Double.infinity
    @Published private(set) var pathConfigured = false
    @Published private(set) var wearerConfigured = false
    @Published private(set) var wearerObservation: MobileWearerObservation?
    @Published var depthEnabled = false {
        didSet {
            settings.depthEnabled = depthEnabled
            settings.revision &+= 1; clearObservations()
            if source == .drone { channel?.send(LocalPacket(type: "settings", settings: settings)) }
            else if settings.analyze { videoPipeline.configure(settings) }
            recordPerformance("depth_configuration_changed")
        }
    }
    @Published private(set) var fps = 0.0
    @Published private(set) var memoryMB = 0.0
    @Published private(set) var frameAgeMS = 0.0
    @Published private(set) var modelDescription = String(localized: "Checking bundled model…")
    @Published private(set) var modelAvailable = false
    @Published private(set) var player: AVPlayer?
    @Published private(set) var source: Source = .drone
    @Published private(set) var stabilityTestSeconds: Int?
    private var stabilityTestStartedMS: Double?
    @Published private var areaSelection = CaptureAreaSelection(saved: CaptureRegion.saved())
    var region: CaptureRegion {
        get { areaSelection.draft }
        set { areaSelection.draft = newValue }
    }
    @Published var regionConfirmed = false
    @Published private(set) var recordingAreaConfirmed = false
    var videoAreaStatus: String {
        if !regionConfirmed || lastRegion != region {
            return lastRegion == region ? "Saved area — apply for this session." : "Changes not applied."
        }
        if !connected { return "Saved on iPhone. Start the broadcast to use this area." }
        return recordingAreaConfirmed ? "Applied — recording crop confirmed." : "Area saved. Waiting for broadcast confirmation…"
    }
    @Published var quieter = false
    @Published var vibrationEnabled = UserDefaults.standard.object(forKey: "skycompanion.vibration") as? Bool ?? true {
        didSet { UserDefaults.standard.set(vibrationEnabled, forKey: "skycompanion.vibration") }
    }
    @Published var saveEvidence = false {
        didSet {
            settings.captureEvidence = saveEvidence; settings.revision &+= 1; clearObservations()
            if !saveEvidence { latestEvidence = nil }
            if source == .drone { channel?.send(LocalPacket(type: "settings", settings: settings)) }
            else if settings.analyze { videoPipeline.configure(settings) }
        }
    }
    let voice = LocalVoiceController()
    let photon = PhotonCompanion()
    let navigation = NavigationController()
    private var navigationSubscription: AnyObject?
    private var lastNavigationSpeech: String?
    private var navigationQuietUntil = 0.0
    private var lastAlertDiagnosticAt = -Double.infinity
    @Published private(set) var tripSummary = ""
    @Published private(set) var lastReportedAlert = ""
    @Published var readCompanionMessages = UserDefaults.standard.object(forKey: "skycompanion.agent.read") as? Bool ?? true {
        didSet { UserDefaults.standard.set(readCompanionMessages, forKey: "skycompanion.agent.read") }
    }
    private var companionTrip: CompanionTrip?
    private var companionSpeech = CompanionSpeechQueue()
    private var lastSpokenAlert: (eventID: String, sessionID: String, frameID: UInt64, text: String, snapshot: LocalPacket)?
    private var photonSubscription: AnyObject?
    var hasCompanionTrip: Bool { companionTrip != nil }
    var canReportAlert: Bool { lastSpokenAlert != nil }
    private var channel: LoopbackChannel?
    private let videoPipeline = LocalVisionPipeline()
    private var settings = LocalCaptureSettings(sessionID: UUID().uuidString, revision: 0, region: CaptureRegion(),
        corridor: [MobilePoint(x: 0.35, y: 0.45), MobilePoint(x: 0.65, y: 0.45), MobilePoint(x: 0.9, y: 1), MobilePoint(x: 0.1, y: 1)], analyze: false)
    private var output: AVPlayerItemVideoOutput?
    private var currentVideoURL: URL?
    private var videoSHA256: String?
    private var displayLink: CADisplayLink?
    private var videoOrientation: CGImagePropertyOrientation = .up
    private var frameTimes: [Double] = []
    private var foreground = true
    private var watchdog: Task<Void, Never>?
    private var observers: [NSObjectProtocol] = []
    private var lastResultAt = 0.0
    private var statusFailure: MobileAssistanceStatus = .unavailable
    private var statusAnnouncements = MobileStatusAnnouncements()
    private var lastObservedStatus: MobileAssistanceStatus?
    private var statusSpeech: (state: MobileAssistanceStatus, text: String)?
    private struct DescribeRequest {
        let id: UUID
        let sessionID: String
        let revision: UInt64
        let deadline: Double
    }
    private var describeGeneration = UUID()
    private var pendingDescribe: DescribeRequest?
    private var lastDiagnosticAt = 0.0
    private var lastEventID: String?
    private var guidanceGate = MobileGuidanceGate()
    private var cameraAlertRetry = MobileCameraAlertRetry()
    private var startedWaitingAt = 0.0
    private var lastVideoTime: Double?
    private var latestEvidence: LocalPacket?
    private var lastRegion: CaptureRegion? { areaSelection.applied }
    private var activeRecordingID: String?
    private var speechSubscription: AnyObject?
    private var sessionRequest = UUID()
    private var now: Double { ProcessInfo.processInfo.systemUptime * 1_000 }

    override init() {
        super.init()
        // Forward nested observable changes so every screen reflects actual speech state.
        speechSubscription = voice.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() } as AnyObject
        photonSubscription = photon.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() } as AnyObject
        navigationSubscription = navigation.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() } as AnyObject
        navigation.onInvalidateGuidance = { [weak self] in
            guard let self else { return }
            if let text = self.lastNavigationSpeech, self.voice.activeSpeechText == text,
               self.voice.activeSpeechPriority == -1 { self.voice.cancelSpeech() }
            self.lastNavigationSpeech = nil
        }
        navigation.onPrompt = { [weak self] text in
            guard let self, self.now >= self.navigationQuietUntil,
                  !self.voice.protectingCommand,
                  (self.voice.activeSpeechPriority ?? -3) < -1 else { return false }
            self.voice.backgroundNavigationActive = self.navigation.isActive
            let accepted = self.voice.speak(text, priority: -1, expires: self.now + 1_500)
            if accepted { self.lastNavigationSpeech = text }
            return accepted
        }
        navigation.onAnnouncement = { [weak self] text in
            guard let self else { return }
            let finishingBackgroundRoute = self.voice.backgroundNavigationActive
            self.voice.backgroundNavigationActive = self.navigation.isActive
            // Route status never protects a command reply against an obstacle alert.
            if self.voice.speak(text, priority: -1, expires: self.now + 5_000, backgroundAllowed: finishingBackgroundRoute) { self.lastNavigationSpeech = text }
        }
        voice.onNavigationCommand = { [weak self] command in self?.handleNavigation(command) }
        photon.onMessage = { [weak self] incoming in
            guard let self, incoming.kind != "summary" else { return } // End summaries already read locally, including offline.
            self.queueCompanionSpeech(id: incoming.id, text: incoming.text)
        }
        if let folder = try? evidenceDirectory(), let saved = try? String(contentsOf: folder.appendingPathComponent("last-trip-summary.txt"), encoding: .utf8) {
            tripSummary = saved
        }
        voice.onCommand = { [weak self] command in self?.handle(command) }
        voice.onUnavailable = { [weak self] message in self?.unavailable(message, speak: false, failure: .audioUnavailable) }
        voice.onDiagnostic = { [weak self] text in
            self?.appendLog(text); self?.recordPerformance("audio_output", message: text)
        }
        voice.onPlayback = { [weak self] spoken, time in
            self?.statusSpeechDidStart(spoken)
            self?.appendLog(String.localizedStringWithFormat(String(localized: "Speech API started at %lld ms. Acoustic onset not measured."), Int(time))) }
        videoPipeline.onPacket = { [weak self] packet in Task { @MainActor in
            guard let self, self.source == .video else { return }; self.receive(packet)
        } }
        UIDevice.current.isBatteryMonitoringEnabled = true
        checkModel()
        appendLog("Local voice: \(voice.voiceDescription); rate=\(voice.rate)")
        watchdog = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 250_000_000)
                guard !Task.isCancelled, let self else { return }
                if let start = self.stabilityTestStartedMS {
                    self.stabilityTestSeconds = Int((self.now-start)/1_000)
                    if self.now-start >= 1_800_000 {
                        self.recordPerformance("stability_test_finished")
                        self.pause()
                        self.message = String(localized: "30-minute local video test finished. Review the recorded measurements; this does not verify DJI Fly.")
                    }
                }
                if let frame = self.frame { self.frameAgeMS = max(0, self.now-frame.capturedUptimeMS) }
                if self.phase == .starting && self.settings.analyze && self.now-self.startedWaitingAt > 30_000 {
                    self.unavailable(String(localized: "No fresh result arrived within 30 seconds. Check the source and model in SkyCompanion."), failure: .interrupted)
                }
                if self.phase == .running && self.frame?.isFresh(at: self.now) != true {
                    self.unavailable(String(localized: "The camera view is no longer fresh. Reconfirm the source in SkyCompanion."), failure: .interrupted)
                }
                self.refreshStatusAnnouncement()
                self.pumpDescription()
                self.voice.backgroundNavigationActive = self.navigation.isActive
                self.photon.setSessionActive(self.voice.listening || self.navigation.isActive)
                self.pumpCompanionSpeech()
            }
        }
        observers.append(NotificationCenter.default.addObserver(forName: UIApplication.protectedDataWillBecomeUnavailableNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.endSession(reason: String(localized: "Phone locked. Start a new session after unlocking."), stopNavigation: false) }
        })
        observers.append(NotificationCenter.default.addObserver(forName: .AVPlayerItemDidPlayToEndTime, object: nil, queue: .main) { [weak self] note in
            guard let item = note.object as? AVPlayerItem else { return }
            Task { @MainActor in
                guard let self, item === self.player?.currentItem else { return }
                if self.stabilityTestStartedMS != nil, self.phase == .running || self.phase == .starting {
                    self.recordPerformance("video_loop")
                    self.playVideo()
                } else {
                    self.pause(); self.message = String(localized: "Video finished. Replay to start a fresh test.")
                    self.finishCompanionTrip(reason: "Recorded video finished")
                }
            }
        })
    }

    func checkModel() {
        guard let manifest = Bundle.main.url(forResource: "selectedModel", withExtension: "json"),
              let data = try? Data(contentsOf: manifest), let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let name = json["resourceName"] as? String else {
            modelAvailable = false; modelDescription = String(localized: "No Core ML model is bundled. This build cannot analyze video."); return
        }
        modelAvailable = Bundle.main.url(forResource: name, withExtension: "mlmodelc") != nil
        let size = json["inputSize"] as? Int ?? 0
        let title = json["displayName"] as? String ?? name
        let count = (json["names"] as? [String])?.count ?? 0
        let output = (json["maskChannels"] as? Int ?? 0) > 0 ? "boxes and masks" : "boxes only"
        modelDescription = "\(title) · \(size) px · \(count) categories · \(output) · on device"
        if !modelAvailable { modelDescription += String(localized: " · model resource missing") }
    }

    func prepareDrone() async {
        guard !savingRecording else { return }
        guard modelAvailable else { message = modelDescription; return }
        finishCompanionTrip(reason: "Starting a new drone session")
        let request = UUID(); sessionRequest = request
        stopSource(); resetAnalysisConfirmation(); source = .drone; settings.recordingContainsLocalVideo = false; phase = .preparing
        let photoAccess = await PHPhotoLibrary.requestAuthorization(for: .addOnly)
        guard sessionRequest == request else { return }
        recordingStatus = photoAccess == .authorized || photoAccess == .limited
            ? "Ready to save screen video to Photos when the broadcast stops."
            : "Video saving is off. Allow Add Photos in iPhone Settings, then restart the broadcast."
        guard await voice.startListening(), sessionRequest == request else {
            if sessionRequest == request { phase = .unavailable; message = voice.status }; return
        }
        do {
            try startBroadcastChannel()
            settings.sessionID = UUID().uuidString; settings.revision &+= 1
            settings.analyze = false; settings.requestPreview = false
            settings.recordingRegion = lastRegion
            recordingAreaConfirmed = false
            settings.region = region; settings.pathConfiguration = nil; pathConfigured = false; settings.wearerConfiguration = nil; wearerConfigured = false
            phase = .preview; message = String(localized: "Next: share the screen, open DJI Fly, then return here.")
            if let id = activeRecordingID, let channel { voice.startRecordingAudio(id: id, channel: channel) }
            beginCompanionTrip()
            appendLog(String(localized: "Local-only DJI session prepared; awaiting user-started broadcast."))
        } catch { unavailable(error.localizedDescription) }
    }

    /// The broadcast records the screen independently of which video is analyzed.
    /// Its lifetime token must not be replaced when a local file is imported.
    private func startBroadcastChannel() throws {
        guard channel == nil else { return }
        let token = UUID(); broadcastRequest = token
        let channel = LoopbackChannel(role: .app, token: try DevicePairing.load().token)
        self.channel = channel; broadcastPrepared = true
        channel.onPacket = { [weak self] packet in Task { @MainActor in
            guard let self, self.broadcastRequest == token else { return }
            if self.source == .video {
                // A recording-only extension must never analyze or report this UI
                // as the drone camera. Local-file results use videoPipeline only.
                switch packet.type {
                case "recordingStarted", "recording", "recordingFinished", "recordingDiagnostics": self.receive(packet)
                case "ready": self.configureRecordingOnlyBroadcast()
                case "unavailable": self.recordingStatus = packet.message ?? "Screen recording paused."
                default: break
                }
            } else { self.receive(packet) }
        } }
        channel.onState = { [weak self] ready, text in Task { @MainActor in
            guard let self, self.broadcastRequest == token else { return }
            self.connected = ready
            self.recordingAreaConfirmed = false
            self.appendLog("Broadcast link \(ready ? "connected" : "disconnected"): \(text); foreground=\(self.foreground), listening=\(self.voice.listening)")
            if !ready { self.voice.stopRecordingAudio() }
            if !ready && self.savingRecording {
                self.resolveRecordingStop("Broadcast disconnected before saving was confirmed. Check Photos.")
                return
            }
            if self.source == .video {
                if !ready { self.recordingStatus = text }
                return // Recording loss must not stop local-video analysis or voice commands.
            }
            if !ready && (self.phase == .running || self.phase == .starting || self.phase == .armed) {
                self.unavailable(text, failure: .interrupted)
            } else if !ready { self.message = text }
        } }
        channel.start()
    }

    private func configureRecordingOnlyBroadcast() {
        var recordingOnly = settings
        recordingOnly.analyze = false; recordingOnly.requestPreview = false
        recordingOnly.captureEvidence = false; recordingOnly.depthEnabled = false
        recordingOnly.pathConfiguration = nil; recordingOnly.wearerConfiguration = nil
        channel?.send(LocalPacket(type: "settings", settings: recordingOnly))
    }

    func prepareVideoRecording() async {
        guard source == .video, player != nil, !savingRecording else { return }
        let request = sessionRequest
        let access = await PHPhotoLibrary.requestAuthorization(for: .addOnly)
        guard sessionRequest == request, source == .video else { return }
        guard access == .authorized || access == .limited else {
            recordingStatus = "Allow Add Photos in iPhone Settings to save this test."; return
        }
        guard await voice.startListening(), sessionRequest == request else {
            recordingStatus = voice.status; return
        }
        do {
            try startBroadcastChannel()
            configureRecordingOnlyBroadcast()
            if let id = activeRecordingID, let channel { voice.startRecordingAudio(id: id, channel: channel) }
            recordingStatus = connected ? "Recording this test with your voice and SkyCompanion responses."
                : "Ready. Tap to broadcast and choose SkyCompanion, then play the video."
        } catch { recordingStatus = error.localizedDescription }
    }

    func restoreAppliedVideoArea() {
        areaSelection.reopen()
        regionConfirmed = source == .drone && lastRegion != nil
            && settings.region == lastRegion && settings.recordingRegion == lastRegion
        appendLog("Video area editor restored: \(region.summary).")
    }

    func resetVideoAreaDraft() {
        region = CaptureRegion(); regionConfirmed = false
        appendLog("Video area draft reset by Use full image; not yet applied.")
    }

    func confirmRegion() {
        guard region.valid else { message = "Choose a valid video rectangle."; return }
        let changed = settings.region != region
        // Selection can be prepared before a DJI preview arrives. Applying it
        // changes analysis coordinates and the recording crop, never its lifetime.
        voice.cancelSpeech(); clearObservations()
        settings.region = region; settings.recordingRegion = region
        region.save(); recordingAreaConfirmed = false
        settings.analyze = false; settings.requestPreview = !foreground
        settings.revision &+= 1
        if changed {
            settings.pathConfiguration = nil; pathConfigured = false; settings.wearerConfiguration = nil; wearerConfigured = false
        }
        channel?.send(LocalPacket(type: "settings", settings: settings))
        if source == .drone && phase != .idle { phase = .paused }
        areaSelection.apply(); regionConfirmed = true
        appendLog("Video area saved and sent: \(region.summary); recordingActive=\(recordingActive).")
        message = recordingActive ? "Video area applied. Recording continues. Resume analysis when ready." : "Video area applied. Ready to start analysis."
    }

    func armDrone() {
        guard source == .drone, connected, voice.listening, regionConfirmed, lastRegion == region else {
            message = String(localized: "Start voice assistance, connect the broadcast and confirm the video area first."); return
        }
        clearObservations(); resetAnalysisConfirmation(attempted: true); settings.revision &+= 1; settings.region = region
        settings.recordingRegion = region; recordingAreaConfirmed = false
        settings.analyze = false; settings.requestPreview = true
        phase = .armed; message = String(localized: "Open DJI Fly now. Keep the phone unlocked. Waiting for the first analyzed frame.")
        channel?.send(LocalPacket(type: "settings", settings: settings))
    }

    func setForeground(_ active: Bool) {
        foreground = active; voice.foreground = active
        if broadcastPrepared { appendLog("App \(active ? "foreground" : "background"); recording connection=\(connected), listening=\(voice.listening)") }
        photon.setForeground(active)
        if active, source == .drone, phase == .running || phase == .starting {
            pause(); message = String(localized: "Paused while SkyCompanion is open. Resume, then open DJI Fly.")
        } else if !active, source == .drone, phase == .armed, voice.listening {
            settings.analyze = true; startedWaitingAt = now; phase = .starting
            channel?.send(LocalPacket(type: "settings", settings: settings))
        } else if source == .drone, phase == .preview || phase == .paused {
            settings.requestPreview = !active
            channel?.send(LocalPacket(type: "settings", settings: settings))
        } else if !active, source == .video { pause() }
    }

    private func stopStabilityTest() {
        stabilityTestStartedMS = nil; stabilityTestSeconds = nil
        UIApplication.shared.isIdleTimerDisabled = false
    }

    func startStabilityTest() {
        guard source == .video, player != nil, modelAvailable else { return }
        stabilityTestStartedMS = now; stabilityTestSeconds = 0
        UIApplication.shared.isIdleTimerDisabled = true
        recordPerformance("stability_test_started")
        playVideo()
    }

    func pause() {
        stopStabilityTest()
        recordPerformance("pause", message: "User, foreground transition, or video end")
        let snapshot = inspection
        settings.analyze = false; settings.revision &+= 1
        if source == .drone { settings.requestPreview = !foreground }
        channel?.send(LocalPacket(type: "settings", settings: settings))
        player?.pause(); voice.endVideoPlayback(); videoPipeline.configure(settings); displayLink?.invalidate(); displayLink = nil
        clearObservations(); voice.cancelSpeech(); phase = .paused
        inspection = snapshot
        message = String(localized: "Analysis paused. Resume when ready.")
    }

    func stopRecordingAndEnd() async {
        guard !savingRecording else { return }
        guard connected, let channel else {
            if broadcastPrepared {
                recordingStatus = "Broadcast link unavailable. Use the system broadcast control to stop recording and save."
                message = recordingStatus
                voice.speak(recordingStatus, control: true)
            } else { endSession() }
            return
        }
        savingRecording = true
        let request = sessionRequest
        pause()
        await voice.finishRecordingAudio()
        recordPerformance("recording_audio_relay", message: voice.recordingAudioDiagnostics)
        appendLog(voice.recordingAudioDiagnostics)
        guard sessionRequest == request else { savingRecording = false; return }
        voice.stopListening()
        phase = .paused; recordingStatus = "Saving recording to Photos…"; message = recordingStatus
        let outcome = await withCheckedContinuation { continuation in
            recordingCompletion = continuation
            channel.send(LocalPacket(type: "stop"), completion: { [weak self] sent in
                guard !sent else { return }
                Task { @MainActor in self?.resolveRecordingStop("Could not confirm the recording was saved. Check Photos.") }
            })
            recordingTimeout = Task { [weak self] in
                do { try await Task.sleep(nanoseconds: 18_000_000_000) } catch { return }
                self?.resolveRecordingStop("Video save is not confirmed. Check Photos before starting another recording.")
            }
        }
        savingRecording = false
        guard sessionRequest == request else { return }
        recordingStatus = outcome
        endSession(reason: outcome + " Assistance ended. Microphone off.")
    }

    private func resolveRecordingStop(_ text: String) {
        recordingTimeout?.cancel(); recordingTimeout = nil
        let completion = recordingCompletion; recordingCompletion = nil
        completion?.resume(returning: text)
    }

    func endSession(reason: String = String(localized: "Assistance ended. Microphone off."), stopNavigation: Bool = true) {
        if stopNavigation { cancelNavigation() }
        resolveRecordingStop(reason)
        recordPerformance("end", message: reason)
        sessionRequest = UUID(); stopSource(); voice.stopListening()
        phase = .idle; message = reason; appendLog(reason)
        finishCompanionTrip(reason: reason)
        photon.setSessionActive(false)
    }

    private func stopSource() {
        statusAnnouncements = MobileStatusAnnouncements(); lastObservedStatus = nil; statusSpeech = nil; statusFailure = .unavailable
        stopStabilityTest()
        // Analysis/source teardown never owns the broadcast lifetime. Only the
        // explicit recording-stop control sends Stop; ReplayKit can also end it.
        videoPipeline.stop(); player?.pause(); voice.endVideoPlayback(); player = nil; output = nil
        if let currentVideoURL { try? FileManager.default.removeItem(at: currentVideoURL) }
        currentVideoURL = nil; videoSHA256 = nil
        displayLink?.invalidate(); displayLink = nil; preview = nil; lastVideoTime = nil
        settings.analyze = false; settings.requestPreview = false; settings.revision &+= 1
        channel?.send(LocalPacket(type: "settings", settings: settings))
        settings.pathConfiguration = nil; pathConfigured = false; settings.wearerConfiguration = nil; wearerConfigured = false
        clearObservations()
    }

    private func resetAnalysisConfirmation(attempted: Bool = false) {
        analyzedFrameCount = 0; lastAnalysisDate = nil; analysisAttempted = attempted
    }

    private func clearObservations() {
        cancelDescriptionRequest()
        inspection = nil; wearerObservation = nil; depthResult = nil; pathObservation = nil; walkingObservation = nil; walkingSpeech = nil
        frame = nil; assessment = nil; summary = nil; latestEvidence = nil; lastEventID = nil
        frameTimes.removeAll(); fps = 0; frameAgeMS = 0; guidanceGate = MobileGuidanceGate(); cameraAlertRetry.reset()
    }

    private func unavailable(_ text: String, speak: Bool = true, failure: MobileAssistanceStatus = .unavailable) {
        statusFailure = failure
        if phase == .unavailable { message = text; return }
        guard phase != .idle else { message = text; return }
        recordPerformance("unavailable", message: text)
        stopStabilityTest()
        settings.analyze = false; settings.revision &+= 1
        channel?.send(LocalPacket(type: "settings", settings: settings))
        videoPipeline.stop(); player?.pause(); voice.endVideoPlayback(); displayLink?.invalidate(); displayLink = nil
        clearObservations(); voice.cancelSpeech(); phase = .unavailable; message = text
        appendLog(text)
        if speak { refreshStatusAnnouncement() }
    }

    private func receive(_ packet: LocalPacket) {
        if let sessionID = packet.contextSessionID, sessionID != settings.sessionID { return }
        if let revision = packet.contextRevision, revision != settings.revision { return }
        switch packet.type {
        case "recordingStarted":
            recordingActive = true
            activeRecordingID = packet.recordingID
            if source == .video { player?.isMuted = false }
            voice.checkAudioAfterBroadcastChange()
            appendLog("Recording audio relay starting; " + voice.recordingAudioDiagnostics)
            if let id = packet.recordingID, let channel { voice.startRecordingAudio(id: id, channel: channel) }
        case "recordingDiagnostics":
            if let text = packet.message { appendLog(text); recordPerformance("recording_audio", message: text) }
        case "recordingFinished":
            recordingActive = false; activeRecordingID = nil
            voice.checkAudioAfterBroadcastChange()
            voice.stopRecordingAudio()
            if let text = packet.message {
                recordingStatus = text; appendLog(text); resolveRecordingStop(text)
            }
        case "recording":
            if let text = packet.message {
                recordingStatus = text; appendLog(text)
            }
        case "ready":
            if phase == .running || phase == .starting {
                unavailable(String(localized: "Broadcast reconnected. Reconfirm the source."), failure: .interrupted); return
            }
            // A resumed extension cannot reuse previously armed observations.
            settings.analyze = false; settings.revision &+= 1; clearObservations()
            phase = .preview; settings.requestPreview = !foreground
            channel?.send(LocalPacket(type: "settings", settings: settings))
        case "recordingAreaApplied":
            guard source == .drone, packet.contextSessionID == settings.sessionID,
                  packet.contextRevision == settings.revision, packet.appliedRegion == lastRegion,
                  packet.appliedRegion == settings.recordingRegion else { return }
            recordingAreaConfirmed = true
            appendLog("Broadcast writer confirmed video area: \(packet.appliedRegion?.summary ?? "unknown").")
        case "preview":
            // Preserve the last external view while editing. Late ReplayKit
            // frames of SkyCompanion itself must not replace the DJI preview.
            guard source == .drone, !foreground else { return }
            if let data = packet.preview { preview = UIImage(data: data) }
        case "unavailable": unavailable(packet.message ?? String(localized: "Local vision is unavailable."), failure: packet.failure == "analysis" ? .unavailable : .interrupted)
        case "state":
            if let text = packet.message { message = text }
        case "depth":
            guard settings.analyze, settings.depthEnabled, let result = packet.depth,
                  result.sessionID == settings.sessionID, result.revision == settings.revision else { return }
            // Diagnostics may describe an expired sample; never route raw depth to guidance.
            depthResult = result
            do {
                let file = try evidenceDirectory().appendingPathComponent("depth-\(settings.sessionID).jsonl")
                var data = try JSONEncoder().encode(result); data.append(10)
                if !FileManager.default.fileExists(atPath: file.path) { FileManager.default.createFile(atPath: file.path, contents: nil) }
                let handle = try FileHandle(forWritingTo: file); defer { try? handle.close() }
                try handle.seekToEnd(); try handle.write(contentsOf: data)
            } catch { appendLog("Depth log error: \(error.localizedDescription)") }
        case "result":
            guard let incoming = packet.frame, incoming.sessionID == settings.sessionID,
                  incoming.revision == settings.revision, incoming.isFresh(at: now), settings.analyze,
                  source == .video || (!foreground && voice.listening) else { return }
            if saveEvidence, packet.evidenceImage != nil { latestEvidence = packet }
            if packet.preview != nil { inspection = packet }
            if source == .drone, let data = packet.sourcePreview { preview = UIImage(data: data) }
            analyzedFrameCount += 1; lastAnalysisDate = Date()
            let first = phase != .running
            wearerObservation = packet.wearer
            frame = incoming; assessment = packet.risk; summary = packet.summary.flatMap { value in
                value.sessionID == incoming.sessionID && value.revision == incoming.revision && value.frameID == incoming.frameID ? value : nil
            }
            phase = .running; lastResultAt = now; frameAgeMS = now-incoming.capturedUptimeMS
            frameTimes.append(now); frameTimes.removeAll { now-$0 > 2_000 }
            fps = frameTimes.count > 1 ? Double(frameTimes.count-1)*1_000/max(1, now-frameTimes[0]) : 0
            memoryMB = packet.memoryMB ?? memoryMB
            message = String(localized: "Analyzing on this iPhone.")
            if let assessment = packet.risk { guidanceGate.observe(assessment, nowUptimeMS: now) }
            if let path = packet.path { pathObservation = path }
            refreshStatusAnnouncement()
            let capabilities = assistanceSnapshot
            let directionsAvailable = capabilities.walkingGuidanceAvailable(at: now)
            let cameraOnly = capabilities.cameraOnlyAlerts(at: now)
            let cameraRoute = capabilities.cameraAlertsAvailable(at: now)
                && (settings.pathConfiguration?.rearFollowing != true || !directionsAvailable)
            if cameraOnly { message = voice.muted ? "Analyzing; spoken alerts are muted." : "Camera obstacle alerts only. Walking guidance paused." }
            let cameraCandidate = cameraAlertRetry.candidate(frame: incoming, assessment: packet.risk, now: now, enabled: cameraOnly)
            let candidate = cameraOnly ? cameraCandidate : packet.risk?.event
            var alerted = false
            if cameraRoute, let event = candidate, event.frameID == incoming.frameID,
               event.capturedUptimeMS == incoming.capturedUptimeMS {
                let decision: MobileGuidanceGate.Decision
                if cameraOnly, !voice.muted,
                   !MobileGuidanceGate.mayStartSpeech(incoming: event.level.rawValue, current: voice.activeSpeechPriority, protectingCommand: voice.protectingCommand) {
                    // The tracking notice must not consume the first obstacle event.
                    // Retry only with fresh evidence of the same observed object.
                    decision = .busy
                } else {
                    decision = guidanceGate.receive(event, nowUptimeMS: now,
                    sessionID: settings.sessionID, revision: settings.revision,
                    enabled: (vibrationEnabled || !voice.muted) && (!quieter || event.level >= .action)
                        && photon.preferences.allows(level: event.level, label: event.evidence.detectedLabel),
                    currentSpeechPriority: voice.activeSpeechPriority, protectingCommand: voice.protectingCommand,
                    ordinaryIntervalSeconds: photon.preferences.repeatIntervalSeconds, hapticsEnabled: vibrationEnabled)
                    cameraAlertRetry.reset()
                }
                // Read-only diagnostics: retain the restored admission behavior.
                if now-lastAlertDiagnosticAt >= 1_000 {
                    lastAlertDiagnosticAt = now
                    let seconds = player?.currentTime().seconds ?? -1
                    let detail = "source=\(source.rawValue); cameraOnly=\(cameraOnly); " + String(format: "video=%.2fs", seconds)
                        + "; frame=\(incoming.frameID); target=\(event.evidence.detectedLabel ?? "uncertain")"
                        + "; eventSide=\(event.direction.rawValue); displayedSide=\(packet.risk?.direction?.rawValue ?? "none")"
                        + "; gate=\(decision); commandProtected=\(voice.protectingCommand)"
                        + "; speechPriority=\(voice.activeSpeechPriority.map(String.init) ?? "none"); muted=\(voice.muted)"
                    recordPerformance("alert_decision", message: detail)
                }
                if case .play(let deadline) = decision {
                    if vibrationEnabled {
                        emitVibration(reason: "fresh R\(event.level.rawValue) obstacle")
                    }
                    navigationQuietUntil = now + 4_000
                    let speech = cameraOnly ? MobileAlertSpeech.cameraObstacle(direction: event.direction)
                        : photon.preferences.speech(direction: event.direction, consequence: event.evidence.hazardConsequence, level: event.level)
                    let observedAt = Int64((Date().timeIntervalSince1970 * 1_000 - max(0, now - incoming.capturedUptimeMS)).rounded())
                    let snapshot = alertSnapshot(frame: incoming, assessment: packet.risk)
                    alerted = voice.speak(speech, priority: event.level.rawValue, expires: deadline,
                        onStarted: { [weak self] in self?.recordSpokenAlert(event, text: speech, observedAtMS: observedAt, snapshot: snapshot) })
                    recordPerformance("alert_delivery", frame: incoming, message: "accepted=\(alerted); muted=\(voice.muted); cameraOnly=\(cameraOnly); speech=\(speech)")
                    if alerted { lastEventID = event.id }
                    if alerted { appendLog(String.localizedStringWithFormat(String(localized: "Risk R%lld: %@"), event.level.rawValue, event.text)) }
                }
            }
            if let path = packet.path {
                pathObservation = path
                if directionsAvailable, settings.pathConfiguration?.rearFollowing != true, let text = path.eventText, !alerted, (vibrationEnabled || !voice.muted) {
                    if vibrationEnabled { emitVibration(reason: "path or walking event") }
                    // Route observations do not interrupt a command response or an obstacle warning.
                    alerted = voice.speak(String(localized: String.LocalizationValue(text)), priority: 0, expires: path.capturedUptimeMS+1_500)
                    appendLog("Path state: \(path.state.rawValue); \(path.reason)")
                }
            }
            if let walking = packet.walking, walking.sessionID == incoming.sessionID,
               walking.revision == incoming.revision, walking.frameID == incoming.frameID {
                walkingObservation = walking
                let walkingText = photon.preferences.speech(walking: walking)
                let signature = walking.confirmed ? walkingText : ""
                if let speaking = walkingSpeech, speaking != signature,
                   voice.activeSpeechText == speaking {
                    voice.cancelSpeech(); walkingSpeech = nil
                }
                if walking.event, directionsAvailable, (vibrationEnabled || !voice.muted),
                   photon.preferences.allowsWalking(walking), (!quieter || walking.severity >= .action),
                   walking.severity >= .action || now - lastOrdinaryWalkingAt >= Double(photon.preferences.repeatIntervalSeconds) * 1_000 {
                    navigationQuietUntil = now + 4_000
                    if vibrationEnabled { emitVibration(reason: "path or walking event") }
                    let priority = walking.severity.rawValue
                    if walking.severity == .attention { lastOrdinaryWalkingAt = now }
                    let eventID = UUID().uuidString
                    var snapshot = alertSnapshot(frame: incoming, assessment: packet.risk)
                    snapshot.walking = walking
                    let observedAt = Int64((Date().timeIntervalSince1970 * 1_000 - max(0, now - incoming.capturedUptimeMS)).rounded())
                    alerted = voice.speak(walkingText, priority: priority, expires: walking.capturedUptimeMS+1_500,
                        onStarted: { [weak self] in
                            guard let self, walking.obstacleRelated, self.companionTrip?.id == walking.sessionID,
                                  self.companionTrip?.ended == false else { return }
                            self.companionTrip?.record(eventID: eventID, category: "obstacle")
                            self.lastSpokenAlert = (eventID, walking.sessionID, walking.frameID, walkingText, snapshot)
                            self.lastReportedAlert = walkingText
                            self.photon.recordObstacleSpeech(eventID: eventID, sessionID: walking.sessionID, frameID: walking.frameID,
                                spokenText: walkingText, category: "obstacle", direction: walking.caution == .ahead ? "center" : walking.caution?.rawValue ?? "unknown",
                                evidence: ["recorded_rear_following_obstacle_reminder", walking.reason], observedAtMS: observedAt)
                        })
                    if alerted { walkingSpeech = walkingText }
                    appendLog("Rear-following guidance: \(walking.speech) \(walking.reason)")
                }
            }
            if first { appendLog("Analysis confirmed: first fresh on-device result received.") }
            if first && !alerted && !assistanceStatus.isFault { voice.speak(String(localized: "Camera view received. Local analysis is active."), priority: 0) }
            if now-lastDiagnosticAt >= 1_000 {
                lastDiagnosticAt = now
                appendLog(String(format: "fps=%.1f inference=%.0fms age=%.0fms resident=%.1fMB", fps, incoming.inferenceMS, frameAgeMS, memoryMB))
                recordPerformance("sample", frame: incoming, timings: packet.inferenceTimings)
                if let timings = packet.inferenceTimings {
                    appendLog(String(format: "stages preprocess=%.1fms model=%.1fms decode=%.1fms thermal=%ld",
                        timings.preprocessMS, timings.modelMS, timings.decodeMS, ProcessInfo.processInfo.thermalState.rawValue))
                }
            }
        default: break
        }
    }


    func confirmWearer(snapshot: LocalPacket, personIndex: Int) {
        guard let frame = snapshot.frame, frame.sessionID == settings.sessionID,
              let jpeg = snapshot.preview, jpeg.count < 400_000,
              frame.detections.indices.contains(personIndex), frame.detections[personIndex].label == "person",
              frame.detections[personIndex].isValid else {
            message = String(localized: "Select the followed user in this session's analyzed view."); return
        }
        pause()
        settings.wearerConfiguration = LocalWearerConfiguration(referenceJPEG: jpeg, person: frame.detections[personIndex])
        wearerConfigured = true
        settings.pathConfiguration = nil; pathConfigured = false
        message = String(localized: "Followed user selected. Resume analysis. Only this tracked person is excluded from obstacle descriptions and alerts.")
    }

    func confirmPath(snapshot: LocalPacket, personIndex: Int, boundary: [MobilePoint], kind: String, rearFollowing: Bool = false) {
        guard let frame = snapshot.frame, frame.sessionID == settings.sessionID,
              let jpeg = snapshot.preview, jpeg.count < 400_000,
              frame.detections.indices.contains(personIndex), frame.detections[personIndex].label == "person",
              MobilePathMonitor.validBoundary(boundary) else {
            message = String(localized: "Select a person and a valid four-corner path in this session's analyzed snapshot."); return
        }
        pause()
        settings.pathConfiguration = LocalPathConfiguration(referenceJPEG: jpeg, person: frame.detections[personIndex], boundary: boundary, kind: kind, rearFollowing: rearFollowing)
        settings.wearerConfiguration = LocalWearerConfiguration(referenceJPEG: jpeg, person: frame.detections[personIndex])
        wearerConfigured = true; pathConfigured = true
        message = String(localized: "Experimental path monitoring configured. Resume analysis. If the person moved too far or tracking fails, select again.")
    }
    func disablePath() {
        pause(); settings.pathConfiguration = nil; pathConfigured = false; pathObservation = nil
        message = String(localized: "Path monitoring off. Resume analysis when ready.")
    }

    private func emitVibration(reason: String) {
        // Starting a broadcast or changing audio routes can reset audio-session
        // policy. Reapply it at delivery, not only when listening first starts.
        do {
            try AVAudioSession.sharedInstance().setAllowHapticsAndSystemSoundsDuringRecording(true)
        } catch { appendLog("Recording haptics policy failed: \(error.localizedDescription)") }
        AudioServicesPlayAlertSound(kSystemSoundID_Vibrate)
        appendLog("Vibration requested: \(reason); recordingAllowed=\(AVAudioSession.sharedInstance().allowHapticsAndSystemSoundsDuringRecording). Physical delivery not measured.")
    }

    func testVibration() {
        guard foreground else { return }
        emitVibration(reason: "manual test")
        message = String(localized: "Vibration test requested. Confirm that you felt it on this iPhone.")
        appendLog("Manual vibration test requested; physical delivery not measured.")
    }

    private var assistanceSnapshot: MobileAssistanceSnapshot {
        var snapshot = MobileAssistanceSnapshot()
        switch phase {
        case .idle: snapshot.phase = .idle
        case .paused: snapshot.phase = .paused
        case .unavailable: snapshot.phase = .unavailable
        case .running: snapshot.phase = .running
        default: snapshot.phase = .waiting
        }
        snapshot.failure = statusFailure
        snapshot.sessionID = settings.sessionID; snapshot.revision = settings.revision; snapshot.frame = frame
        snapshot.analyzing = settings.analyze; snapshot.sourceConnected = source == .video || connected
        snapshot.requiresVoiceSession = source == .drone; snapshot.listening = voice.listening
        snapshot.muted = voice.muted; snapshot.riskAvailable = assessment?.health == .available
        // Identity gates walking instructions. Camera-only risk independently
        // removes all person candidates while identity cannot be confirmed.
        snapshot.wearerRequired = source == .drone || wearerConfigured; snapshot.wearer = wearerObservation
        snapshot.pathRequired = settings.pathConfiguration?.rearFollowing == true; snapshot.path = pathObservation
        return snapshot
    }
    private var assistanceStatus: MobileAssistanceStatus { assistanceSnapshot.status(at: now) }

    private func speakAssistanceStatus() {
        let state = assistanceStatus
        let text = assistanceSnapshot.speech(at: now)
        appendLog("Assistance status: \(state.rawValue); \(text)")
        // Explicit queries and service-failure notices bypass obstacle mute, not the audio-session guard.
        if voice.speak(text, priority: 3, control: true) { statusSpeech = (state, text) }
    }

    private func statusSpeechDidStart(_ text: String) {
        guard let spoken = statusSpeech, spoken.text == text else { return }
        guard spoken.state == assistanceStatus, spoken.text == assistanceSnapshot.speech(at: now) else { voice.cancelSpeech(); statusSpeech = nil; return }
        if spoken.state.isFault { statusAnnouncements.didStart(spoken.state) }
    }

    private func refreshStatusAnnouncement() {
        let state = assistanceStatus
        let transitioned = lastObservedStatus != state
        lastObservedStatus = state
        if let spoken = statusSpeech {
            if voice.activeSpeechText != spoken.text { statusSpeech = nil }
            else if spoken.state != state || spoken.text != assistanceSnapshot.speech(at: now) { voice.cancelSpeech(); statusSpeech = nil }
        }
        if transitioned && (state == .trackingLost || state == .pathUnavailable) {
            // Never finish a movement instruction after losing the user/path.
            if voice.activeSpeechText != statusSpeech?.text { voice.cancelSpeech(); walkingSpeech = nil }
        }
        guard statusAnnouncements.observe(state, now: now) != nil, state != .audioUnavailable,
              statusSpeech?.state != state, foreground || voice.listening else { return }
        speakAssistanceStatus()
    }

    func startNavigation(to destination: String) {
        navigation.start(destination: destination)
        voice.backgroundNavigationActive = navigation.isActive
    }

    func cancelNavigation() {
        navigation.stop(); voice.backgroundNavigationActive = false
        if let lastNavigationSpeech, voice.activeSpeechText == lastNavigationSpeech { voice.cancelSpeech() }
        lastNavigationSpeech = nil
    }

    private func handleNavigation(_ command: NavigationVoiceCommand) {
        switch command {
        case .destination(let name): startNavigation(to: name)
        case .cancel: cancelNavigation(); voice.speak("Navigation stopped.", priority: -1)
        case .select(let number): navigation.selectCandidate(number: number)
        case .status: voice.speak(navigation.status, priority: -1)
        }
    }

    func handle(_ command: MobileVoiceCommand) {
        cancelDescriptionRequest()
        appendLog("Command handled: \(command.rawValue); source=\(source.rawValue), foreground=\(foreground), phase=\(phase.rawValue).")
        switch command {
        case .agentSummary: askCompanion("Trip summary?")
        case .agentWhy: askCompanion("Why did you warn me?")
        case .stop, .end:
            endSession(reason: recordingActive ? "Assistance ended. Recording continues until you tap Stop recording and save." : "Assistance ended. Microphone off.")
        case .pause:
            pause(); voice.speak(String(localized: "Analysis paused. Command listening remains on."), control: true)
        case .resume:
            if source == .video { playVideo() }
            else {
                armDrone()
                if phase == .armed && !foreground {
                    settings.analyze = true; startedWaitingAt = now; phase = .starting
                    channel?.send(LocalPacket(type: "settings", settings: settings))
                }
            }
        case .status: speakAssistanceStatus()
        case .mute: voice.setMuted(true, announce: false); speakAssistanceStatus()
        case .unmute: voice.setMuted(false, announce: false); speakAssistanceStatus()
        case .quiet: quieter = true; voice.speak(String(localized: "Quieter alerts enabled."), control: true)
        case .normal: quieter = false; voice.speak(String(localized: "Normal alerts enabled."), control: true)
        case .acknowledge: voice.speak(String(localized: "Alert acknowledged. This does not mean the obstacle is resolved."), control: true)
        case .reportFalseAlert: reportFalseAlert()
        case .path:
            if assistanceStatus.isFault { speakAssistanceStatus(); return }
            guard let path = pathObservation, phase == .running, now-path.capturedUptimeMS < 1_500,
                  path.capturedUptimeMS <= now else {
                voice.speak(String(localized: "Current path position is unavailable. Confirm the person and path in SkyCompanion."), control: true); return
            }
            let text: String
            switch path.state {
            case .inside: text = String(localized: "Selected person appears inside the confirmed region. This does not establish a clear route.")
            case .nearBoundary: text = String(localized: "Selected person is near the confirmed path boundary.")
            case .outside: text = String(localized: "Selected person appears outside the confirmed path. Check position.")
            case .confirming: text = String(localized: "Path position is still being confirmed.")
            case .unknown: text = String(localized: "Path position unavailable. Check the selected person and path.")
            }
            voice.speak(text, expires: path.capturedUptimeMS+1_500, control: true)
        case .describe:
            pendingDescribe = DescribeRequest(id: describeGeneration, sessionID: settings.sessionID,
                revision: settings.revision, deadline: now + 8_000)
            voice.commandPending = true
            pumpDescription()
        case .repeatAlert, .explain:
            let cameraOnly = assistanceSnapshot.cameraOnlyAlerts(at: now)
            if assistanceStatus.isFault && !cameraOnly { speakAssistanceStatus(); return }
            if settings.pathConfiguration?.rearFollowing == true && !cameraOnly {
                guard let walking = walkingObservation, phase == .running,
                      walking.confirmed, now >= walking.capturedUptimeMS, now-walking.capturedUptimeMS < 1_500,
                      walking.action != nil else {
                    voice.speak(String(localized: "No current walking instruction."), control: true); return
                }
                let played = voice.speak(command == .explain ? walking.reason : walking.speech,
                    expires: walking.capturedUptimeMS+1_500, control: true)
                if played && command == .repeatAlert { walkingSpeech = walking.speech }
                return
            }
            guard let frame, frame.isFresh(at: now), let assessment, assessment.state == .occupied else {
                voice.speak(String(localized: "No current confirmed alert to repeat."), control: true); return
            }
            let text: String
            if command == .explain && assessment.lifecycle != .occludedUnresolved {
                text = String(localized: "The object overlaps the selected camera area across several observations. Its distance and direction relative to you are unknown.")
            } else if command == .repeatAlert, assessment.lifecycle != .occludedUnresolved, let direction = assessment.direction {
                text = cameraOnly ? MobileAlertSpeech.cameraObstacle(direction: direction) : MobileAlertSpeech.obstacle(direction: direction)
            } else {
                text = assessment.text
            }
            voice.speak(text, priority: assessment.level.rawValue, expires: frame.capturedUptimeMS+1_500, control: true)
        }
    }

    private func cancelDescriptionRequest() {
        describeGeneration = UUID(); pendingDescribe = nil; voice.commandPending = false
    }

    private func pumpDescription() {
        guard let request = pendingDescribe else { return }
        guard request.id == describeGeneration, request.sessionID == settings.sessionID,
              request.revision == settings.revision else { cancelDescriptionRequest(); return }
        let time = now
        guard MobileGuidanceGate.mayStartSpeech(incoming: 0, current: voice.activeSpeechPriority, explicitRequest: true) else {
            if time >= request.deadline {
                appendLog("Describe could not start while a higher-priority announcement was active.")
                cancelDescriptionRequest()
            }
            return
        }
        // Re-read observations after the current warning finishes, never queue old scene text.
        let reply = time >= request.deadline ? MobileSceneReply.unavailable(now: time)
            : MobileSceneReply.current(frame: frame, summary: summary, running: phase == .running, now: time)
        guard let reply else { return }
        let expiry: (() -> Void)? = reply.isObservation ? { [weak self] in
            guard let self, self.describeGeneration == request.id,
                  self.settings.sessionID == request.sessionID, self.settings.revision == request.revision else { return }
            self.pendingDescribe = request; self.voice.commandPending = true
            self.appendLog("Describe observation expired before speech; retrying with the latest view.")
            self.pumpDescription()
        } : nil
        if voice.speak(reply.text, expires: reply.expiresMS, control: true,
                       onStarted: { [weak self] in self?.appendLog("Describe response started; observation=\(reply.isObservation).") },
                       onExpired: expiry) {
            pendingDescribe = nil; voice.commandPending = false
        }
    }

    func importVideo(_ originalURL: URL) async {
        guard !savingRecording else { return }
        let keepBroadcast = broadcastPrepared
        if keepBroadcast {
            cancelNavigation()
            finishCompanionTrip(reason: "Switching to a local video test")
            voice.cancelSpeech()
            stopSource()
        } else { endSession() }
        resetAnalysisConfirmation(); source = .video; settings.recordingContainsLocalVideo = true; settings.recordingRegion = nil; phase = .preparing
        let request = UUID(); sessionRequest = request
        if keepBroadcast {
            configureRecordingOnlyBroadcast()
            appendLog("Local video selected; screen recording and voice assistance retained.")
        }
        let access = originalURL.startAccessingSecurityScopedResource()
        defer { if access { originalURL.stopAccessingSecurityScopedResource() } }
        do {
            let target = FileManager.default.temporaryDirectory.appendingPathComponent("skycompanion-test-\(request.uuidString).\(originalURL.pathExtension)")
            if FileManager.default.fileExists(atPath: target.path) { try FileManager.default.removeItem(at: target) }
            try FileManager.default.copyItem(at: originalURL, to: target)
            defer { if currentVideoURL != target { try? FileManager.default.removeItem(at: target) } }
            let asset = AVURLAsset(url: target)
            guard let track = try await asset.loadTracks(withMediaType: .video).first else { throw LocalFailure.message(String(localized: "The selected file has no video track.")) }
            guard sessionRequest == request, source == .video else { return }
            let transform = try await track.load(.preferredTransform)
            guard sessionRequest == request, source == .video else { return }
            videoOrientation = transform.b > 0.5 ? .right : transform.b < -0.5 ? .left : transform.a < -0.5 ? .down : .up
            let output = AVPlayerItemVideoOutput(pixelBufferAttributes: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
            let item = AVPlayerItem(asset: asset); item.add(output)
            self.output = output; player = AVPlayer(playerItem: item); player?.isMuted = false
            currentVideoURL = target
            let fileHandle = try FileHandle(forReadingFrom: target)
            var hasher = SHA256()
            while let chunk = try fileHandle.read(upToCount: 1_048_576), !chunk.isEmpty { hasher.update(data:chunk) }
            try fileHandle.close(); videoSHA256 = hasher.finalize().map { String(format:"%02x", $0) }.joined()
            settings.sessionID = UUID().uuidString; settings.revision &+= 1
            settings.region = CaptureRegion()
            settings.requestPreview = true; settings.analyze = false
            phase = .paused; message = String(localized: "Local video ready. Recording includes the original soundtrack and your conversation.")
        } catch { guard sessionRequest == request else { return }; phase = .unavailable; message = error.localizedDescription; appendLog(message) }
    }

    func playVideo() {
        guard source == .video, let player, modelAvailable else { return }
        if companionTrip?.ended == true { settings.sessionID = UUID().uuidString }
        beginCompanionTrip()
        do { try voice.beginVideoPlayback() }
        catch { unavailable(error.localizedDescription); return }
        clearObservations(); resetAnalysisConfirmation(attempted: true); settings.revision &+= 1; settings.analyze = true
        videoPipeline.configure(settings); phase = .starting; startedWaitingAt = now; lastVideoTime = nil
        if player.currentItem?.status == .failed { unavailable(String(localized: "The selected video cannot be played.")); return }
        if let duration = player.currentItem?.duration.seconds, duration.isFinite, player.currentTime().seconds >= duration-0.1 {
            settings.pathConfiguration = nil; pathConfigured = false; settings.wearerConfiguration = nil; wearerConfigured = false; videoPipeline.configure(settings); player.seek(to: .zero)
        }
        displayLink?.invalidate()
        let link = CADisplayLink(target: self, selector: #selector(readVideoFrame))
        link.add(to: .main, forMode: .common); displayLink = link
        player.play(); message = String(localized: "Starting on-device test…")
    }

    @objc private func readVideoFrame() {
        guard let output, let player, settings.analyze else { return }
        let time = player.currentTime()
        if let last = lastVideoTime, time.seconds < last || time.seconds-last > 0.6 {
            settings.pathConfiguration = nil; pathConfigured = false; settings.wearerConfiguration = nil; wearerConfigured = false
            clearObservations(); settings.revision &+= 1; videoPipeline.configure(settings)
        }
        lastVideoTime = time.seconds
        guard output.hasNewPixelBuffer(forItemTime: time), let pixels = output.copyPixelBuffer(forItemTime: time, itemTimeForDisplay: nil) else { return }
        videoPipeline.submit(pixels, orientation: videoOrientation, capturedMS: now)
    }

    private func beginCompanionTrip() {
        guard companionTrip?.id != settings.sessionID || companionTrip?.ended != false else { return }
        companionSpeech.clear()
        companionTrip = CompanionTrip(id: settings.sessionID, recordedVideo: source == .video, chinese: voice.chineseCommands)
        lastSpokenAlert = nil; lastReportedAlert = ""; tripSummary = ""
        photon.startTrip(sessionID: settings.sessionID, source: source == .video ? "video" : "drone", chinese: voice.chineseCommands)
    }

    private func finishCompanionTrip(reason: String) {
        guard var trip = companionTrip, let text = trip.finish() else { return }
        companionTrip = trip; tripSummary = text
        photon.endTrip(sessionID: trip.id, reason: reason)
        companionSpeech.clear()
        queueCompanionSpeech(id: "local-summary-" + trip.id, text: text)
        // Keep the latest summary available offline, even after the app restarts.
        if let folder = try? evidenceDirectory() {
            try? Data(text.utf8).write(to: folder.appendingPathComponent("last-trip-summary.txt"), options: .atomic)
        }
    }

    private func alertSnapshot(frame: MobileFrameResult, assessment: MobileRiskAssessment?) -> LocalPacket {
        if saveEvidence, let packet = latestEvidence, packet.frame?.sessionID == frame.sessionID,
           packet.frame?.revision == frame.revision, packet.frame?.frameID == frame.frameID {
            return packet
        }
        return LocalPacket(type: "reported_case", frame: frame, risk: assessment)
    }

    private func recordSpokenAlert(_ event: MobileRiskEvent, text: String, observedAtMS: Int64, snapshot: LocalPacket) {
        if source == .video {
            let detail = String(format: "video=%.2fs", player?.currentTime().seconds ?? -1)
                + "; frame=\(event.frameID); side=\(event.direction.rawValue)"
                + "; target=\(event.evidence.detectedLabel ?? "uncertain"); text=\(text)"
            recordPerformance("alert_audio_started", message: detail)
        }
        guard companionTrip?.id == event.sessionID, companionTrip?.ended == false else { return }
        let category = event.evidence.categoryNamingEnabled ? event.evidence.kind : "obstacle"
        companionTrip?.record(eventID: event.id, category: category)
        lastSpokenAlert = (event.id, event.sessionID, event.frameID, text, snapshot)
        lastReportedAlert = text
        photon.recordAlert(event: event, spokenText: text, category: category, observedAtMS: observedAtMS)
    }

    func askCompanion(_ question: String) {
        guard let trip = companionTrip, !question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            message = "Start a trip or a video test before asking about its reminders."; return
        }
        photon.ask(question: question, sessionID: trip.id)
    }

    func readCompanionMessage(id: String, text: String) {
        // Explicit reads are also interruptible, never protected as voice commands.
        companionSpeech.enqueue(id: "read-" + id + "-" + UUID().uuidString, text: companionSpeechText(text), nowMS: now)
    }

    private func queueCompanionSpeech(id: String, text: String) {
        guard readCompanionMessages else { return }
        companionSpeech.enqueue(id: id, text: companionSpeechText(text), nowMS: now)
    }

    private func companionSpeechText(_ text: String) -> String {
        guard text.count > 1_800 else { return text }
        return String(text.prefix(1_800)) + ". Read the full message in the app."
    }

    private func pumpCompanionSpeech() {
        let hazard = phase == .running && frame?.isFresh(at: now) == true && assessment?.state == .occupied
        guard let item = companionSpeech.next(nowMS: now, speechBusy: voice.activeSpeechPriority != nil,
            protectingCommand: voice.protectingCommand, obstacleActive: hazard,
            canSpeak: (foreground || voice.listening) && !voice.muted) else { return }
        // Assistant replies sit below navigation (-1), commands, health and obstacle speech.
        // New obstacle speech cancels this utterance immediately through the same synthesizer.
        voice.speak(item.text, priority: -2, expires: now + 3_000)
    }

    func reportFalseAlert(note: String = "User reported an incorrect alert") {
        if let recorded = lastSpokenAlert {
            do {
                let folder = try evidenceDirectory()
                let name = "case-" + UUID().uuidString
                var snapshot = recorded.snapshot
                let image = saveEvidence ? snapshot.evidenceImage : nil
                snapshot.evidenceImage = nil; snapshot.preview = nil; snapshot.type = "reported_case"
                try JSONEncoder().encode(snapshot).write(to: folder.appendingPathComponent(name + ".json"), options: .atomic)
                if let image { try image.write(to: folder.appendingPathComponent(name + "-input.jpg"), options: .atomic) }
                let feedback: [String: Any] = ["event_id": recorded.eventID, "session_id": recorded.sessionID,
                    "frame_id": recorded.frameID, "spoken_text": recorded.text,
                    "note": String(note.prefix(1_000)), "review_status": "unreviewed", "evidence_file": name + ".json",
                    "source": source == .video ? "recorded_test" : "drone", "model": modelDescription]
                try JSONSerialization.data(withJSONObject: feedback, options: [.sortedKeys])
                    .write(to: folder.appendingPathComponent(name + "-feedback.json"), options: .atomic)
                photon.reportFalseAlert(eventID: recorded.eventID, sessionID: recorded.sessionID, note: note)
                message = "Incorrect-alert feedback saved for review. The model has not changed."
                queueCompanionSpeech(id: name, text: "Feedback saved for review.")
            } catch { message = "Could not save feedback: " + error.localizedDescription }
            return
        }
        guard let frame, frame.isFresh(at: now), let assessment else {
            queueCompanionSpeech(id: UUID().uuidString, text: String(localized: "There is no fresh evidence to report.")); return
        }
        do {
            let folder = try evidenceDirectory()
            let name = "case-\(UUID().uuidString)"
            let evidence = latestEvidence.flatMap { packet -> LocalPacket? in
                guard saveEvidence, let candidate = packet.frame, candidate.sessionID == frame.sessionID,
                      candidate.revision == frame.revision, candidate.isFresh(at: now) else { return nil }; return packet
            }
            var report = evidence ?? LocalPacket(type: "reported_case", frame: frame, risk: assessment, summary: summary)
            let image = report.evidenceImage; report.evidenceImage = nil; report.type = "reported_case"
            let data = try JSONEncoder().encode(report)
            try data.write(to: folder.appendingPathComponent(name+".json"), options: .atomic)
            // An optional snapshot and its JSON always come from the same processed frame.
            if let image { try image.write(to: folder.appendingPathComponent(name+"-input.jpg"), options: .atomic) }
            appendLog(String(localized: "User-reported case saved. No automatic model change."))
            queueCompanionSpeech(id: name, text: String(localized: "Report saved on this phone for review."))
        } catch { message = String.localizedStringWithFormat(String(localized: "Could not save the report: %@"), error.localizedDescription) }
    }

    func deleteLocalData() {
        do {
            let folder = try evidenceDirectory()
            for file in try FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil) { try FileManager.default.removeItem(at: file) }
            log.removeAll(); message = String(localized: "Local diagnostics and saved cases deleted.")
            lastSpokenAlert = nil; lastReportedAlert = ""; tripSummary = ""
        } catch { message = error.localizedDescription }
    }

    private func evidenceDirectory() throws -> URL {
        let folder = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("SkyCompanionDiagnostics")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        return folder
    }
    /// Append-only numeric evidence survives the short on-screen log's 300-entry cap.
    private func recordPerformance(_ type: String, frame: MobileFrameResult? = nil,
                                   timings: MobileInferenceTimings? = nil, message: String? = nil) {
        do {
            let file = try evidenceDirectory().appendingPathComponent("performance-\(settings.sessionID).jsonl")
            var row: [String: Any] = ["event": type, "date": Date().ISO8601Format(),
                "uptimeMS": now, "sessionID": settings.sessionID, "revision": settings.revision,
                "source": source.rawValue, "fps": fps, "visionResidentMB": memoryMB,
                "thermalState": ProcessInfo.processInfo.thermalState.rawValue,
                "batteryLevel": UIDevice.current.batteryLevel, "batteryState": UIDevice.current.batteryState.rawValue,
                "depthEnabled": settings.depthEnabled, "pathEnabled": pathConfigured,
                "listening": voice.listening, "voice": voice.voiceDescription, "model": modelDescription]
            let snapshot = assistanceSnapshot
            row["assistanceStatus"] = snapshot.status(at: now).rawValue
            row["cameraAlertsAvailable"] = snapshot.cameraAlertsAvailable(at: now)
            row["walkingGuidanceAvailable"] = snapshot.walkingGuidanceAvailable(at: now)
            row["wearerConfigured"] = wearerConfigured
            row["wearerState"] = wearerObservation?.state.rawValue ?? "none"
            row["wearerReason"] = wearerObservation?.reason ?? "No current wearer observation"
            row["riskState"] = assessment?.state.rawValue ?? "none"
            row["riskHealth"] = assessment?.health.rawValue ?? "none"
            row["riskLifecycle"] = assessment?.lifecycle.rawValue ?? "none"
            row["riskLabel"] = assessment?.evidence?.detectedLabel ?? "none"
            row["muted"] = voice.muted; row["quieter"] = quieter
            row["commandProtected"] = voice.protectingCommand
            row["activeSpeechPriority"] = voice.activeSpeechPriority ?? -99
            if let depthResult { row["depthInferenceMS"] = depthResult.inferenceMS; row["depthStatus"] = depthResult.status }
            if let walkingObservation { row["walkingAction"] = walkingObservation.action?.rawValue ?? "none"; row["walkingReason"] = walkingObservation.reason }
            if let pathObservation { row["pathProcessingMS"] = pathObservation.processingMS; row["pathState"] = pathObservation.state.rawValue }
            if let frame {
                row["frameID"] = frame.frameID; row["capturedMS"] = frame.capturedUptimeMS
                row["inferenceMS"] = frame.inferenceMS; row["ageMS"] = now-frame.capturedUptimeMS
            }
            if let timings {
                row["preprocessMS"] = timings.preprocessMS; row["modelMS"] = timings.modelMS; row["decodeMS"] = timings.decodeMS
            }
            if let videoSHA256 { row["videoSHA256"] = videoSHA256 }
            if let player {
                row["playerRate"] = player.rate; row["playerState"] = player.timeControlStatus.rawValue
                let time = player.currentTime().seconds
                if time.isFinite { row["videoTimeSeconds"] = time }
            }
            if let message { row["message"] = message }
            var data = try JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]); data.append(10)
            if !FileManager.default.fileExists(atPath: file.path) { FileManager.default.createFile(atPath: file.path, contents: nil) }
            let handle = try FileHandle(forWritingTo: file); defer { try? handle.close() }
            try handle.seekToEnd(); try handle.write(contentsOf: data)
        } catch { appendLog("Performance log write failed: \(error.localizedDescription)") }
    }

    private func appendLog(_ text: String) {
        log.append(String.localizedStringWithFormat(String(localized: "%@ · %@"), Date().formatted(date: .omitted, time: .standard), text))
        if log.count > 300 { log.removeFirst(log.count-300) }
        if let folder = try? evidenceDirectory(), let data = try? JSONEncoder().encode(log) {
            try? data.write(to: folder.appendingPathComponent("latest-session.json"), options: .atomic)
        }
    }
}
