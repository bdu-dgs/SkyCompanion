// Compile with the production BroadcastMovieWriter.swift on macOS.
// These synthetic frames verify file writing, not ReplayKit or Photos permissions.
import Foundation
import AVFoundation
import CoreVideo
import ImageIO

@main struct RecordingTest {
    static func pixels(width: Int = 640, height: Int = 360) throws -> CVPixelBuffer {
        var output: CVPixelBuffer?
        guard CVPixelBufferCreate(kCFAllocatorDefault, width, height, kCVPixelFormatType_32BGRA,
            [kCVPixelBufferIOSurfacePropertiesKey: [:]] as CFDictionary, &output) == kCVReturnSuccess,
            let output else { throw NSError(domain: "Test", code: 1) }
        CVPixelBufferLockBaseAddress(output, [])
        let base = CVPixelBufferGetBaseAddress(output)!.assumingMemoryBound(to: UInt8.self)
        let stride = CVPixelBufferGetBytesPerRow(output)
        for y in 0..<height { for x in 0..<width {
            let p = y*stride+x*4
            base[p] = 32; base[p+1] = y < height/2 ? 0 : 255
            base[p+2] = y < height/2 ? 255 : 0; base[p+3] = 255
        } }
        CVPixelBufferUnlockBaseAddress(output, [])
        return output
    }
    static func finish(_ writer: BroadcastMovieWriter) async -> Result<URL?, Error> {
        await withCheckedContinuation { continuation in writer.finish { continuation.resume(returning: $0) } }
    }
    static func tone(_ recorder: BroadcastMovieWriter, time: Double, rate: Int32, frequency: Double, source: RecordingAudioMixer.Source) throws {
        let count = Int(rate)/12
        let addSystemSpeech = source == .app && CommandLine.arguments.contains("--system-mix")
        let samples = (0..<count).map { index -> Int16 in
            let time = Double(index)/Double(rate)
            let primary = 12_000*sin(2*Double.pi*frequency*time)
            let spoken = addSystemSpeech ? 12_000*sin(2*Double.pi*576*time) : 0
            return Int16(primary+spoken)
        }
        if (source == .commandMicrophone || source == .speech) {
            let data = samples.withUnsafeBytes { Data($0) }
            let audio = LocalRecordingAudio(recordingID: "test", source: source == .speech ? .speech : .microphone,
                hostSeconds: time, sampleRate: Double(rate), pcm: data)
            precondition(audio.valid)
            recorder.submitLocalAudio(audio); return
        }
        let channels: UInt32 = source == .app ? 2 : 1
        let interleaved = channels == 2 ? samples.flatMap { [$0,$0] } : samples
        let buffer = try RecordingAudioMixer.sample(interleaved, firstSample: Int64((time*Double(rate)).rounded()), rate: rate, channels: channels)
        recorder.submitAudio(buffer, source: source)
    }
    static func main() async throws {
        let direct = CommandLine.arguments.contains("--direct")
        let staticScreen = CommandLine.arguments.contains("--static")
        let systemMix = CommandLine.arguments.contains("--system-mix")
        let crop = CommandLine.arguments.contains("--crop")
        let preselected = CommandLine.arguments.contains("--preselected-crop")
        let root = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let movieURL = root.appendingPathComponent("orientation-and-pause.mov")
        let recorder = BroadcastMovieWriter(url: movieURL, waitForConfiguration: preselected)
        recorder.setPreferSystemMix(systemMix)
        let landscape = try pixels(), portrait = try pixels(width: 360, height: 640)
        if preselected {
            recorder.submit(landscape, orientation: .up, seconds: 99)
            try await Task.sleep(nanoseconds: 100_000_000)
            await withCheckedContinuation { continuation in
                recorder.setRecordingRegion(CGRect(x:0,y:0,width:1,height:0.5)) { continuation.resume() }
            }
        }
        for i in 0..<(staticScreen ? 60 : 12) {
            if crop && i == 3 { recorder.setRecordingRegion(CGRect(x:0,y:0,width:1,height:0.5)) }
            if crop && i == 7 { recorder.setRecordingRegion(CGRect(x:0,y:0.5,width:1,height:0.5)) }
            if crop && i == 8 { recorder.setRecordingRegion(CGRect(x:0,y:0,width:2,height:1)) } // Invalid: retain last crop.
            if !staticScreen || i == 0 { recorder.submit(landscape, orientation: .up, seconds: 100+Double(i)/12) }
            try await Task.sleep(nanoseconds: 85_000_000)
            try tone(recorder, time: 100+Double(i)/12, rate: 48_000, frequency: 432, source: .app)
            try tone(recorder, time: 100+Double(i)/12, rate: 16_000, frequency: 864, source: .microphone)
            if direct {
                try tone(recorder, time: 100+Double(i)/12, rate: 48_000, frequency: 576, source: .speech)
                try tone(recorder, time: 100+Double(i)/12, rate: 48_000, frequency: 1008, source: .commandMicrophone)
            }
        }
        recorder.pause()
        recorder.submit(landscape, orientation: .up, seconds: 110)
        recorder.resume()
        for i in 0..<12 {
            if !staticScreen || i == 0 { recorder.submit(portrait, orientation: .right, seconds: 130+Double(i)/12) }
            try await Task.sleep(nanoseconds: 85_000_000)
            try tone(recorder, time: 130+Double(i)/12, rate: 48_000, frequency: 432, source: .app)
            try tone(recorder, time: 130+Double(i)/12, rate: 44_100, frequency: 864, source: .microphone)
        }
        recorder.submit(landscape, orientation: .up, seconds: .nan)
        recorder.submit(landscape, orientation: .up, seconds: 90)
        async let first = finish(recorder)
        async let second = finish(recorder)
        let outcomes = await [first, second]
        for result in outcomes { let url = try result.get(); precondition(url == movieURL) }
        let asset = AVURLAsset(url: movieURL)
        let duration = try await asset.load(.duration).seconds
        let track = try await asset.loadTracks(withMediaType: .video).first!
        let size = try await track.load(.naturalSize)
        let playable = try await asset.load(.isPlayable)
        precondition(playable && duration > (staticScreen ? 5.5 : 1.5) && duration < (staticScreen ? 6.2 : 3), "Pause must not produce a 30-second gap or truncate static-screen audio")
        precondition(size == CGSize(width: 640, height: preselected ? 180 : 360))
        let reader = try AVAssetReader(asset: asset)
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
        reader.add(output); precondition(reader.startReading())
        var frames = 0
        while let sample = output.copyNextSampleBuffer() {
            precondition(CMSampleBufferGetImageBuffer(sample) != nil)
            if preselected && frames < 12 {
                let pixel = CMSampleBufferGetImageBuffer(sample)!
                CVPixelBufferLockBaseAddress(pixel, .readOnly)
                let bytes = CVPixelBufferGetBaseAddress(pixel)!.assumingMemoryBound(to: UInt8.self)
                for y in [0.2,0.8] { for x in [0.2,0.8] {
                    let index = CVPixelBufferGetBytesPerRow(pixel)*Int(Double(CVPixelBufferGetHeight(pixel))*y)
                        + 4*Int(Double(CVPixelBufferGetWidth(pixel))*x)
                    let red = Int(bytes[index+2]), green = Int(bytes[index+1])
                    precondition(frames < 7 ? red > green+100 : green > red+100,
                        "Every encoded source pixel must come from the applied crop, including the first frame")
                } }
                CVPixelBufferUnlockBaseAddress(pixel, .readOnly)
            }
            if crop && (frames == 4 || frames == 9) {
                let pixel = CMSampleBufferGetImageBuffer(sample)!
                CVPixelBufferLockBaseAddress(pixel, .readOnly)
                let bytes = CVPixelBufferGetBaseAddress(pixel)!.assumingMemoryBound(to: UInt8.self)
                let index = CVPixelBufferGetBytesPerRow(pixel)*(CVPixelBufferGetHeight(pixel)/2)+4*(CVPixelBufferGetWidth(pixel)/2)
                let red = Int(bytes[index+2]), green = Int(bytes[index+1])
                CVPixelBufferUnlockBaseAddress(pixel, .readOnly)
                precondition(frames == 4 ? red > green+100 : green > red+100,
                             "Live crop must select top/bottom correctly in the same movie, rejecting invalid changes")
            }
            frames += 1
        }
        precondition(reader.status == .completed && frames >= (staticScreen ? 2 : 20))
        let audioTracks = try await asset.loadTracks(withMediaType: .audio)
        precondition(audioTracks.count == 1, "Photos must receive one mixed track")
        let audioReader = try AVAssetReader(asset: asset)
        let audioOutput = AVAssetReaderTrackOutput(track: audioTracks[0], outputSettings: [
            AVFormatIDKey: kAudioFormatLinearPCM, AVLinearPCMBitDepthKey: 32,
            AVLinearPCMIsFloatKey: true, AVLinearPCMIsNonInterleaved: false])
        audioReader.add(audioOutput); precondition(audioReader.startReading())
        var decoded = [Float]()
        while let sample = audioOutput.copyNextSampleBuffer(), let block = CMSampleBufferGetDataBuffer(sample) {
            let size = CMBlockBufferGetDataLength(block)
            var values = [Float](repeating: 0, count: size/4)
            let status = values.withUnsafeMutableBytes { CMBlockBufferCopyDataBytes(block, atOffset: 0, dataLength: size, destination: $0.baseAddress!) }
            precondition(status == noErr); decoded.append(contentsOf: values)
        }
        precondition(audioReader.status == .completed && decoded.count > 80_000)
        // Check both tones survived mix/resampling/AAC. Use a block before pause
        // so encoder priming and independent second-segment phase cannot cancel it.
        func strength(_ frequency: Double, start: Int = 12_000) -> Double {
            let window = Array(decoded[start..<(start+24_000)])
            var real = 0.0, imaginary = 0.0
            for (i,value) in window.enumerated() {
                let phase = 2*Double.pi*frequency*Double(i)/48_000
                real += Double(value)*cos(phase); imaginary += Double(value)*sin(phase)
            }
            return 2*sqrt(real*real+imaginary*imaginary)/Double(window.count)
        }
        let deviceTone = strength(direct && !systemMix ? 576 : 432), microphoneTone = strength(direct ? 1008 : 864)
        if staticScreen {
            precondition(strength(direct && !systemMix ? 576 : 432, start:168_000) > 0.05)
            precondition(strength(direct ? 1008 : 864, start:168_000) > 0.05,
                "Microphone must remain audible after more than two seconds without a video frame")
            let videoDuration = try await track.load(.timeRange).duration.seconds
            precondition(videoDuration > 5.5, "The static picture must last through the audio tail")
        }
        if systemMix {
            precondition(strength(576) > 0.05 && strength(576) < 0.25, "System speech must remain audible once alongside the soundtrack, without a duplicate direct voice")
        }
        if direct && !systemMix {
            precondition(strength(432) < 0.015 && strength(864) < 0.015, "ReplayKit duplicates must not be mixed twice")
            precondition(deviceTone < 0.25 && microphoneTone < 0.25, "Direct tracks must not be doubled")
        }
        precondition(deviceTone > 0.05 && microphoneTone > 0.05, "Both audio sources must be audible")
        let empty = BroadcastMovieWriter(url: root.appendingPathComponent("empty.mov"))
        let emptyResult = try await finish(empty).get()
        precondition(emptyResult == nil)
        let invalid = BroadcastMovieWriter(url: root.appendingPathComponent("missing/invalid.mov"))
        invalid.submit(landscape, orientation: .up, seconds: 100)
        try await Task.sleep(nanoseconds: 200_000_000)
        if case .success = await finish(invalid) { fatalError("Unwritable destination must fail") }
        let report: [String: Any] = ["passed": true, "decodedFrames": frames, "durationSeconds": duration,
            "width": size.width, "height": size.height, "orientationChange": true,
            "pauseGapRemoved": true, "duplicateFinish": true, "emptyRecording": true, "writeFailure": true,
            "audioTrackCount": audioTracks.count, "deviceToneAmplitude": deviceTone,
            "microphoneToneAmplitude": microphoneTone, "microphoneSampleRates": [16000,44100],
            "systemSpeechToneAmplitude": systemMix ? strength(576) : 0, "systemMix": systemMix, "staticScreen": staticScreen, "liveCrop": crop, "invalidCropRejected": crop, "preselectedCrop": preselected, "uncroppedIntroRejected": preselected, "deviceInputChannels": 2, "directAudio": direct, "duplicateSourcesSuppressed": direct,
            "scope": "Synthetic macOS writer check; not iPhone ReplayKit or Photos validation"]
        print(String(decoding: try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted,.sortedKeys]), as: UTF8.self))
    }
}
