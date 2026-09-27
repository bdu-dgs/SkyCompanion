import Foundation

/// Bounded mono signed little-endian PCM. Host time is shared by AVAudioEngine
/// and ReplayKit on this phone; no wall-clock or network clock is involved.
struct LocalRecordingAudio: Codable {
    enum Source: String, Codable { case microphone, speech }
    var recordingID: String
    var source: Source
    var hostSeconds: Double
    var sampleRate: Double
    var pcm: Data
    var valid: Bool {
        hostSeconds.isFinite && hostSeconds >= 0 && hostSeconds < 1_000_000_000 && sampleRate.isFinite &&
        (8_000...96_000).contains(sampleRate) && sampleRate.rounded() == sampleRate && !pcm.isEmpty && pcm.count % 2 == 0 &&
        pcm.count <= 32_768 && Double(pcm.count/2)/sampleRate <= 0.25
    }
}
