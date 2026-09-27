import XCTest
@testable import CaptureCore

final class CaptureCadenceTests: XCTestCase {
    func testJitteredThirtyFPSInputMaintainsFifteenFPS() {
        var cadence = CaptureCadence()
        let accepted = (0..<300).filter { index in
            let jitter = index == 0 ? 0 : (index % 2 == 0 ? -0.3 : 0.3)
            return cadence.take(at: Double(index) * 1_000 / 30 + jitter)
        }
        XCTAssertEqual(accepted.count, 150)
    }

    func testSlowEncodingSkipsSlotsWithoutCatchUpBurst() {
        var cadence = CaptureCadence()
        XCTAssertTrue(cadence.take(at: 0))
        XCTAssertTrue(cadence.take(at: 510))
        XCTAssertFalse(cadence.take(at: 511))
        XCTAssertFalse(cadence.take(at: 532))
        XCTAssertTrue(cadence.take(at: 534))
    }

    func testResetAllowsImmediateFrameAfterReconnect() {
        var cadence = CaptureCadence()
        XCTAssertTrue(cadence.take(at: 1_000))
        XCTAssertFalse(cadence.take(at: 1_010))
        cadence.reset()
        XCTAssertTrue(cadence.take(at: 1_011))
        XCTAssertFalse(cadence.take(at: .nan))
        XCTAssertFalse(cadence.take(at: .infinity))
    }
}
