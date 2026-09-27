import Foundation
import Photos
import CoreVideo
import ImageIO
import CoreMedia

/// Saves inside the upload extension, so finalization does not depend on the
/// containing app remaining awake or an App Groups entitlement.
final class BroadcastRecording: @unchecked Sendable {
    var onStatus: ((String) -> Void)?
    var onStarted: ((String) -> Void)?
    var onDiagnostics: ((String) -> Void)?
    private var recordingID: String?
    private let lock = NSLock()
    private var movie: BroadcastMovieWriter?
    private var ending = false
    private let completed = DispatchGroup()
    private let saves = DispatchQueue(label: "sky.recording.photos", qos: .utility)
    private var finalMessage = "No recording was started."
    private var stoppedEarly: String?

    func start() {
        let status = PHPhotoLibrary.authorizationStatus(for: .addOnly)
        guard status == .authorized || status == .limited else {
            onStatus?("Video saving is off. Allow Add Photos in iPhone Settings, then restart the broadcast."); return
        }
        do {
            let folder = try directory()
            // Retained completed files from a previous failed Photos import are
            // retried only after permission is present. Never delete failed saves.
            let pending = try FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)
                .filter { $0.pathExtension == "mov" && FileManager.default.fileExists(atPath: $0.appendingPathExtension("ready").path) }
            saves.async { for url in pending { _ = self.importIntoPhotos(url) } }
            let url = folder.appendingPathComponent("SkyCompanion-\(UUID().uuidString).mov")
            let movie = BroadcastMovieWriter(url: url, waitForConfiguration: true)
            movie.onFailure = { [weak self] error in
                guard let self else { return }
                self.lock.lock(); self.stoppedEarly = error.localizedDescription; self.lock.unlock()
                self.onStatus?("Recording stopped early: \(error.localizedDescription)")
            }
            let id = UUID().uuidString
            lock.lock(); self.movie = movie; self.recordingID = id; lock.unlock()
            onStarted?(id)
            onStatus?("Recording screen, your voice and SkyCompanion responses on this phone.")
        } catch { onStatus?("Could not start video saving: \(error.localizedDescription)") }
    }

    func configureAudio(localVideo: Bool, region: CaptureRegion?, onApplied: (() -> Void)? = nil) {
        lock.lock(); let current = movie; lock.unlock()
        current?.setPreferSystemMix(localVideo)
        current?.setRecordingRegion(region?.rect, onApplied: onApplied)
    }

    func publishCurrentState() {
        lock.lock(); let id = ending ? nil : recordingID; let failure = stoppedEarly; lock.unlock()
        if let failure {
            onStatus?("Recording stopped early: \(failure)"); return
        }
        if let id {
            onStarted?(id)
            onStatus?("Screen recording continues. Your voice and responses are included while voice assistance is available.")
        } else {
            onStatus?("Recording is unavailable. Check Photos permission and restart the broadcast.")
        }
    }

    func submit(_ pixels: CVPixelBuffer, orientation: CGImagePropertyOrientation, seconds: Double) {
        lock.lock(); let current = movie; lock.unlock()
        current?.submit(pixels, orientation: orientation, seconds: seconds)
    }
    func submitAudio(_ sample: CMSampleBuffer, source: RecordingAudioMixer.Source) {
        lock.lock(); let current = movie; lock.unlock()
        current?.submitAudio(sample, source: source)
    }
    func submitLocalAudio(_ audio: LocalRecordingAudio) {
        lock.lock(); let current = audio.recordingID == recordingID && !ending ? movie : nil; lock.unlock()
        current?.submitLocalAudio(audio)
    }
    func pause() { lock.lock(); let current = movie; lock.unlock(); current?.pause() }
    func resume() { lock.lock(); let current = movie; lock.unlock(); current?.resume() }

    /// ReplayKit has no completion-handler argument for broadcastFinished.
    /// Keep that callback alive for a bounded finalization + Photos transaction.
    /// Encoding remains on its own queue; no inference/sample callback waits.
    func finish(timeout: Double = 15) -> String {
        lock.lock()
        if !ending {
            ending = true
            if let current = movie {
                completed.enter()
                current.finish { result in
                    self.saves.async {
                        self.onDiagnostics?(current.audioDiagnostics)
                        let message: String
                        switch result {
                        case .success(let url?):
                            do {
                                try Data().write(to: url.appendingPathExtension("ready"), options: .atomic)
                                let saved = self.importIntoPhotos(url)
                                self.lock.lock(); let early = self.stoppedEarly; self.lock.unlock()
                                if saved == "Video saved to Photos." {
                                    message = (early.map { "Partial video saved to Photos. Recording stopped early: \($0)" } ?? saved)
                                        + " " + current.audioSummary
                                } else { message = saved }
                            } catch { message = "Video retained on this phone, but saving to Photos failed: \(error.localizedDescription)" }
                        case .success(nil): message = "No video frames were received. Nothing was saved."
                        case .failure(let error): message = "Video recording failed: \(error.localizedDescription)"
                        }
                        self.lock.lock(); self.finalMessage = message; self.lock.unlock()
                        self.onStatus?(message); self.completed.leave()
                    }
                }
            }
        }
        lock.unlock()
        onStatus?("Finishing recording. Check Photos after the broadcast stops.")
        guard completed.wait(timeout: .now()+timeout) == .success else {
            return "Video save is not confirmed. Check Photos; any completed unsaved video will be retried on the next broadcast."
        }
        lock.lock(); defer { lock.unlock() }; return finalMessage
    }

    private func importIntoPhotos(_ url: URL) -> String {
        do {
            try PHPhotoLibrary.shared().performChangesAndWait {
                let request = PHAssetCreationRequest.forAsset()
                let options = PHAssetResourceCreationOptions()
                options.originalFilename = url.lastPathComponent
                // Copy, not move: failed imports must not destroy the only file.
                options.shouldMoveFile = false
                request.addResource(with: .video, fileURL: url, options: options)
            }
            try? FileManager.default.removeItem(at: url)
            try? FileManager.default.removeItem(at: url.appendingPathExtension("ready"))
            return "Video saved to Photos."
        } catch {
            return "Video could not be added to Photos. It is retained on this phone for retry on the next broadcast. \(error.localizedDescription)"
        }
    }
    private func directory() throws -> URL {
        let url = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("ScreenRecordings", isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }
}
