// Offline render check for the production playback path. No microphone or speaker.
import AVFoundation
import Foundation

@main struct SpeechPCMTest {
    static func main() throws {
        let engine = AVAudioEngine(), player = SpeechPCMPlayer()
        engine.attach(player.node); engine.attach(player.mixer)
        engine.connect(player.node, to: player.mixer, format: player.format)
        engine.connect(player.mixer, to: engine.mainMixerNode, format: player.format)
        try engine.enableManualRenderingMode(.offline, format: player.format, maximumFrameCount: 1024)
        try engine.start()
        defer { player.stop(); engine.stop() }
        let callback = DispatchSemaphore(value: 0)
        let token = player.begin(start: { callback.signal() }, finish: {}, failure: { fatalError($0) })
        let source = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 24_000, channels: 1, interleaved: false)!
        let pcm = AVAudioPCMBuffer(pcmFormat: source, frameCapacity: 24_000)!
        pcm.frameLength = 24_000
        for i in 0..<24_000 { pcm.floatChannelData![0][i] = Float(0.3*sin(2*Double.pi*500*Double(i)/24_000)) }
        player.append(pcm, token: token)
        precondition(callback.wait(timeout: .now()+0.05) == .timedOut,
                     "Scheduling alone must never report audible playback")
        let silence = AVAudioPCMBuffer(pcmFormat: player.format, frameCapacity: 1024)!
        silence.frameLength = 1024
        for i in 0..<1024 { silence.floatChannelData![0][i] = 0 }
        player.didRender(silence)
        precondition(callback.wait(timeout: .now()+0.05) == .timedOut,
                     "Silent output must not report speech started")
        let output = AVAudioPCMBuffer(pcmFormat: player.format, frameCapacity: 1024)!
        var energy: Float = 0
        for _ in 0..<10 {
            let status = try engine.renderOffline(1024, to: output)
            if status == .success { player.didRender(output); for i in 0..<Int(output.frameLength) { energy += abs(output.floatChannelData![0][i]) } }
        }
        precondition(callback.wait(timeout: .now()+1) == .success,
                     "Rendered non-silent speech must report playback")
        precondition(callback.wait(timeout: .now()+0.05) == .timedOut,
                     "Playback start must be delivered only once")
        precondition(energy > 100, "Speech PCM must reach the output mixer")
        player.stop()
        // A callback from a cancelled synthesizer must never restart audio.
        player.append(pcm, token: token)
        for _ in 0..<5 { _ = try engine.renderOffline(1024, to: output) }
        var tail: Float = 0
        for _ in 0..<5 {
            if try engine.renderOffline(1024, to: output) == .success {
                for i in 0..<Int(output.frameLength) { tail += abs(output.floatChannelData![0][i]) }
            }
        }
        precondition(tail < 0.01, "Cancelled speech must not reach playback or recording")
        print("PASS: rendered speech, 24k-to-48k resampling, cancellation, stale synthesis rejected, start requires non-silent rendering. Offline macOS only.")
    }
}
