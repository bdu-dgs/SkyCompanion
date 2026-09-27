import XCTest
@testable import CaptureCore

final class NavigationVoiceCommandTests: XCTestCase {
    func testDestinationRetainsAddressAndPlaceSpelling() {
        XCTAssertEqual(NavigationVoiceCommand.parse("Sky Companion, take me to St. Mary's Hospital."),
                       .destination("St. Mary's Hospital"))
        XCTAssertEqual(NavigationVoiceCommand.parse("SKYCOMPANION navigate to 123 North Lake-Shore Drive, Chicago"),
                       .destination("123 North Lake-Shore Drive, Chicago"))
        XCTAssertEqual(NavigationVoiceCommand.parse("SkyCompanion directions to O’Hare Terminal 3!"),
                       .destination("O’Hare Terminal 3"))
        XCTAssertEqual(NavigationVoiceCommand.parse("SkyCompanion navigate to Central Library on Main Street"),
                       .destination("Central Library on Main Street"))
    }

    func testWakePhraseAndNonEmptyDestinationAreRequired() {
        for text in ["navigate to the library", "OtherAssistant navigate to the library",
                     "I heard SkyCompanion navigate to home", "SkyCompanionship navigate to home",
                     "SkyCompanion navigate to", "Sky Companion take me to ...",
                     "SkyCompanion directions to !?", "SkyCompanionnavigate to home"] {
            XCTAssertNil(NavigationVoiceCommand.parse(text), text)
        }
    }

    func testCancellationAndSelectionAreWholeUtterances() {
        XCTAssertEqual(NavigationVoiceCommand.parse("SkyCompanion stop navigation"), .cancel)
        XCTAssertEqual(NavigationVoiceCommand.parse("Sky Companion, cancel navigation!"), .cancel)
        XCTAssertEqual(NavigationVoiceCommand.parse("SkyCompanion navigation status"), .status)
        XCTAssertEqual(NavigationVoiceCommand.parse("SkyCompanion option one"), .select(1))
        XCTAssertEqual(NavigationVoiceCommand.parse("SkyCompanion choose two"), .select(2))
        XCTAssertEqual(NavigationVoiceCommand.parse("SkyCompanion choose option 3"), .select(3))
        XCTAssertEqual(NavigationVoiceCommand.parse("SkyCompanion select option three"), .select(3))
        for text in ["SkyCompanion cancel navigation later", "SkyCompanion option one or two",
                     "SkyCompanion choose four", "option one", "SkyCompanion stop listening",
                     "SkyCompanion status", "SkyCompanion resume"] {
            XCTAssertNil(NavigationVoiceCommand.parse(text), text)
        }
    }
}
