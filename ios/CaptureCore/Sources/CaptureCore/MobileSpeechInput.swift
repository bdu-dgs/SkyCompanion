import Foundation

/// Word timing from the local speech recognizer, not stored microphone audio.
public struct MobileSpeechSegment: Sendable {
    public let text: String
    public let timestamp: Double
    public let duration: Double
    public init(text: String, timestamp: Double, duration: Double) {
        self.text = text; self.timestamp = timestamp; self.duration = duration
    }
}

public enum MobileSpeechInput {
    public static func startsWakePhrase(_ text: String) -> Bool {
        let words = text.lowercased().components(separatedBy: CharacterSet.alphanumerics.inverted).filter { !$0.isEmpty }
        return words.first == "skycompanion" || words.first == "sky"
    }

    /// A recognition task can contain earlier conversation. Only split at a
    /// measured pause followed by the wake phrase; never search arbitrary text
    /// for embedded commands. Missing partial-result timing keeps strict parsing.
    public static func utteranceStart(in segments: [MobileSpeechSegment]) -> Int {
        guard segments.count > 1 else { return 0 }
        for index in stride(from: segments.count - 1, through: 1, by: -1) {
            let previous = segments[index - 1], current = segments[index]
            guard previous.timestamp.isFinite, previous.duration.isFinite,
                  current.timestamp.isFinite, previous.timestamp >= 0, previous.duration > 0,
                  current.timestamp - previous.timestamp - previous.duration >= 0.8 else { continue }
            if startsWakePhrase(current.text) { return index }
        }
        return 0
    }
}

/// Repeated identical partial results must not postpone the same command forever.
public struct MobileCommandDebounce: Sendable {
    private var key: String?
    private var final = false
    public init() {}
    public mutating func shouldSchedule(key next: String?, isFinal: Bool) -> Bool {
        guard let next else { key = nil; final = false; return false }
        guard key != next || (isFinal && !final) else { return false }
        key = next; final = isFinal
        return true
    }
}
