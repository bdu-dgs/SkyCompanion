import ReplayKit
import CoreMedia
import Foundation

final class SampleHandler: RPBroadcastSampleHandler {
    private let encodeQueue = DispatchQueue(label: "skycompanion.capture.encode", qos: .userInitiated)
    private let gate = NSLock()
    private let encoder = FrameEncoder()
    private var transport: BroadcastTransport?
    // gate protects callback/encoding/network transitions; at most one raw buffer
    // may be retained by encodeQueue. Incoming frames are dropped while it is busy.
    private var running = false
    private var paused = false
    private var connected = false
    private var encoding = false
    private var epoch = 0
    private var cadence = CaptureCadence(framesPerSecond: 15)
    private var nextFrameID = 0

    override func broadcastStarted(withSetupInfo setupInfo: [String: NSObject]?) {
        do {
            let configuration = try CaptureConfiguration.load()
            let sender = BroadcastTransport(configuration: configuration)
            sender.onReadyChanged = { [weak self] ready in self?.setReady(ready) }
            sender.onFatalError = { [weak self] message in
                self?.finishBroadcastWithError(NSError(domain: "SkyCompanionCapture", code: 1,
                                                     userInfo: [NSLocalizedDescriptionKey: message]))
            }
            transport = sender
            gate.lock()
            running = true
            paused = false
            epoch += 1
            gate.unlock()
            sender.start()
        } catch {
            finishBroadcastWithError(error)
        }
    }

    override func broadcastPaused() {
        gate.lock()
        paused = true
        epoch += 1
        gate.unlock()
        transport?.pause()
    }

    override func broadcastResumed() {
        gate.lock()
        paused = false
        epoch += 1
        cadence.reset()
        gate.unlock()
        transport?.resume()
    }

    override func broadcastFinished() {
        gate.lock()
        running = false
        connected = false
        epoch += 1
        gate.unlock()
        transport?.finish()
    }

    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer, with sampleBufferType: RPSampleBufferType) {
        // Discard both app audio and microphone samples even if a system setting
        // outside the host app requests them.
        guard sampleBufferType == .video, CMSampleBufferDataIsReady(sampleBuffer) else { return }
        let now = ProcessInfo.processInfo.systemUptime * 1_000
        gate.lock()
        guard running, !paused, connected, !encoding, cadence.take(at: now) else {
            gate.unlock()
            return
        }
        encoding = true
        nextFrameID += 1
        let frameID = nextFrameID
        let frameEpoch = epoch
        gate.unlock()

        let rawOrientation = (CMGetAttachment(sampleBuffer, key: RPVideoSampleOrientationKey as CFString,
                                             attachmentModeOut: nil) as? NSNumber)?.intValue ?? 1
        let orientation = (1...8).contains(rawOrientation) ? rawOrientation : 1
        encodeQueue.async { [weak self] in
            guard let self else { return }
            autoreleasepool {
                let frame = self.encoder.encode(sampleBuffer, id: frameID, capturedMS: now, orientation: orientation)
                self.gate.lock()
                self.encoding = false
                let usable = self.running && !self.paused && self.connected && self.epoch == frameEpoch
                // Submit while holding gate so a disconnect cannot race between
                // the epoch check and enqueueing a frame into the old connection.
                if usable, let frame { self.transport?.submit(frame) }
                self.gate.unlock()
            }
        }
    }

    private func setReady(_ ready: Bool) {
        gate.lock()
        if connected != ready {
            connected = ready
            epoch += 1
            cadence.reset()
        }
        gate.unlock()
    }
}
