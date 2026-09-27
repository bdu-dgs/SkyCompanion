import XCTest
@testable import CaptureCore

final class CompanionSpeechTests: XCTestCase {
    func testCompanionSummaryStaysEnglishWithChineseCommandLocale() {
        var trip = CompanionTrip(id: "english-assistant", recordedVideo: true, chinese: true)
        trip.record(eventID: "alert-1", category: "pole")
        let summary = trip.finish()!
        XCTAssertTrue(summary.hasPrefix("Recorded video test ended."))
        XCTAssertTrue(summary.contains("1 obstacle reminders: pole 1"))
    }
    func testExplicitCompanionAndCorrectionCommands() {
        XCTAssertEqual(MobileVoiceCommand.parse("SkyCompanion trip summary"), .agentSummary)
        XCTAssertEqual(MobileVoiceCommand.parse("SkyCompanion ask assistant why"), .agentWhy)
        XCTAssertEqual(MobileVoiceCommand.parse("Sky Companion wrong alert"), .reportFalseAlert)
        XCTAssertEqual(MobileVoiceCommand.parse("Sky Companion trip summary"), .agentSummary)
        XCTAssertNil(MobileVoiceCommand.parse("Tell someone about a trip summary"))
    }
    func testCompanionWaitsForObstacleSpeechAndCommand() {
        var queue = CompanionSpeechQueue()
        queue.enqueue(id: "a", text: "Trip summary", nowMS: 100)
        XCTAssertNil(queue.next(nowMS: 200, speechBusy: true, protectingCommand: false, obstacleActive: false, canSpeak: true))
        XCTAssertNil(queue.next(nowMS: 200, speechBusy: false, protectingCommand: true, obstacleActive: false, canSpeak: true))
        XCTAssertNil(queue.next(nowMS: 200, speechBusy: false, protectingCommand: false, obstacleActive: true, canSpeak: true))
        XCTAssertNil(queue.next(nowMS: 200, speechBusy: false, protectingCommand: false, obstacleActive: false, canSpeak: false))
        XCTAssertEqual(queue.next(nowMS: 200, speechBusy: false, protectingCommand: false, obstacleActive: false, canSpeak: true)?.id, "a")
        // Real risk uses positive priority, companion uses -1 and never protects a command.
        for risk in 1...3 {
            XCTAssertTrue(MobileGuidanceGate.mayStartSpeech(incoming: risk, current: -1))
            XCTAssertFalse(MobileGuidanceGate.mayStartSpeech(incoming: -1, current: risk))
        }
    }

    func testExpiredAndDuplicateRepliesDoNotPlay() {
        var queue = CompanionSpeechQueue()
        queue.enqueue(id: "a", text: "History", nowMS: 0)
        queue.enqueue(id: "a", text: "Duplicate", nowMS: 5)
        XCTAssertEqual(queue.items.count, 1)
        XCTAssertNil(queue.next(nowMS: 60_000, speechBusy: false, protectingCommand: false, obstacleActive: false, canSpeak: true))
        for index in 0..<20 { queue.enqueue(id: "m\(index)", text: "Message", nowMS: 70_000) }
        XCTAssertEqual(queue.items.count, 8)
    }

    func testTripEndIsIdempotentAndCountsReminders() {
        var trip = CompanionTrip(id: "walk", recordedVideo: false, chinese: false)
        trip.record(eventID: "a", category: "person")
        trip.record(eventID: "a", category: "person")
        trip.record(eventID: "b", category: "person")
        XCTAssertEqual(trip.counts["person"], 2)
        XCTAssertTrue(trip.finish()!.contains("2 obstacle reminders"))
        XCTAssertNil(trip.finish())
        trip.record(eventID: "c", category: "car")
        XCTAssertNil(trip.counts["car"])
    }

    func testEmptyRecordedTripDoesNotClaimSafety() {
        var trip = CompanionTrip(id: "test", recordedVideo: true, chinese: false)
        let summary = trip.finish()!
        XCTAssertTrue(summary.hasPrefix("Recorded video test"))
        XCTAssertTrue(summary.contains("does not mean there were no obstacles"))
    }
}
