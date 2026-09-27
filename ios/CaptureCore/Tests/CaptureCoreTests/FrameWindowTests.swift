import XCTest
@testable import CaptureCore

final class FrameWindowTests: XCTestCase {
    private func frame(_ id: Int, at time: Double = 1_000) -> CaptureFrame {
        CaptureFrame(id: id, capturedMS: time, width: 960, height: 540, orientation: 1, jpeg: Data([0]))
    }

    func testSlowReceiverRetainsOnlyNewestPendingFrame() {
        var window = FrameWindow()
        window.offer(frame(1))
        XCTAssertEqual(window.take(nowMS: 1_010)?.id, 1)
        for id in 2...100 { window.offer(frame(id)) }
        XCTAssertNil(window.take(nowMS: 1_100))
        XCTAssertEqual(window.pending?.id, 100)
        XCTAssertFalse(window.accept(frameID: 77))
        XCTAssertEqual(window.unacknowledgedID, 1)
        XCTAssertTrue(window.accept(frameID: 1))
        XCTAssertEqual(window.take(nowMS: 1_110)?.id, 100)
    }

    func testReceiptUsesCaptureTimeAndCannotBeReplayed() {
        var window = FrameWindow()
        window.offer(frame(1))
        _ = window.take(nowMS: 1_100)
        XCTAssertEqual(window.displayLatency(frameID: 1, nowMS: 1_450), 450)
        XCTAssertNil(window.displayLatency(frameID: 1, nowMS: 1_500))
        XCTAssertNil(window.displayLatency(frameID: 999, nowMS: 1_500))
    }

    func testDisconnectDropsFramesAndPreviousSessionReceipts() {
        var window = FrameWindow()
        window.offer(frame(1))
        _ = window.take(nowMS: 1_000)
        window.offer(frame(2))
        window.clear()
        XCTAssertNil(window.pending)
        XCTAssertNil(window.unacknowledgedID)
        XCTAssertNil(window.displayLatency(frameID: 1, nowMS: 1_200))
        XCTAssertNil(window.take(nowMS: 1_200))
    }

    func testStalePendingIsNotReplayedAndTimeoutIsBounded() {
        var window = FrameWindow()
        window.offer(frame(1))
        XCTAssertNil(window.take(nowMS: 4_000))
        XCTAssertNil(window.pending)
        window.offer(frame(2, at: 4_000))
        _ = window.take(nowMS: 4_100)
        XCTAssertFalse(window.acknowledgementExpired(nowMS: 6_500))
        XCTAssertTrue(window.acknowledgementExpired(nowMS: 6_601))
    }

    func testReceiptHistoryHasHardLimitAndRejectsNegativeLatency() {
        var window = FrameWindow(receiptLimit: 2)
        for id in 1...3 {
            window.offer(frame(id))
            _ = window.take(nowMS: 1_100)
            window.accept(frameID: id)
        }
        XCTAssertNil(window.displayLatency(frameID: 1, nowMS: 1_500))
        XCTAssertNil(window.displayLatency(frameID: 2, nowMS: 900))
        XCTAssertEqual(window.displayLatency(frameID: 3, nowMS: 1_500), 500)
    }

    func testPauseDiscardsImagesButRetainsNetworkWindowUntilAcknowledged() {
        var window = FrameWindow()
        window.offer(frame(1))
        _ = window.take(nowMS: 1_010)
        window.offer(frame(2))
        window.discardPendingAndReceipts()
        XCTAssertNil(window.pending)
        XCTAssertNil(window.displayLatency(frameID: 1, nowMS: 1_200))
        window.offer(frame(3))
        XCTAssertNil(window.take(nowMS: 1_250))
        XCTAssertTrue(window.accept(frameID: 1))
        XCTAssertEqual(window.take(nowMS: 1_260)?.id, 3)
    }
}
