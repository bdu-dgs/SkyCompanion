import XCTest
@testable import CaptureCore

final class MobileSpeechInputTests: XCTestCase {
    func segment(_ text: String, _ time: Double, _ duration: Double = 0.2) -> MobileSpeechSegment {
        .init(text: text, timestamp: time, duration: duration)
    }
    func testNewWakeUtteranceAfterEarlierAmbientSpeech() {
        let words = [segment("hello",0),segment("there",0.3),segment("Sky",2),segment("Companion",2.3),segment("describe",2.7)]
        let start = MobileSpeechInput.utteranceStart(in: words)
        XCTAssertEqual(start,2)
        XCTAssertEqual(MobileVoiceCommand.parse(words[start...].map(\.text).joined(separator:" ")),.describe)
    }
    func testEmbeddedOrUntimedWordsDoNotBecomeCommands() {
        let embedded = [segment("Say",0),segment("SkyCompanion",0.3),segment("describe",0.6)]
        XCTAssertEqual(MobileSpeechInput.utteranceStart(in:embedded),0)
        XCTAssertNil(MobileVoiceCommand.parse(embedded.map(\.text).joined(separator:" ")))
        XCTAssertEqual(MobileSpeechInput.utteranceStart(in:[segment("hello",0,0),segment("SkyCompanion",2,0),segment("describe",0,0)]),0)
        XCTAssertEqual(MobileSpeechInput.utteranceStart(in:[segment("noise",0),segment("SkyCompanionship",2)]),0)
    }
    func testLatestSeparateWakeWinsWithoutSplittingPauseInsideCommand() {
        let words = [segment("SkyCompanion",0),segment("status",0.3),segment("SkyCompanion",3),segment("describe",5)]
        XCTAssertEqual(MobileSpeechInput.utteranceStart(in:words),2)
        XCTAssertEqual(MobileSpeechInput.utteranceStart(in:[segment("Sky",0),segment("Companion",2),segment("describe",2.3)]),0)
    }
    func testDuplicatePartialsKeepFirstCommitAndFinalCanExpedite() {
        var gate = MobileCommandDebounce()
        XCTAssertTrue(gate.shouldSchedule(key:"describe",isFinal:false))
        for _ in 0..<20 { XCTAssertFalse(gate.shouldSchedule(key:"describe",isFinal:false)) }
        XCTAssertTrue(gate.shouldSchedule(key:"describe",isFinal:true))
        XCTAssertFalse(gate.shouldSchedule(key:"describe",isFinal:true))
    }
    func testContinuationCancelsAndNewCommandCanSchedule() {
        var gate = MobileCommandDebounce()
        XCTAssertTrue(gate.shouldSchedule(key:"describe",isFinal:false))
        XCTAssertFalse(gate.shouldSchedule(key:nil,isFinal:false))
        XCTAssertTrue(gate.shouldSchedule(key:"status",isFinal:false))
        XCTAssertTrue(gate.shouldSchedule(key:"navigation:SkyCompanion navigate to Main",isFinal:false))
        XCTAssertTrue(gate.shouldSchedule(key:"navigation:SkyCompanion navigate to Main Street",isFinal:false))
    }
}
