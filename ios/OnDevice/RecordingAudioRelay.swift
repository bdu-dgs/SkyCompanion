import AVFoundation
import Foundation

/// Copies only active-recording PCM off the audio callback. At most eight packets
/// can be converting or in flight; a disconnected consumer cannot accumulate audio.
final class RecordingAudioRelay: @unchecked Sendable {
    private let lock = NSLock()
    private let queue = DispatchQueue(label: "sky.recording.audio.relay")
    private var channel: LoopbackChannel?
    private var recordingID: String?
    private var speechActive = false
    private var pending = 0
    private var dropped = 0
    private var epoch = UUID()

    func start(id: String, channel: LoopbackChannel) {
        lock.lock(); defer { lock.unlock() }
        guard recordingID != id else { return }
        epoch = UUID(); recordingID = id; self.channel = channel; dropped = 0
    }
    func stop() {
        lock.lock(); defer { lock.unlock() }
        epoch = UUID(); recordingID = nil; channel = nil
    }

    var diagnostics: String {
        lock.lock(); defer { lock.unlock() }
        return "Audio relay dropped callbacks=\(dropped), pending=\(pending)."
    }

    func finish(_ completion: @escaping () -> Void) {
        // Stop accepting new PCM but drain already-copied buffers before the app
        // sends Stop on the same IPC queue. This preserves the last spoken word.
        lock.lock(); recordingID = nil; channel = nil; lock.unlock()
        queue.async(execute: completion)
    }

    func setSpeechActive(_ value: Bool) { lock.lock(); speechActive = value; lock.unlock() }

    func capture(_ buffer: AVAudioPCMBuffer, at time: AVAudioTime, source: LocalRecordingAudio.Source) {
        lock.lock()
        guard let id = recordingID, let channel, source != .speech || speechActive else { lock.unlock(); return }
        guard pending < 8, time.isHostTimeValid, buffer.frameLength > 0,
              Double(buffer.frameLength)/buffer.format.sampleRate <= 0.25,
              buffer.frameLength <= 16_384 else { dropped += 1; lock.unlock(); return }
        let token = epoch
        pending += 1
        lock.unlock()
        // AVAudioEngine reuses tap storage after this callback, so retain a copy.
        guard let copy = AVAudioPCMBuffer(pcmFormat: buffer.format, frameCapacity: buffer.frameLength) else {
            complete(); return
        }
        copy.frameLength = buffer.frameLength
        let src = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: buffer.audioBufferList))
        let dst = UnsafeMutableAudioBufferListPointer(copy.mutableAudioBufferList)
        for i in 0..<src.count {
            if let from = src[i].mData, let to = dst[i].mData {
                memcpy(to, from, Int(src[i].mDataByteSize))
            }
        }
        let seconds = AVAudioTime.seconds(forHostTime: time.hostTime)
        queue.async { [self] in
            lock.lock(); let active = token == epoch; lock.unlock()
            guard active else { complete(); return }
            guard let pcm = Self.monoPCM(copy) else { complete(); return }
            let audio = LocalRecordingAudio(recordingID: id, source: source, hostSeconds: seconds,
                                           sampleRate: copy.format.sampleRate, pcm: pcm)
            guard audio.valid else { complete(); return }
            channel.send(LocalPacket(type: "recordingAudio", recordingAudio: audio)) { [weak self] _ in self?.complete() }
        }
    }
    private func complete() { lock.lock(); pending -= 1; lock.unlock() }

    static func monoPCM(_ buffer: AVAudioPCMBuffer) -> Data? {
        let channels = Int(buffer.format.channelCount), count = Int(buffer.frameLength)
        guard channels > 0, count > 0 else { return nil }
        let interleaved = buffer.format.isInterleaved
        var samples = [Int16](repeating: 0, count: count)
        for i in 0..<count {
            var sum: Float = 0
            for c in 0..<channels {
                let row = interleaved ? 0 : c, column = interleaved ? i*channels+c : i
                if let floats = buffer.floatChannelData { sum += floats[row][column] }
                else if let shorts = buffer.int16ChannelData { sum += Float(shorts[row][column])/32768 }
                else { return nil }
            }
            let value = sum/Float(channels)
            samples[i] = Int16(max(-1, min(1, value.isFinite ? value : 0))*32767).littleEndian
        }
        return samples.withUnsafeBytes { Data($0) }
    }
}
