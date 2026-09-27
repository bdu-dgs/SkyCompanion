import Foundation

/// Companion messages never become navigation instructions or protected command speech.
public struct CompanionSpeechQueue: Sendable {
    public struct Item: Equatable, Sendable {
        public let id: String
        public let text: String
        public let expiresMS: Double
    }
    public private(set) var items: [Item] = []
    private var seen: [String] = []
    public init() {}

    public mutating func enqueue(id: String, text: String, nowMS: Double) {
        guard nowMS.isFinite, !id.isEmpty, !text.isEmpty, text.count <= 2_000,
              !seen.contains(id) else { return }
        seen.append(id)
        if seen.count > 128 { seen.removeFirst(seen.count - 128) }
        items.removeAll { $0.expiresMS <= nowMS }
        if items.count >= 8 { items.removeFirst() }
        items.append(Item(id: id, text: text, expiresMS: nowMS + 60_000))
    }

    public mutating func next(nowMS: Double, speechBusy: Bool, protectingCommand: Bool,
                              obstacleActive: Bool, canSpeak: Bool) -> Item? {
        guard nowMS.isFinite else { return nil }
        items.removeAll { $0.expiresMS <= nowMS }
        guard canSpeak, !speechBusy, !protectingCommand, !obstacleActive, !items.isEmpty else { return nil }
        return items.removeFirst()
    }

    public mutating func clear() { items.removeAll() }
}

/// Counts start-of-speech callbacks, not detected objects, requests to speak, or hearing.
public struct CompanionTrip: Sendable {
    public let id: String
    public let recordedVideo: Bool
    public let chinese: Bool
    public private(set) var counts: [String: Int] = [:]
    public private(set) var ended = false
    private var eventIDs: Set<String> = []
    public init(id: String, recordedVideo: Bool, chinese: Bool) {
        self.id = id; self.recordedVideo = recordedVideo; self.chinese = chinese
    }
    public mutating func record(eventID: String, category: String) {
        guard !ended, !eventID.isEmpty, !eventIDs.contains(eventID) else { return }
        // Retain at most 10,000 IDs per trip; bound unusually long or corrupt input.
        guard eventIDs.count < 10_000 else { return }
        eventIDs.insert(eventID)
        let label = category.trimmingCharacters(in: .whitespacesAndNewlines)
        counts[label.isEmpty ? "obstacle" : String(label.prefix(64)), default: 0] += 1
    }
    public mutating func finish() -> String? {
        guard !ended else { return nil }
        ended = true
        let total = counts.values.reduce(0, +)
        let source = recordedVideo ? "Recorded video test ended. " : "Trip ended. "
        if total == 0 {
            return source + "No spoken obstacle reminders were recorded. This does not mean there were no obstacles."
        }
        let top = counts.sorted { $0.value == $1.value ? $0.key < $1.key : $0.value > $1.value }.prefix(3)
        let detail = top.map { "\($0.key) \($0.value)" }.joined(separator: ", ")
        return source + "\(total) obstacle reminders: \(detail). These are reminders, not distinct objects."
    }
}
