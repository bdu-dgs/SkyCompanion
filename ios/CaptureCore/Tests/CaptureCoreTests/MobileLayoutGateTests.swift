import XCTest
@testable import CaptureCore

final class MobileLayoutGateTests: XCTestCase {
    func testPortraitDJIViewIsAcceptedAfterSettling() {
        var gate = MobileLayoutGate()
        XCTAssertEqual(gate.evaluate(width: 400, height: 800, orientation: 1, capturedMS: 0), .waiting)
        XCTAssertEqual(gate.evaluate(width: 400, height: 800, orientation: 1, capturedMS: 499), .waiting)
        XCTAssertEqual(gate.evaluate(width: 400, height: 800, orientation: 1, capturedMS: 500), .accept)
        XCTAssertEqual(gate.evaluate(width: 400, height: 800, orientation: 1, capturedMS: 700), .accept)
    }

    func testStartupRotationMustSettleAgain() {
        var gate = MobileLayoutGate()
        _ = gate.evaluate(width: 400, height: 800, orientation: 1, capturedMS: 0)
        XCTAssertEqual(gate.evaluate(width: 800, height: 400, orientation: 6, capturedMS: 400), .waiting)
        XCTAssertEqual(gate.evaluate(width: 800, height: 400, orientation: 6, capturedMS: 600), .waiting)
        XCTAssertEqual(gate.evaluate(width: 800, height: 400, orientation: 6, capturedMS: 900), .accept)
    }

    func testLayoutChangesAfterAcceptanceRequireReconfirmation() {
        var gate = MobileLayoutGate()
        _ = gate.evaluate(width: 800, height: 400, orientation: 6, capturedMS: 0)
        _ = gate.evaluate(width: 800, height: 400, orientation: 6, capturedMS: 500)
        XCTAssertEqual(gate.evaluate(width: 400, height: 800, orientation: 1, capturedMS: 600), .changed)
        XCTAssertEqual(gate.evaluate(width: 800, height: 400, orientation: 8, capturedMS: 700), .changed)
        XCTAssertEqual(gate.evaluate(width: 900, height: 400, orientation: 6, capturedMS: 800), .changed)
    }

    func testNewSessionDropsPreviousLayout() {
        var gate = MobileLayoutGate()
        _ = gate.evaluate(width: 400, height: 800, orientation: 1, capturedMS: 0)
        _ = gate.evaluate(width: 400, height: 800, orientation: 1, capturedMS: 500)
        gate = MobileLayoutGate()
        XCTAssertEqual(gate.evaluate(width: 800, height: 400, orientation: 6, capturedMS: 1_000), .waiting)
        XCTAssertEqual(gate.evaluate(width: 800, height: 400, orientation: 6, capturedMS: 1_500), .accept)
    }
}
