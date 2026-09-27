import XCTest
@testable import CaptureCore

final class PhotonProtocolTests: XCTestCase {
    private func record(_ id: String, kind: String = "alert") -> PhotonRecord {
        PhotonRecord(id: id, kind: kind, sessionID: "trip", atMS: 1_000)
    }
    func testAtomicBatchRetryKeepsIDsAndOrderUntilExactAcknowledgment() throws {
        var queue = PhotonOutbox()
        queue.append(record("start", kind: "start")); queue.append(record("alert")); queue.append(record("end", kind: "end"))
        let sent = queue.batch(limit: 2)
        XCTAssertFalse(queue.acknowledge(sent, accepted: 1, duplicates: 0))
        XCTAssertEqual(queue.batch(limit: 2), sent)
        XCTAssertFalse(queue.acknowledge(Array(sent.reversed()), accepted: 2, duplicates: 0))
        XCTAssertFalse(queue.acknowledge(sent, accepted: -1, duplicates: 3))
        XCTAssertFalse(queue.acknowledge(sent, accepted: Int.max, duplicates: Int.max))
        // A response lost in transit can be retried with the original stable IDs.
        let restored = try JSONDecoder().decode(PhotonOutbox.self, from: JSONEncoder().encode(queue))
        XCTAssertEqual(restored.batch(limit: 2), sent)
        XCTAssertTrue(queue.acknowledge(sent, accepted: 0, duplicates: 2))
        XCTAssertEqual(queue.records.map(\.kind), ["end"])
    }
    func testNewRecordsAddedDuringRequestAreNotAcknowledgedByThatResponse() {
        var queue = PhotonOutbox(); queue.append(record("a"))
        let sent = queue.batch(); queue.append(record("b"))
        XCTAssertTrue(queue.acknowledge(sent, accepted: 1, duplicates: 0))
        XCTAssertEqual(queue.records.map(\.id), ["b"])
    }
    func testBoundedQueueReservesTripEndAndRejectsWithoutDroppingOlderData() {
        var queue = PhotonOutbox()
        for index in 0..<999 { XCTAssertTrue(queue.append(record("\(index)"))) }
        XCTAssertFalse(queue.append(record("overflow")))
        XCTAssertTrue(queue.append(record("end", kind: "end")))
        XCTAssertFalse(queue.append(record("second-end", kind: "end")))
        XCTAssertEqual(queue.records.count, 1_000)
        XCTAssertEqual(queue.records.first?.id, "0")
        XCTAssertTrue(queue.append(record("0")))
        XCTAssertEqual(queue.records.count, 1_000)
        XCTAssertEqual(queue.batch().count, 50)
    }
    func testRestartRecoveryClosesAfterOldAlertsAndDoesNotInventCompletion() throws {
        var queue = PhotonOutbox()
        queue.append(record("start", kind: "start")); queue.append(record("alert"))
        let restored = try JSONDecoder().decode(PhotonOutbox.self, from: JSONEncoder().encode(queue))
        queue = restored
        XCTAssertTrue(queue.reconcileInterruptedTrip(sessionID: "trip", atMS: 2_000))
        XCTAssertEqual(queue.records.map(\.kind), ["start", "alert", "end"])
        XCTAssertTrue(queue.records.last?.reason?.contains("interrupted") == true)
        XCTAssertTrue(queue.records.last?.reason?.contains("incomplete") == true)
        let snapshot = queue.records
        XCTAssertTrue(queue.reconcileInterruptedTrip(sessionID: "trip", atMS: 3_000))
        XCTAssertEqual(queue.records, snapshot, "Repeated recovery keeps the original stable end record")
    }
    func testHTTPSOriginValidationPreventsCredentialURLsAndProductionPlaintext() {
        XCTAssertNotNil(PhotonPolicy.endpoint("https://companion.example", allowLocalHTTP: false))
        XCTAssertNotNil(PhotonPolicy.endpoint("http://localhost:8787", allowLocalHTTP: true))
        for candidate in ["http://localhost:8787", "http://192.168.1.1", "https://user:secret@example.com", "https://example.com/path", "https://example.com?token=x", "https://example.com#x", "file:///tmp/server"] {
            XCTAssertNil(PhotonPolicy.endpoint(candidate, allowLocalHTTP: false), candidate)
        }
        XCTAssertNil(PhotonPolicy.endpoint("http://192.168.1.1", allowLocalHTTP: true))
    }
    func testInboxCursorCannotSkipUnseenMessagesOrMoveBackwards() throws {
        let good = try inbox(cursor: 12, sequences: [11, 12])
        XCTAssertTrue(PhotonPolicy.validInbox(good, after: 10))
        XCTAssertFalse(PhotonPolicy.validInbox(try inbox(cursor: 13, sequences: [11, 12]), after: 10))
        XCTAssertFalse(PhotonPolicy.validInbox(try inbox(cursor: 12, sequences: [12, 11]), after: 10))
        XCTAssertFalse(PhotonPolicy.validInbox(try inbox(cursor: 9, sequences: []), after: 10))
        XCTAssertTrue(PhotonPolicy.validInbox(try inbox(cursor: 10, sequences: []), after: 10))
    }
    func testOldOtherTripAndFutureMessagesAreNeverAutomaticallyAnnounced() {
        let message = PhotonMessage(id: "m", sequence: 1, sessionID: "trip", kind: "answer", text: "answer", createdAtMS: 100_000)
        XCTAssertTrue(message.shouldAnnounce(sessionID: "trip", connectedAtMS: 90_000, nowMS: 110_000))
        XCTAssertFalse(message.shouldAnnounce(sessionID: "trip", connectedAtMS: 100_001, nowMS: 110_000))
        XCTAssertFalse(message.shouldAnnounce(sessionID: "other", connectedAtMS: 90_000, nowMS: 110_000))
        XCTAssertFalse(message.shouldAnnounce(sessionID: "trip", connectedAtMS: 90_000, nowMS: 160_001))
        XCTAssertFalse(message.shouldAnnounce(sessionID: "trip", connectedAtMS: 90_000, nowMS: 99_999))
    }
    func testTextAndIdentifiersRespectServerWireLimits() {
        XCTAssertEqual(PhotonPolicy.boundedText("  hi\u{0}\u{1} there  ", limit: 100), "hi there")
        XCTAssertEqual(PhotonPolicy.boundedText("😀😀x", limit: 3), "😀")
        XCTAssertEqual(PhotonPolicy.boundedText(String(repeating: "😀", count: 1_000), limit: 1_000).utf16.count, 1_000)
        XCTAssertTrue(PhotonPolicy.validIdentifier("start-trip_1.2:3"))
        for invalid in ["", "trip 1", "trip/1", String(UnicodeScalar(0xE9)!), String(repeating: "a", count: 161)] {
            XCTAssertFalse(PhotonPolicy.validIdentifier(invalid))
        }
    }
    func testWireKeysAreSnakeCaseAndUnrelatedFieldsAreOmitted() throws {
        var alert = record("a"); alert.eventID = "event"; alert.observedAtMS = 900; alert.speechStatus = "started"
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(alert)) as? [String: Any])
        XCTAssertEqual(json["session_id"] as? String, "trip")
        XCTAssertEqual(json["speech_status"] as? String, "started")
        XCTAssertEqual(json["observed_at_ms"] as? Int, 900)
        XCTAssertNil(json["sessionID"]); XCTAssertNil(json["question"])
    }
    private func inbox(cursor: Int, sequences: [Int]) throws -> PhotonInboxResponse {
        let messages = sequences.map { ["id": "m\($0)", "sequence": $0, "session_id": "trip", "kind": "answer", "text": "answer", "created_at_ms": 1_000] as [String: Any] }
        let data = try JSONSerialization.data(withJSONObject: ["messages": messages, "cursor": cursor, "agent_name": "SkyCompanion Assistant"])
        return try JSONDecoder().decode(PhotonInboxResponse.self, from: data)
    }
}
