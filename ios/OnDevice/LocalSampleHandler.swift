import ReplayKit
import ImageIO
import CoreMedia

final class LocalSampleHandler: RPBroadcastSampleHandler {
    private let pipeline = LocalVisionPipeline()
    private let recording = BroadcastRecording()
    private var channel: RecoveringBroadcastChannel?
    private let finishLock = NSLock()
    private var finishing = false

    override func broadcastStarted(withSetupInfo setupInfo: [String : NSObject]?) {
        do {
            let channel = RecoveringBroadcastChannel(token: try DevicePairing.load().token)
            self.channel = channel
            recording.onStatus = { [weak channel] text in channel?.send(LocalPacket(type: "recording", message: text)) }
            recording.onStarted = { [weak channel] id in channel?.send(LocalPacket(type: "recordingStarted", recordingID: id)) }
            recording.onDiagnostics = { [weak channel] text in channel?.send(LocalPacket(type: "recordingDiagnostics", message: text)) }
            pipeline.onPacket = { [weak channel] packet in channel?.send(packet) }
            channel.onPacket = { [weak self, weak channel] packet in
                if packet.type == "settings", let settings = packet.settings {
                    self?.recording.configureAudio(localVideo: settings.recordingContainsLocalVideo, region: settings.recordingRegion) { [weak channel] in
                        channel?.send(LocalPacket(type: "recordingAreaApplied", contextSessionID: settings.sessionID,
                            contextRevision: settings.revision, appliedRegion: settings.recordingRegion ?? CaptureRegion()))
                    }
                    self?.pipeline.configure(settings)
                }
                if packet.type == "recordingAudio", let audio = packet.recordingAudio { self?.recording.submitLocalAudio(audio) }
                if packet.type == "stop" { self?.end(String(localized: "SkyCompanion ended the assistance session.")) }
            }
            channel.onState = { [weak self, weak channel] connected, message in
                guard let self else { return }
                self.finishLock.lock(); let ending = self.finishing; self.finishLock.unlock()
                guard !ending else { return }
                // Clear analysis on link loss and reconnection. Only fresh settings
                // may re-enable it; never replay old observations after app suspension.
                self.pipeline.stop()
                if connected {
                    channel?.send(LocalPacket(type: "ready"))
                    self.recording.publishCurrentState()
                    channel?.send(LocalPacket(type: "recordingDiagnostics", message: "Broadcast IPC connected; existing recording retained."))
                }
                // A lost app connection is not a user Stop. The recording keeps
                // receiving ReplayKit frames while authenticated IPC reconnects.
            }
            recording.start()
            channel.start()
        } catch { end(error.localizedDescription) }
    }
    override func broadcastPaused() {
        recording.pause()
        pipeline.stop(); channel?.send(LocalPacket(type: "unavailable", message: String(localized: "Screen broadcast paused. Return to SkyCompanion before resuming analysis.")))
    }
    override func broadcastResumed() { recording.resume(); channel?.send(LocalPacket(type: "ready")) }
    override func broadcastFinished() {
        finishLock.lock(); finishing = true; finishLock.unlock()
        pipeline.stop()
        let message = recording.finish()
        sendRecordingOutcome(message)
        channel?.stop(); channel = nil
    }
    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer, with sampleBufferType: RPSampleBufferType) {
        guard CMSampleBufferDataIsReady(sampleBuffer) else { return }
        if sampleBufferType == .audioApp { recording.submitAudio(sampleBuffer, source: .app); return }
        if sampleBufferType == .audioMic { recording.submitAudio(sampleBuffer, source: .microphone); return }
        guard sampleBufferType == .video,
              let pixels = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let value = (CMGetAttachment(sampleBuffer, key: RPVideoSampleOrientationKey as CFString, attachmentModeOut: nil) as? NSNumber)?.uint32Value ?? 1
        recording.submit(pixels, orientation: CGImagePropertyOrientation(rawValue: value) ?? .up,
                         seconds: CMSampleBufferGetPresentationTimeStamp(sampleBuffer).seconds)
        pipeline.submit(pixels, orientation: CGImagePropertyOrientation(rawValue: value) ?? .up,
                        capturedMS: ProcessInfo.processInfo.systemUptime * 1_000)
    }
    private func end(_ message: String) {
        finishLock.lock()
        guard !finishing else { finishLock.unlock(); return }
        finishing = true; finishLock.unlock()
        DispatchQueue.global(qos: .utility).async { [self] in
            pipeline.stop()
            let result = recording.finish()
            sendRecordingOutcome(result)
            channel?.stop()
            finishBroadcastWithError(NSError(domain: "SkyCompanionLocal", code: 1, userInfo: [NSLocalizedDescriptionKey: message]))
        }
    }

    private func sendRecordingOutcome(_ message: String) {
        // The Photos commit is independent of IPC. Give the final status a brief
        // chance to flush; never report success merely because writing started.
        let sent = DispatchSemaphore(value: 0)
        channel?.send(LocalPacket(type: "recordingFinished", message: message), completion: { _ in sent.signal() })
        _ = sent.wait(timeout: .now()+0.5)
    }
}
