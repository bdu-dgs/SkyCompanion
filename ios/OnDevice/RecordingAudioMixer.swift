import AVFoundation
import Foundation

/// Normalizes ReplayKit app/microphone PCM into one timestamped AAC input stream.
/// Used only on the movie writer's serial queue. Keeps at most two seconds of PCM.
final class RecordingAudioMixer {
    enum Source: Hashable { case app, microphone, commandMicrophone, speech }
    private struct Block {
        var app = [Float](repeating: 0, count: 480)
        var mic = [Float](repeating: 0, count: 480)
        var commandMic = [Float](repeating: 0, count: 480)
        var speech = [Float](repeating: 0, count: 480)
        var commandPresent = [Bool](repeating: false, count: 480)
        var speechPresent = [Bool](repeating: false, count: 480)
    }
    private var blocks: [Int: Block] = [:]
    private var converters: [Source: AVAudioConverter] = [:]
    private var formats: [Source: AVAudioFormat] = [:]
    var preferSystemMix = false
    private var nextBlock = 0
    private(set) var acceptedSamples: [Source: Int] = [:]
    private(set) var discardedSamples: [Source: Int] = [:]
    private(set) var speechSignal = false
    private(set) var commandMicSignal = false
    private(set) var appSignal = false
    private(set) var microphoneSignal = false
    private let outputFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48_000, channels: 1, interleaved: false)!

    func append(_ sample: CMSampleBuffer, source: Source, seconds: Double) throws {
        guard seconds.isFinite, seconds >= 0, seconds < Double(Int.max)/48_000, let description = CMSampleBufferGetFormatDescription(sample),
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(description),
              let format = AVAudioFormat(streamDescription: asbd) else { return }
        let count = CMSampleBufferGetNumSamples(sample)
        guard count > 0, count <= 96_000, format.sampleRate > 0,
              let pcm = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(count)) else { return }
        pcm.frameLength = AVAudioFrameCount(count)
        guard CMSampleBufferCopyPCMDataIntoAudioBufferList(sample, at: 0, frameCount: Int32(count), into: pcm.mutableAudioBufferList) == noErr else {
            throw failure("ReplayKit audio could not be decoded.")
        }
        if formats[source] != format {
            formats[source] = format
            converters[source] = AVAudioConverter(from: format, to: outputFormat)
            converters[source]?.primeMethod = .none
        }
        guard let converter = converters[source],
              let normalized = AVAudioPCMBuffer(pcmFormat: outputFormat,
                frameCapacity: AVAudioFrameCount(ceil(Double(count)*48_000/format.sampleRate)+64)) else {
            throw failure("The recording audio format is unsupported.")
        }
        var delivered = false
        var error: NSError?
        let status = converter.convert(to: normalized, error: &error) { _, inputStatus in
            if delivered { inputStatus.pointee = .noDataNow; return nil }
            delivered = true; inputStatus.pointee = .haveData; return pcm
        }
        guard status != .error, let samples = normalized.floatChannelData?[0] else {
            throw error ?? failure("Audio conversion failed.")
        }
        let start = Int((seconds*48_000).rounded())
        var i = 0
        while i < Int(normalized.frameLength) {
            let position = start+i, index = position/480, offset = position%480
            let count = min(480-offset, Int(normalized.frameLength)-i)
            guard index >= nextBlock, index < nextBlock+200 else {
                discardedSamples[source, default: 0] += count; i += count; continue
            }
            acceptedSamples[source, default: 0] += count
            var block = blocks[index] ?? Block()
            for j in 0..<count {
                let value = samples[i+j].isFinite ? samples[i+j] : 0
                if abs(value) > 0.005 {
                    switch source {
                    case .app: appSignal = true
                    case .microphone: microphoneSignal = true
                    case .commandMicrophone: microphoneSignal = true; commandMicSignal = true
                    case .speech: speechSignal = true
                    }
                }
                switch source {
                case .app: block.app[offset+j] = value
                case .microphone: block.mic[offset+j] = value
                case .commandMicrophone:
                    block.commandMic[offset+j] = value; block.commandPresent[offset+j] = true
                case .speech:
                    block.speech[offset+j] = value; block.speechPresent[offset+j] = true
                }
            }
            blocks[index] = block
            i += count
        }
    }

    func isFlushed(through seconds: Double) -> Bool { nextBlock >= Int(max(0, seconds)*100) }

    /// A short reorder window lets app and microphone callbacks reach the same block.
    /// Backpressure stops flushing instead of queuing unbounded encoded samples.
    func flush(through seconds: Double, input: AVAssetWriterInput) throws {
        guard seconds.isFinite, seconds >= 0 else { return }
        let end = Int(seconds*100)
        while nextBlock < end && input.isReadyForMoreMediaData {
            let block = blocks.removeValue(forKey: nextBlock) ?? Block()
            // In local-video tests ReplayKit captures the foreground app's full
            // output mix (video soundtrack + rendered speech). Keep that mix rather
            // than replacing the soundtrack with the direct speech fallback.
            let systemMixAudible = preferSystemMix && block.app.contains { abs($0) > 0.0005 }
            let mixed = (0..<480).map { i -> Int16 in
                // Prefer the directly rendered answer during speech; ReplayKit may
                // also contain that answer. Likewise, never double the microphone.
                let device = systemMixAudible ? block.app[i] : (block.speechPresent[i] ? block.speech[i] : block.app[i])
                let mic = block.commandPresent[i] ? block.commandMic[i] : block.mic[i]
                let value = max(-1, min(1, 0.5*device+0.5*mic))
                return Int16(value*32767)
            }
            let sample = try Self.sample(mixed, firstSample: Int64(nextBlock)*480)
            guard input.append(sample) else { throw failure("Could not write the mixed recording audio.") }
            nextBlock += 1
        }
    }

    static func sample(_ values: [Int16], firstSample: Int64, rate: Int32 = 48_000, channels: UInt32 = 1) throws -> CMSampleBuffer {
        guard channels > 0, values.count % Int(channels) == 0 else { throw failure("Invalid audio channel data.") }
        var asbd = AudioStreamBasicDescription(mSampleRate: Double(rate), mFormatID: kAudioFormatLinearPCM,
            mFormatFlags: kLinearPCMFormatFlagIsSignedInteger | kLinearPCMFormatFlagIsPacked,
            mBytesPerPacket: 2*channels, mFramesPerPacket: 1, mBytesPerFrame: 2*channels, mChannelsPerFrame: channels,
            mBitsPerChannel: 16, mReserved: 0)
        var format: CMAudioFormatDescription?
        guard CMAudioFormatDescriptionCreate(allocator: kCFAllocatorDefault, asbd: &asbd, layoutSize: 0,
            layout: nil, magicCookieSize: 0, magicCookie: nil, extensions: nil, formatDescriptionOut: &format) == noErr,
              let format else { throw failure("Could not create audio format.") }
        var block: CMBlockBuffer?
        let bytes = values.count*2
        guard CMBlockBufferCreateWithMemoryBlock(allocator: kCFAllocatorDefault, memoryBlock: nil,
            blockLength: bytes, blockAllocator: kCFAllocatorDefault, customBlockSource: nil,
            offsetToData: 0, dataLength: bytes, flags: 0, blockBufferOut: &block) == noErr, let block else {
            throw failure("Could not allocate recording audio.")
        }
        let copied = values.withUnsafeBytes { CMBlockBufferReplaceDataBytes(with: $0.baseAddress!, blockBuffer: block, offsetIntoDestination: 0, dataLength: bytes) }
        guard copied == noErr else { throw failure("Could not copy recording audio.") }
        var timing = CMSampleTimingInfo(duration: CMTime(value: 1, timescale: rate),
            presentationTimeStamp: CMTime(value: firstSample, timescale: rate), decodeTimeStamp: .invalid)
        var size = 2*Int(channels)
        var sample: CMSampleBuffer?
        guard CMSampleBufferCreateReady(allocator: kCFAllocatorDefault, dataBuffer: block,
            formatDescription: format, sampleCount: values.count/Int(channels), sampleTimingEntryCount: 1,
            sampleTimingArray: &timing, sampleSizeEntryCount: 1, sampleSizeArray: &size,
            sampleBufferOut: &sample) == noErr, let sample else { throw failure("Could not create recording audio.") }
        return sample
    }

    private static func failure(_ text: String) -> NSError {
        NSError(domain: "SkyRecordingAudio", code: 1, userInfo: [NSLocalizedDescriptionKey: text])
    }
    private func failure(_ text: String) -> NSError { Self.failure(text) }
}
