import XCTest
@testable import CaptureCore

final class LocalSceneDescriberTests: XCTestCase {
    func box(_ label: String, x: Double = 0.45, y: Double = 0.35, w: Double = 0.08, h: Double = 0.55,
             confidence: Double = 0.8) -> MobileDetection {
        .init(label: label, confidence: confidence, x: x, y: y, width: w, height: h)
    }
    func frame(_ boxes: [MobileDetection], _ ms: Double, session: String = "test", revision: UInt64 = 0) -> MobileFrameResult {
        .init(sessionID: session, frameID: UInt64(ms), capturedUptimeMS: ms, revision: revision, detections: boxes)
    }
    // Executed Python scene_description.py SHA256:
    // 5b6a0dea7d5ccc12f3d93a31d71d3144a9bf60730feea8c064a3765620a38455
    func testPythonGoldenDistinctKindsAndImageDirections() {
        let boxes = [0.05, 0.45, 0.8].map { box("person", x: $0) }
            + [box("traffic light", x: 0.8, y: 0.1, w: 0.05, h: 0.1), box("pole", x: 0.5, y: 0.1, w: 0.08, h: 0.88)]
        var scene = LocalSceneDescriber()
        for time in [10_000.0, 10_200, 10_400] { scene.update(frame: frame(boxes, time), nowUptimeMS: time) }
        let result = scene.describe(nowUptimeMS: 10_500)
        XCTAssertEqual(result.code, .sceneSummary)
        XCTAssertEqual(result.objects.map(\.kind), ["obstacle", "person", "traffic_light"])
        XCTAssertEqual(result.objects.map(\.direction), [.ahead, .left, .right])
        XCTAssertEqual(result.objects.map(\.vertical), ["middle", "middle", "upper"])
        XCTAssertEqual(result.directionBasis, .cameraImage)
        XCTAssertTrue(result.text.hasPrefix("In the camera view:"))
    }
    func testGroupingCapsCountAndUnknownLabelsStayAbsent() {
        var scene = LocalSceneDescriber()
        let boxes = [0.02, 0.08, 0.14, 0.2].map { box("person", x: $0, w: 0.02) } + [box("train")]
        for time in [0.0, 200, 400] { scene.update(frame: frame(boxes, time), nowUptimeMS: time) }
        let result = scene.describe(nowUptimeMS: 500)
        XCTAssertEqual(result.objects.count, 1); XCTAssertEqual(result.objects.first?.count, 3)
        XCTAssertTrue(result.text.contains("several people")); XCTAssertFalse(result.text.contains("train"))
    }
    func testDuplicateFramesAndFreshness() {
        var scene = LocalSceneDescriber()
        for _ in 0..<10 { scene.update(frame: frame([box("person")], 0), nowUptimeMS: 0) }
        XCTAssertEqual(scene.describe(nowUptimeMS: 100).code, .noStableObjects)
        for time in [200.0, 400] { scene.update(frame: frame([box("person")], time), nowUptimeMS: time) }
        XCTAssertEqual(scene.describe(nowUptimeMS: 1_899).code, .sceneSummary)
        XCTAssertEqual(scene.describe(nowUptimeMS: 1_900).code, .visionUnavailable)
        scene.update(frame: frame([box("person")], 2_000, session: "new"), nowUptimeMS: 2_000)
        XCTAssertEqual(scene.describe(nowUptimeMS: 2_001).code, .noStableObjects)
        scene.reset()
        XCTAssertEqual(scene.describe(nowUptimeMS: 2_010).code, .visionUnavailable)
    }
    func testWeakAndMissingObservationsDoNotImplyClearPath() {
        var scene = LocalSceneDescriber()
        for time in [0.0, 200, 400] {
            scene.update(frame: frame([box("person", confidence: 0.2), box("pole", y: 0.1, h: 0.1)], time), nowUptimeMS: time)
        }
        let summary = scene.describe(nowUptimeMS: 500)
        XCTAssertEqual(summary.code, .noStableObjects)
        XCTAssertTrue(summary.text.contains("does not mean the path is clear"))
    }
}
