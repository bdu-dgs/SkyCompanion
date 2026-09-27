import XCTest
@testable import CaptureCore

final class MobileAlertSpeechTests: XCTestCase {
    func testShortTwoPartAlertsAndFrontVocabulary() {
        XCTAssertEqual(MobileAlertSpeech.obstacle(direction: .left), "Caution left. Check your path.")
        XCTAssertEqual(MobileAlertSpeech.obstacle(direction: .right), "Caution right. Check your path.")
        XCTAssertEqual(MobileAlertSpeech.obstacle(direction: .ahead), "Caution front. Check your path.")
    }
    func testObservedBoxSideSurvivesRiskEventAndSpokenCaution() {
        let corridor = [MobilePoint(x: 0, y: 0), MobilePoint(x: 1, y: 0),
                        MobilePoint(x: 1, y: 1), MobilePoint(x: 0, y: 1)]
        let cases: [(Double, MobileDirection, String)] = [
            (0.15, .left, "Caution left."), (0.45, .ahead, "Caution front."),
            (0.75, .right, "Caution right.")
        ]
        for (x, expected, speech) in cases {
            var engine = LocalRiskEngine()
            var event: MobileRiskEvent?
            for index in 0..<3 {
                let time = Double(index)*200
                let box = MobileDetection(label: "bollard", confidence: 0.95,
                                          x: x, y: 0.55, width: 0.1, height: 0.4)
                let frame = MobileFrameResult(sessionID: "sides", frameID: UInt64(index+1),
                    capturedUptimeMS: time, revision: 1, detections: [box], inferenceMS: 0)
                event = engine.update(frame: frame, nowUptimeMS: time, corridor: corridor).event ?? event
            }
            XCTAssertEqual(event?.direction, expected)
            XCTAssertEqual(event.map { MobileAlertSpeech.caution(direction: $0.direction) }, speech)
        }
    }
    func testDistantLeftPedestrianDoesNotBecomeRightWarning() {
        // Positions from the reported local video's 15-second frame. Detection
        // and alert eligibility are separate: the right planter is another target.
        let pedestrian = MobileDetection(label: "person", confidence: 0.94,
            x: 0.320, y: 0.131, width: 0.043, height: 0.163)
        let planter = MobileDetection(label: "potted plant", confidence: 0.98,
            x: 0.735, y: 0.424, width: 0.265, height: 0.480)
        let corridor = [MobilePoint(x: 0.35, y: 0.45), MobilePoint(x: 0.65, y: 0.45),
                        MobilePoint(x: 0.9, y: 1), MobilePoint(x: 0.1, y: 1)]
        XCTAssertEqual(pedestrian.direction, .left)
        var leftOnly = LocalRiskEngine(), together = LocalRiskEngine()
        var rightEvent: MobileRiskEvent?
        for index in 0..<3 {
            let time = Double(index)*200
            var frame = MobileFrameResult(sessionID: "reported-frame", frameID: UInt64(index+1),
                capturedUptimeMS: time, revision: 0, detections: [pedestrian])
            XCTAssertNil(leftOnly.update(frame: frame, nowUptimeMS: time, corridor: corridor).event)
            frame.detections.append(planter)
            rightEvent = together.update(frame: frame, nowUptimeMS: time, corridor: corridor).event ?? rightEvent
        }
        XCTAssertEqual(rightEvent?.direction, .right)
        XCTAssertEqual(rightEvent?.evidence.detectedLabel, "potted plant")
    }
    func testCameraDirectionCannotImplyWalkingPermission() {
        for direction in [MobileDirection.left, .right, .ahead] {
            let speech = MobileAlertSpeech.obstacle(direction: direction).lowercased()
            for instruction in ["go straight", "keep left", "keep right", "turn", "clear", "safe"] {
                XCTAssertFalse(speech.contains(instruction))
            }
        }
    }
}
