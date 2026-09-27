import XCTest
@testable import CaptureCore

final class MobileModelLabelTests: XCTestCase {
    private let full = [MobilePoint(x: 0, y: 0), .init(x: 1, y: 0), .init(x: 1, y: 1), .init(x: 0, y: 1)]
    func testNewVocabularyUsesExistingRiskSemanticsWithoutMasks() {
        let cases = [("tree_trunk", "collision"), ("concrete_block", "trip"),
                     ("open_manhole", "drop"), ("low_branch", "overhead"), ("hose", "trip")]
        for (label, consequence) in cases {
            var risk = LocalRiskEngine()
            let box = MobileDetection(label: MobileModelLabel.runtime(label), confidence: 0.9,
                x: 0.35, y: 0.4, width: 0.3, height: 0.5)
            var result: MobileRiskAssessment?
            for t in [0.0, 200, 500] {
                result = risk.update(frame: .init(sessionID: "new-model", frameID: UInt64(t),
                    capturedUptimeMS: t, detections: [box]), nowUptimeMS: t, corridor: full)
            }
            XCTAssertEqual(result?.evidence?.hazardConsequence, consequence, label)
            XCTAssertNotEqual(result?.level, .urgent)
            XCTAssertNil(box.polygon)
        }
    }
    func testTrafficColorsNeverBecomeMovementInstructions() {
        for label in ["traffic_light_red", "traffic_light_green", "traffic_light_unknown"] {
            let normalized = MobileModelLabel.runtime(label)
            XCTAssertEqual(normalized, "traffic light")
            var risk = LocalRiskEngine()
            let box = MobileDetection(label: normalized, confidence: 0.99, x: 0.4, y: 0.3, width: 0.2, height: 0.6)
            for t in [0.0, 200, 500] {
                let result = risk.update(frame: .init(sessionID: "lights", frameID: UInt64(t), capturedUptimeMS: t,
                    detections: [box]), nowUptimeMS: t, corridor: full)
                XCTAssertNil(result.event)
            }
        }
        XCTAssertEqual(MobileModelLabel.runtime("person"), "person")
    }
    func testNewObstacleAppearsInStableSceneSummary() {
        var scene = LocalSceneDescriber()
        let box = MobileDetection(label: MobileModelLabel.runtime("bus_stop_shelter"), confidence: 0.9,
            x: 0.4, y: 0.4, width: 0.3, height: 0.5)
        for t in [0.0, 200, 500] {
            scene.update(frame: .init(sessionID: "scene", frameID: UInt64(t), capturedUptimeMS: t,
                detections: [box]), nowUptimeMS: t)
        }
        XCTAssertEqual(scene.describe(nowUptimeMS: 501).objects.first?.kind, "obstacle")
    }
}
