import Foundation
import AVFoundation
import CoreImage
import ImageIO

/// Serial, bounded screen recording with mixed device and microphone audio.
/// One frame is being encoded and at most one newer frame waits for it.
final class BroadcastMovieWriter: @unchecked Sendable {
    var onFailure: ((Error) -> Void)?
    private let queue = DispatchQueue(label: "sky.screen.movie", qos: .userInitiated)
    private let lock = NSLock()
    private var pending: (CVPixelBuffer, CGImagePropertyOrientation, Double)?
    private var working = false
    private var accepting = true
    private var lastSubmitted = -Double.infinity
    private var paused = false
    private var resumePending = false
    private var origin: Double?
    private var offset = 0.0
    private var lastSource = 0.0
    private var lastTime = -1.0
    private var lastAudioEnd = 0.0
    private var lastAudioSourceEnd = 0.0
    private var writer: AVAssetWriter?
    private var input: AVAssetWriterInput?
    private var audioInput: AVAssetWriterInput?
    private let audioMixer = RecordingAudioMixer()
    private var queuedAudio = 0
    private var audioFailure: String?
    private var adaptor: AVAssetWriterInputPixelBufferAdaptor?
    private var recordingRegion: CGRect?
    private var regionConfigured: Bool
    private var width = 0
    private var height = 0
    private var failure: Error?
    private var frameCount = 0
    private var finishCallbacks: [(Result<URL?, Error>) -> Void] = []
    private var finished: Result<URL?, Error>?
    private let url: URL
    private let context = CIContext(options: [.useSoftwareRenderer: true, .cacheIntermediates: false])

    init(url: URL, waitForConfiguration: Bool = false) {
        self.url = url; regionConfigured = !waitForConfiguration
    }

    func setPreferSystemMix(_ value: Bool) { queue.async { self.audioMixer.preferSystemMix = value } }

    /// Normalized top-left coordinates in the oriented screen. Changes affect
    /// future frames without replacing the encoder, its audio track or timeline.
    func setRecordingRegion(_ region: CGRect?, onApplied: (() -> Void)? = nil) {
        guard region == nil || (region!.minX.isFinite && region!.minY.isFinite &&
            region!.width.isFinite && region!.height.isFinite && region!.minX >= 0 &&
            region!.minY >= 0 && region!.maxX <= 1.00001 && region!.maxY <= 1.00001 &&
            region!.width > 0.05 && region!.height > 0.05) else { return }
        queue.async {
            self.recordingRegion = region; self.regionConfigured = true
            onApplied?()
        }
    }

    var audioSummary: String {
        queue.sync {
            if let audioFailure { return "Audio recording was incomplete: \(audioFailure)" }
            if (audioMixer.appSignal || audioMixer.speechSignal) && audioMixer.microphoneSignal { return "Device audio and microphone audio were detected." }
            if !audioMixer.microphoneSignal { return "Microphone audio was not detected. Check voice assistance and microphone access." }
            return "Device audio was not detected in this recording."
        }
    }

    var audioDiagnostics: String {
        queue.sync {
            "Audio samples accepted=\(audioMixer.acceptedSamples), discarded=\(audioMixer.discardedSamples); commandMicSignal=\(audioMixer.commandMicSignal), speechSignal=\(audioMixer.speechSignal), deviceSignal=\(audioMixer.appSignal); recordingCrop=\(String(describing: recordingRegion)), encodedFrames=\(frameCount), canvas=\(width)x\(height)."
        }
    }

    func submitLocalAudio(_ audio: LocalRecordingAudio) {
        guard audio.valid else { return }
        let values = audio.pcm.withUnsafeBytes { raw in
            stride(from: 0, to: raw.count, by: 2).map { Int16(littleEndian: raw.loadUnaligned(fromByteOffset: $0, as: Int16.self)) }
        }
        guard let sample = try? RecordingAudioMixer.sample(values,
            firstSample: Int64((audio.hostSeconds*audio.sampleRate).rounded()), rate: Int32(audio.sampleRate)) else { return }
        submitAudio(sample, source: audio.source == .microphone ? .commandMicrophone : .speech)
    }

    func submitAudio(_ sample: CMSampleBuffer, source: RecordingAudioMixer.Source) {
        lock.lock()
        guard accepting, !paused, queuedAudio < 96 else { lock.unlock(); return }
        queuedAudio += 1; lock.unlock()
        queue.async {
            defer { self.lock.lock(); self.queuedAudio -= 1; self.lock.unlock() }
            guard self.finished == nil, self.audioFailure == nil, !self.resumePending,
                  let origin = self.origin, let input = self.audioInput else { return }
            do {
                let time = CMSampleBufferGetPresentationTimeStamp(sample).seconds-origin-self.offset
                let duration = Double(CMSampleBufferGetNumSamples(sample)) /
                    (CMSampleBufferGetFormatDescription(sample).flatMap { CMAudioFormatDescriptionGetStreamBasicDescription($0)?.pointee.mSampleRate } ?? 48_000)
                guard time.isFinite, duration.isFinite, time >= 0, duration > 0,
                      time < max(self.lastTime, self.lastAudioEnd)+5 else { return }
                // Static screens may yield no new ReplayKit video frames. Audio
                // remains live and must advance its own timeline, including gaps.
                self.lastAudioEnd = max(self.lastAudioEnd, time+duration)
                self.lastAudioSourceEnd = max(self.lastAudioSourceEnd, CMSampleBufferGetPresentationTimeStamp(sample).seconds+duration)
                try self.audioMixer.flush(through: max(self.lastTime, self.lastAudioEnd)-0.5, input: input)
                try self.audioMixer.append(sample, source: source, seconds: time)
            } catch { self.audioFailure = error.localizedDescription }
        }
    }

    func submit(_ pixels: CVPixelBuffer, orientation: CGImagePropertyOrientation, seconds: Double) {
        lock.lock()
        guard accepting, !paused, seconds.isFinite, seconds-lastSubmitted >= 1/15.0 else { lock.unlock(); return }
        lastSubmitted = seconds; pending = (pixels, orientation, seconds)
        guard !working else { lock.unlock(); return }
        working = true; lock.unlock()
        queue.async { self.drain() }
    }

    func pause() {
        lock.lock(); paused = true; pending = nil; lock.unlock()
    }
    func resume() {
        // ReplayKit serializes pause/resume/sample callbacks. Queue this before
        // accepting the first resumed frame to remove the paused time interval.
        queue.async { self.resumePending = true }
        lock.lock(); paused = false; lock.unlock()
    }

    func finish(_ completion: @escaping (Result<URL?, Error>) -> Void) {
        lock.lock(); accepting = false; pending = nil; lock.unlock()
        queue.async {
            if let result = self.finished { completion(result); return }
            self.finishCallbacks.append(completion)
            guard self.finishCallbacks.count == 1 else { return }
            guard let writer = self.writer, self.frameCount > 0 else {
                self.writer?.cancelWriting()
                self.complete(self.failure.map { .failure($0) } ?? .success(nil)); return
            }
            guard writer.status == .writing else {
                self.complete(.failure(writer.error ?? self.error("Video writing stopped unexpectedly."))); return
            }
            self.finalize(writer, attempt: 0)
        }
    }

    private func finalize(_ writer: AVAssetWriter, attempt: Int) {
        if let audio = audioInput {
            do { try audioMixer.flush(through: max(lastTime+1/15.0, lastAudioEnd), input: audio) }
            catch { audioFailure = error.localizedDescription }
            if audioFailure == nil, !audioMixer.isFlushed(through: max(lastTime+1/15.0, lastAudioEnd)), writer.status == .writing {
                if attempt < 200 {
                    queue.asyncAfter(deadline: .now()+0.01) { self.finalize(writer, attempt: attempt+1) }; return
                }
                audioFailure = "Audio encoder did not finish before its deadline."
            }
            audio.markAsFinished()
        }
        writer.endSession(atSourceTime: CMTime(seconds: max(lastTime + 1/15.0, lastAudioEnd), preferredTimescale: 60_000))
        input?.markAsFinished()
        writer.finishWriting {
            self.queue.async {
                self.complete(writer.status == .completed ? .success(self.url)
                    : .failure(writer.error ?? self.error("The recording could not be finalized.")))
            }
        }
    }

    private func complete(_ result: Result<URL?, Error>) {
        finished = result
        let callbacks = finishCallbacks; finishCallbacks.removeAll()
        for callback in callbacks { callback(result) }
    }

    private func drain() {
        lock.lock()
        guard let item = pending, accepting, !paused else { working = false; lock.unlock(); return }
        pending = nil; lock.unlock()
        autoreleasepool {
            guard failure == nil else { return }
            do { try append(item) } catch {
                failure = error
                lock.lock(); accepting = false; pending = nil; lock.unlock()
                onFailure?(error)
            }
        }
        queue.async { self.drain() }
    }

    private func append(_ item: (CVPixelBuffer, CGImagePropertyOrientation, Double)) throws {
        // ReplayKit can deliver frames before authenticated settings arrive. Do
        // not encode an uncropped intro or fix the canvas to that first screen.
        guard regionConfigured else { return }
        var image = CIImage(cvPixelBuffer: item.0).oriented(item.1)
        if let region = recordingRegion {
            let extent = image.extent
            let crop = CGRect(x: extent.minX + region.minX * extent.width,
                              y: extent.minY + (1-region.maxY) * extent.height,
                              width: region.width * extent.width, height: region.height * extent.height)
            image = image.cropped(to: crop)
        }
        if writer == nil {
            let scale = min(1, 1280/max(image.extent.width, image.extent.height))
            width = max(2, Int(image.extent.width*scale)/2*2)
            height = max(2, Int(image.extent.height*scale)/2*2)
            let writer = try AVAssetWriter(outputURL: url, fileType: .mov)
            writer.movieFragmentInterval = CMTime(seconds: 2, preferredTimescale: 600)
            let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
                AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: width, AVVideoHeightKey: height,
                AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 2_500_000,
                    AVVideoExpectedSourceFrameRateKey: 15, AVVideoMaxKeyFrameIntervalKey: 30]])
            input.expectsMediaDataInRealTime = true
            guard writer.canAdd(input) else { throw error("Screen recording encoder is unavailable.") }
            writer.add(input)
            let audio = AVAssetWriterInput(mediaType: .audio, outputSettings: [
                AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 48_000,
                AVNumberOfChannelsKey: 1, AVEncoderBitRateKey: 96_000])
            audio.expectsMediaDataInRealTime = true
            guard writer.canAdd(audio) else { throw error("Recording audio encoder is unavailable.") }
            writer.add(audio); self.audioInput = audio
            let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input,
                sourcePixelBufferAttributes: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
                    kCVPixelBufferWidthKey as String: width, kCVPixelBufferHeightKey as String: height,
                    kCVPixelBufferIOSurfacePropertiesKey as String: [:]])
            self.writer = writer; self.input = input; self.adaptor = adaptor
            guard writer.startWriting() else { throw writer.error ?? error("Could not start video writing.") }
            writer.startSession(atSourceTime: .zero)
        }
        guard let writer, writer.status == .writing else { throw writer?.error ?? error("Video writer failed.") }
        guard let input, input.isReadyForMoreMediaData, let adaptor, let pool = adaptor.pixelBufferPool else { return }
        if origin == nil { origin = item.2 }
        if resumePending {
            if frameCount > 0 { offset += max(0, item.2-max(lastSource+1/15.0, lastAudioSourceEnd)) }
            resumePending = false
        }
        let seconds = item.2-(origin ?? item.2)-offset
        guard seconds >= 0, seconds > lastTime else { return }
        if frameCount % 150 == 0 {
            let space = try url.deletingLastPathComponent().resourceValues(forKeys: [.volumeAvailableCapacityKey])
            if let bytes = space.volumeAvailableCapacity, bytes < 50_000_000 { throw error("Storage is nearly full. Screen recording stopped.") }
        }
        var output: CVPixelBuffer?
        guard CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault, pool, &output) == kCVReturnSuccess,
              let output else { throw error("Could not allocate a recording frame.") }
        // Keep the first frame's canvas; subsequent portrait/landscape changes
        // fit inside it without stretching, cropping, or rotating the wrong way.
        let bounds = CGRect(x: 0, y: 0, width: width, height: height)
        let scale = min(CGFloat(width)/image.extent.width, CGFloat(height)/image.extent.height)
        let fitted = image.transformed(by: .init(translationX: -image.extent.minX, y: -image.extent.minY))
            .transformed(by: .init(scaleX: scale, y: scale))
            .transformed(by: .init(translationX: (CGFloat(width)-image.extent.width*scale)/2,
                                  y: (CGFloat(height)-image.extent.height*scale)/2))
        context.render(fitted.composited(over: CIImage(color: .black).cropped(to: bounds)), to: output,
            bounds: bounds, colorSpace: CGColorSpaceCreateDeviceRGB())
        guard adaptor.append(output, withPresentationTime: CMTime(seconds: seconds, preferredTimescale: 60_000)) else {
            throw writer.error ?? error("Could not write the recording frame.")
        }
        lastTime = seconds; lastSource = item.2; frameCount += 1
        if let audioInput { try audioMixer.flush(through: seconds-0.5, input: audioInput) }
    }

    private func error(_ text: String) -> NSError {
        NSError(domain: "SkyScreenRecording", code: 1, userInfo: [NSLocalizedDescriptionKey: text])
    }
}
