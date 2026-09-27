import XCTest
@testable import CaptureCore

final class NavigationProgressTests: XCTestCase {
    func route() -> NavigationProgress {
        NavigationProgress(points: [.init(x: 0, y: 0), .init(x: 100, y: 0), .init(x: 100, y: 100)],
                           maneuvers: [.init(distance: 100, kind: .left)])
    }
    func update(_ tracker: inout NavigationProgress, x: Double, y: Double = 0, time: Double,
                accuracy: Double = 5, now: Double? = nil) -> NavigationProgressUpdate {
        tracker.update(point: .init(x: x, y: y), accuracy: accuracy, timestamp: time, now: now ?? time)
    }
    func testAdvanceThenImmediateEachOnce() {
        var tracker = route()
        XCTAssertNil(update(&tracker, x: 30, time: 0).prompt)
        let advance = update(&tracker, x: 65, time: 15).prompt!
        XCTAssertEqual(advance.text, "About to turn left.")
        tracker.acknowledge(advance)
        XCTAssertNil(update(&tracker, x: 72, time: 20).prompt)
        let turn = update(&tracker, x: 90, time: 30).prompt!
        XCTAssertEqual(turn.text, "Turn left.")
        tracker.acknowledge(turn)
        XCTAssertNil(update(&tracker, x: 97, time: 35).prompt)
    }
    func testAlertRejectedPromptNeverReplaysAfterPassingTurn() {
        var tracker = route()
        _ = update(&tracker, x: 40, time: 0)
        XCTAssertNotNil(update(&tracker, x: 90, time: 20).prompt)
        // No acknowledgment: a high-priority alert occupied speech.
        XCTAssertNil(update(&tracker, x: 100, y: 15, time: 30).prompt)
    }
    func testRejectedAdvanceMayRetryOnlyWithFreshNewFix() {
        var tracker = route()
        _ = update(&tracker, x: 30, time: 0)
        XCTAssertNotNil(update(&tracker, x: 65, time: 20).prompt)
        XCTAssertNil(update(&tracker, x: 66, time: 20).prompt)
        XCTAssertNotNil(update(&tracker, x: 67, time: 21).prompt)
    }
    func testBadAccuracyStaleFutureAndDuplicateLocationsCannotSteer() {
        var tracker = route()
        XCTAssertFalse(update(&tracker, x: 50, time: 0, accuracy: 100).usable)
        XCTAssertFalse(update(&tracker, x: 50, time: 0, now: 10).usable)
        XCTAssertFalse(update(&tracker, x: 50, time: 20, now: 0).usable)
        XCTAssertFalse(update(&tracker, x: 50, time: 0, accuracy: -1).usable)
        XCTAssertTrue(update(&tracker, x: 50, time: 1).usable)
        XCTAssertFalse(update(&tracker, x: 55, time: 1).usable)
        XCTAssertNil(update(&tracker, x: 65, time: 10, accuracy: 18).prompt)
        XCTAssertEqual(tracker.traveled, 65, accuracy: 0.1)
    }
    func testOffRouteRequiresPersistentEvidenceAndBlocksSpeech() {
        var tracker = route()
        _ = update(&tracker, x: 30, time: 0)
        let first = update(&tracker, x: 60, y: -50, time: 10)
        XCTAssertTrue(first.offRoute); XCTAssertFalse(first.shouldReroute); XCTAssertNil(first.prompt)
        XCTAssertFalse(update(&tracker, x: 60, y: -50, time: 15).shouldReroute)
        XCTAssertTrue(update(&tracker, x: 60, y: -50, time: 20).shouldReroute)
        XCTAssertFalse(update(&tracker, x: 60, time: 25).offRoute)
        XCTAssertFalse(update(&tracker, x: 60, y: -50, time: 30).shouldReroute)
    }
    func testArrivalNeedsRouteProgressGoodAccuracyAndTwoFixes() {
        var tracker = route()
        _ = update(&tracker, x: 50, time: 0)
        _ = update(&tracker, x: 100, y: 10, time: 30)
        _ = update(&tracker, x: 100, y: 65, time: 50)
        XCTAssertFalse(update(&tracker, x: 100, y: 93, time: 65, accuracy: 18).arrived)
        XCTAssertFalse(update(&tracker, x: 100, y: 94, time: 70).arrived)
        XCTAssertTrue(update(&tracker, x: 100, y: 96, time: 75).arrived)
    }
    func testLoopEndpointNearStartDoesNotCauseArrivalOrJump() {
        var tracker = NavigationProgress(points: [.init(x: 0, y: 0), .init(x: 100, y: 0),
                                                  .init(x: 100, y: 100), .init(x: 0, y: 100), .init(x: 0, y: 5)], maneuvers: [])
        XCTAssertFalse(update(&tracker, x: 0, y: 4, time: 0).arrived)
        XCTAssertEqual(tracker.traveled, 0)
        XCTAssertFalse(update(&tracker, x: 0, y: 5, time: 5).arrived)
        XCTAssertEqual(tracker.traveled, 0)
    }
    func testManeuverLanguageDoesNotConfuseStreetNamesWithTurns() {
        XCTAssertEqual(NavigationManeuver.Kind.from(instruction: "Turn left onto Main Street"), .left)
        XCTAssertEqual(NavigationManeuver.Kind.from(instruction: "Bear right at the fork"), .bearRight)
        XCTAssertEqual(NavigationManeuver.Kind.from(instruction: "Keep left at the fork"), .keepLeft)
        XCTAssertEqual(NavigationManeuver.Kind.from(instruction: "Turn slightly left"), .bearLeft)
        XCTAssertEqual(NavigationManeuver.Kind.from(instruction: "Cross Main Street"), .cross)
        XCTAssertEqual(NavigationManeuver.Kind.from(instruction: "Make a U-turn"), .uTurn)
        XCTAssertNil(NavigationManeuver.Kind.from(instruction: "Continue on Left Bank Road"))
        XCTAssertNil(NavigationManeuver.Kind.from(instruction: "Destination is on your right"))
        XCTAssertNil(NavigationManeuver.Kind.from(instruction: "Continue toward Cross Street"))
        XCTAssertNil(NavigationManeuver.Kind.from(instruction: "At the roundabout, turn right at the third exit"))
    }
}
