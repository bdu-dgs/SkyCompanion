import XCTest
@testable import CaptureCore

final class MobileVoiceCommandTests: XCTestCase {
    func testLocalLifecycleCommandsAreWholeUtterances() {
        XCTAssertEqual(MobileVoiceCommand.parse("SkyCompanion, pause analysis."), .pause)
        XCTAssertEqual(MobileVoiceCommand.parse("SkyCompanion resume"), .resume)
        XCTAssertEqual(MobileVoiceCommand.parse("SkyCompanion end assistance"), .end)
        XCTAssertEqual(MobileVoiceCommand.parse("SkyCompanion stop listening"), .stop)
        XCTAssertEqual(MobileVoiceCommand.parse("SkyCompanion what's ahead?"), .describe)
        XCTAssertNil(MobileVoiceCommand.parse("I heard SkyCompanion resume in a video"))
        XCTAssertNil(MobileVoiceCommand.parse("SkyCompanion resume later please"))
        XCTAssertNil(MobileVoiceCommand.parse("resume"))
    }
    func testRecognitionSpellingVariantAndAllActions() {
        let examples: [(String, MobileVoiceCommand)] = [
            ("path", .path), ("path status", .path), ("repeat", .repeatAlert), ("mute", .mute), ("unmute", .unmute),
            ("describe", .describe), ("stop listening", .stop), ("why", .explain),
            ("got it", .acknowledge), ("quieter", .quiet), ("normal alerts", .normal),
            ("wrong alert", .reportFalseAlert), ("pause analysis", .pause),
            ("resume analysis", .resume), ("end session", .end)
        ]
        for (text, expected) in examples {
            XCTAssertEqual(MobileVoiceCommand.parse("SkyCompanion " + text), expected)
            XCTAssertEqual(MobileVoiceCommand.parse("Sky Companion " + text), expected)
            XCTAssertEqual(MobileVoiceCommand.parse("SKY COMPANION, " + text + "."), expected)
        }
    }
    func testUnrecognizedWakePhraseAndEmbeddedNameCannotActivateMobileCommands() {
        for text in ["OtherAssistant describe", "otherassistant mute", "OTHERASSISTANT pause analysis", "OtherAssistant resume", "OtherAssistant end assistance",
                     "OtherAssistant SkyCompanion repeat", "SkyCompanion OtherAssistant repeat", "Please SkyCompanion describe",
                     "Sky Companion", "SkyCompanion", "SkyCompanionship mute", "Sky describe"] {
            XCTAssertNil(MobileVoiceCommand.parse(text), text)
        }
        // The desktop grammar uses the same project wake phrase.
        XCTAssertEqual(VoiceCommand.parse("SkyCompanion describe"), .describe)
    }
}
