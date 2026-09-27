import Foundation

/// Metadata only. No images, raw audio, or walking permission are sent to the companion.
public struct PhotonRecord: Codable, Equatable, Sendable, Identifiable {
    public var id: String
    public var kind: String
    public var sessionID: String
    public var atMS: Int64
    public var source: String?
    public var locale: String?
    public var frameID: UInt64?
    public var eventID: String?
    public var category: String?
    public var direction: String?
    public var text: String?
    public var evidence: [String]?
    public var observedAtMS: Int64?
    public var speechStatus: String?
    public var reason: String?
    public var note: String?
    public var question: String?

    public init(id: String = UUID().uuidString, kind: String, sessionID: String, atMS: Int64) {
        self.id = id; self.kind = kind; self.sessionID = sessionID; self.atMS = atMS
    }
    enum CodingKeys: String, CodingKey {
        case id, kind, source, locale, category, direction, text, evidence, reason, note, question
        case sessionID = "session_id", atMS = "at_ms", frameID = "frame_id", eventID = "event_id"
        case observedAtMS = "observed_at_ms", speechStatus = "speech_status"
    }
}

public struct PhotonMessage: Codable, Equatable, Identifiable, Sendable {
    public let id: String
    public let sequence: Int64
    public let sessionID: String
    public let kind: String
    public let text: String
    public let createdAtMS: Int64
    public init(id: String, sequence: Int64, sessionID: String, kind: String, text: String, createdAtMS: Int64) {
        self.id = id; self.sequence = sequence; self.sessionID = sessionID
        self.kind = kind; self.text = text; self.createdAtMS = createdAtMS
    }
    enum CodingKeys: String, CodingKey {
        case id, sequence, kind, text
        case sessionID = "session_id", createdAtMS = "created_at_ms"
    }
    public func shouldAnnounce(sessionID: String?, connectedAtMS: Int64, nowMS: Int64) -> Bool {
        self.sessionID == sessionID && createdAtMS >= connectedAtMS && createdAtMS <= nowMS
            && nowMS - createdAtMS <= 60_000
    }
}

public struct PhotonSyncResponse: Decodable, Sendable {
    public let accepted: Int
    public let duplicates: Int
}
public struct PhotonInboxResponse: Decodable, Sendable {
    public let messages: [PhotonMessage]
    public let cursor: Int64
    public let agentName: String
    enum CodingKeys: String, CodingKey { case messages, cursor; case agentName = "agent_name" }
}

/// The server commits an entire batch atomically. A failed/malformed response removes nothing.
public struct PhotonOutbox: Codable, Equatable, Sendable {
    public static let capacity = 1_000
    public private(set) var records: [PhotonRecord] = []
    public init() {}
    @discardableResult public mutating func append(_ record: PhotonRecord) -> Bool {
        if records.contains(where: { $0.id == record.id }) { return true }
        // Reserve one slot for end so a full alert queue can still close a trip.
        let limit = record.kind == "end" ? Self.capacity : Self.capacity - 1
        guard records.count < limit else { return false }
        records.append(record); return true
    }
    /// Stable end IDs make recovery safe if termination happened after server acceptance.
    @discardableResult public mutating func reconcileInterruptedTrip(sessionID: String, atMS: Int64) -> Bool {
        var end = PhotonRecord(id: "end-\(sessionID)", kind: "end", sessionID: sessionID, atMS: atMS)
        end.reason = "App restarted before the trip closed. This trip was interrupted; its obstacle log may be incomplete."
        return append(end)
    }
    public func batch(limit: Int = 50) -> [PhotonRecord] { Array(records.prefix(max(0, min(50, limit)))) }
    @discardableResult public mutating func acknowledge(_ batch: [PhotonRecord], accepted: Int, duplicates: Int) -> Bool {
        guard !batch.isEmpty, accepted >= 0, duplicates >= 0,
              accepted <= batch.count, duplicates == batch.count - accepted,
              Array(records.prefix(batch.count)) == batch else { return false }
        records.removeFirst(batch.count); return true
    }
}

public enum PhotonPolicy {
    /// Server limits are JavaScript UTF-16 code units, not Swift grapheme counts.
    public static func boundedText(_ value: String, limit: Int) -> String {
        var result = String.UnicodeScalarView(), units = 0
        for scalar in value.unicodeScalars {
            if scalar.value <= 8 || scalar.value == 11 || scalar.value == 12 || (14...31).contains(scalar.value) { continue }
            let width = scalar.value > 0xFFFF ? 2 : 1
            guard units + width <= limit else { break }
            result.append(scalar); units += width
        }
        return String(result).trimmingCharacters(in: .whitespacesAndNewlines)
    }
    public static func validIdentifier(_ value: String) -> Bool {
        !value.isEmpty && value.utf8.count <= 160 && value.utf8.allSatisfy {
            (65...90).contains($0) || (97...122).contains($0) || (48...57).contains($0)
                || [45, 46, 58, 95].contains($0)
        }
    }
    public static func endpoint(_ value: String, allowLocalHTTP: Bool) -> URL? {
        guard var parts = URLComponents(string: value.trimmingCharacters(in: .whitespacesAndNewlines)),
              let host = parts.host?.lowercased(), !host.isEmpty,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/" else { return nil }
        let local = ["localhost", "127.0.0.1", "[::1]", "::1"].contains(host)
        guard parts.scheme == "https" || (allowLocalHTTP && local && parts.scheme == "http") else { return nil }
        parts.path = ""; return parts.url
    }
    /// Reject skipped/backwards cursors and unordered/oversized responses before persistence.
    public static func validInbox(_ response: PhotonInboxResponse, after: Int64) -> Bool {
        guard response.cursor >= after, response.messages.count <= 200,
              !response.agentName.isEmpty, response.agentName.count <= 120 else { return false }
        var sequence = after
        var ids = Set<String>()
        for message in response.messages {
            guard message.sequence > sequence, message.sequence <= response.cursor,
                  !message.id.isEmpty, message.id.count <= 200,
                  !message.sessionID.isEmpty, message.sessionID.count <= 200,
                  ["summary", "answer", "feedback"].contains(message.kind),
                  !message.text.isEmpty, message.text.count <= 8_000,
                  message.createdAtMS > 0, ids.insert(message.id).inserted else { return false }
            sequence = message.sequence
        }
        return response.cursor == sequence
    }
}
