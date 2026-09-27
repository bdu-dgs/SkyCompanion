import AVFoundation

/// Plays the same synthesized PCM that the recording tap observes. The tap is on
/// the rendered mixer, not on synthesis callbacks, so cancelled tails aren't saved.
final class SpeechPCMPlayer: @unchecked Sendable {
    var onActive: ((Bool) -> Void)?
    let node = AVAudioPlayerNode()
    let mixer = AVAudioMixerNode()
    let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48_000, channels: 1, interleaved: false)!
    private let queue = DispatchQueue(label: "sky.speech.pcm")
    private var token = UUID()
    private var converter: AVAudioConverter?
    private var inputFormat: AVAudioFormat?
    private var pendingFrames = 0
    private var pendingBuffers = 0
    private var ended = false
    private var started = false
    private var onStart: (() -> Void)?
    private let renderLock = NSLock()
    private var renderStarted: (() -> Void)?
    private var onFinish: (() -> Void)?
    private var onFailure: ((String) -> Void)?

    func begin(start: @escaping () -> Void, finish: @escaping () -> Void,
               failure: @escaping (String) -> Void) -> UUID {
        queue.sync {
            stopInternal(); onStart = start; onFinish = finish; onFailure = failure
            return token
        }
    }
    func stop() { queue.sync { stopInternal() } }
    private func stopInternal() {
        renderLock.lock(); renderStarted = nil; renderLock.unlock()
        token = UUID(); onActive?(false); node.stop(); converter = nil; inputFormat = nil
        pendingFrames = 0; pendingBuffers = 0; ended = false; started = false
        onStart = nil; onFinish = nil; onFailure = nil
    }
    // Synthesis callbacks are not audio render callbacks. Serialize conversion here
    // rather than launching an unbounded task for every generated buffer.
    func append(_ buffer: AVAudioBuffer, token expected: UUID) {
        queue.sync {
            guard expected == token else { return }
            guard let pcm = buffer as? AVAudioPCMBuffer else { fail("Speech returned an unsupported audio buffer."); return }
            if pcm.frameLength == 0 { ended = true; finishIfDrained(); return }
            guard pcm.format.sampleRate > 0, pendingFrames < 48_000*60 else {
                fail("Speech exceeded the playback buffer limit."); return
            }
            if inputFormat != pcm.format {
                inputFormat = pcm.format; converter = AVAudioConverter(from: pcm.format, to: format)
                converter?.primeMethod = .none
            }
            guard let converter, let output = AVAudioPCMBuffer(pcmFormat: format,
                frameCapacity: AVAudioFrameCount(ceil(Double(pcm.frameLength)*48_000/pcm.format.sampleRate)+64)) else {
                fail("Speech audio conversion is unavailable."); return
            }
            var delivered = false
            var error: NSError?
            let result = converter.convert(to: output, error: &error) { _, status in
                if delivered { status.pointee = .noDataNow; return nil }
                delivered = true; status.pointee = .haveData; return pcm
            }
            guard result != .error else { fail(error?.localizedDescription ?? "Speech audio conversion failed."); return }
            guard output.frameLength > 0 else { return }
            let frames = Int(output.frameLength)
            pendingFrames += frames; pendingBuffers += 1
            node.scheduleBuffer(output, completionCallbackType: .dataPlayedBack) { [weak self] _ in
                guard let self else { return }
                self.queue.async {
                    guard self.token == expected else { return }
                    self.pendingFrames -= frames; self.pendingBuffers -= 1; self.finishIfDrained()
                }
            }
            if !started {
                started = true
                renderLock.lock(); renderStarted = onStart; renderLock.unlock()
                onActive?(true); node.play()
            }
        }
    }
    /// Scheduling is not playback: confirm only non-silent PCM in the output tap.
    /// This callback does not prove that the user heard the physical speaker.
    func didRender(_ buffer: AVAudioPCMBuffer) {
        guard let samples = buffer.floatChannelData, buffer.frameLength > 0,
              (0..<Int(buffer.frameLength)).contains(where: { abs(samples[0][$0]) > 0.00001 }) else { return }
        renderLock.lock(); let callback = renderStarted; renderStarted = nil; renderLock.unlock()
        callback?()
    }

    private func finishIfDrained() {
        guard ended, pendingBuffers == 0 else { return }
        let completed = onFinish; stopInternal(); completed?()
    }
    private func fail(_ message: String) { let callback = onFailure; stopInternal(); callback?(message) }
}
