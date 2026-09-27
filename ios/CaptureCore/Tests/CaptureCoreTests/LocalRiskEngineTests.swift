import XCTest
@testable import CaptureCore

final class LocalRiskEngineTests: XCTestCase {
    let full = [MobilePoint(x: 0, y: 0), .init(x: 1, y: 0), .init(x: 1, y: 1), .init(x: 0, y: 1)]
    let center = [MobilePoint(x: 0.3, y: 0.4), .init(x: 0.7, y: 0.4), .init(x: 0.7, y: 1), .init(x: 0.3, y: 1)]
    func box(_ label: String = "pole", x: Double = 0.4, y: Double = 0.35, w: Double = 0.08,
             h: Double = 0.55, confidence: Double = 0.8, polygon: [MobilePoint]? = nil) -> MobileDetection {
        .init(label: label, confidence: confidence, x: x, y: y, width: w, height: h, polygon: polygon)
    }
    func frame(_ boxes: [MobileDetection], _ ms: Double, session: String = "test", revision: UInt64 = 0) -> MobileFrameResult {
        .init(sessionID: session, frameID: UInt64(ms), capturedUptimeMS: ms, revision: revision, detections: boxes)
    }
    func confirm(_ engine: inout LocalRiskEngine, boxes: [MobileDetection], offset: Double = 0,
                 corridor: [MobilePoint]? = nil) -> MobileRiskAssessment {
        var result: MobileRiskAssessment!
        for time in [0.0, 200, 500] {
            result = engine.update(frame: frame(boxes, offset + time), nowUptimeMS: offset + time, corridor: corridor ?? full)
        }
        return result
    }

    // Golden values produced by executing Python baseline on 2026-09-26.
    // obstacle_risk.py SHA256: 92e4954eafa4cd6f5222661aa7af0f260f8822fb664973dcc102159fdb90d326
    // obstacle_attention.py SHA256: 0072af66f4d81c4b44e152fbbb9043668c3fe6d6a0db478d1802486bfa34bbf9
    func testPythonGoldenAttentionRiskAndEvidence() throws {
        let goldens: [(MobileDetection, Double, MobileRiskLevel, MobileDirection, String, String)] = [
            (box(), 0.7964, .action, .ahead, "lower_visible_body", "collision"),
            (box("person", x: 0.5, y: 0.45, w: 0.035, h: 0.12), 0.376, .attention, .ahead, "lower_visible_body", "collision"),
            (box("concrete block", x: 0.2, y: 0.86, w: 0.25, h: 0.07), 0.672, .action, .left, "low_object_candidate", "trip"),
            (box("pothole", y: 0.8, w: 0.2, h: 0.08), 0.6136, .action, .ahead, "surface_change_candidate", "drop"),
            (box("overhead obstacle", y: 0.1, w: 0.3, h: 0.2), 0.381, .action, .ahead, "elevated_image_alignment", "overhead")
        ]
        for (box, score, level, direction, kind, consequence) in goldens {
            var engine = LocalRiskEngine()
            let result = confirm(&engine, boxes: [box])
            XCTAssertEqual(box.attention.score, score, accuracy: 0.0001)
            XCTAssertEqual(result.level, level); XCTAssertEqual(result.direction, direction)
            let evidence = try XCTUnwrap(result.evidence)
            XCTAssertEqual(evidence.overlap, 1); XCTAssertEqual(evidence.observations, 3)
            XCTAssertEqual(evidence.durationMS, 500); XCTAssertEqual(evidence.apparentAreaRatio, 1)
            XCTAssertEqual(evidence.kind, kind); XCTAssertEqual(evidence.hazardConsequence, consequence)
            XCTAssertFalse(evidence.categoryNamingEnabled); XCTAssertFalse(evidence.verifiedUrgency)
            XCTAssertEqual(evidence.directionBasis, .cameraImage)
            let position = direction == .ahead ? "center" : direction.rawValue
            let noun = ["trip": "low obstacle", "drop": "ground-level change", "surface": "ground-level change", "overhead": "overhead obstacle"][consequence] ?? "obstacle"
            XCTAssertEqual(result.event?.text, "Camera \(position): possible \(noun).")
        }
    }
    func testUncertainCategoryUsesGenericObstacleAndVehicleDoesNotClaimMotion() {
        var uncertain = LocalRiskEngine()
        let generic = confirm(&uncertain, boxes: [box("pothole", y: 0.8, w: 0.2, h: 0.08, confidence: 0.4)])
        XCTAssertEqual(generic.event?.text, "Camera center: possible obstacle.")
        var vehicle = LocalRiskEngine()
        let specific = confirm(&vehicle, boxes: [box("car")])
        XCTAssertEqual(specific.event?.text, "Camera center: possible vehicle.")
        XCTAssertFalse(specific.event?.text.contains("approaching") ?? true)
    }

    func testSameTimestampCannotConfirmOrReplay() {
        var engine = LocalRiskEngine()
        for _ in 0..<10 {
            XCTAssertEqual(engine.update(frame: frame([box()], 0), nowUptimeMS: 0, corridor: full).state, .confirming)
        }
        _ = engine.update(frame: frame([box()], 200), nowUptimeMS: 200, corridor: full)
        let confirmed = engine.update(frame: frame([box()], 500), nowUptimeMS: 500, corridor: full)
        XCTAssertNotNil(confirmed.event)
        XCTAssertNil(engine.update(frame: frame([box()], 500), nowUptimeMS: 550, corridor: full).event)
        XCTAssertEqual(engine.describe(nowUptimeMS: 550).evidence?.observations, 3)
    }
    func testStaleFutureAndSessionChangeNeverReplayOldDirection() {
        var engine = LocalRiskEngine()
        _ = confirm(&engine, boxes: [box(x: 0.1)])
        XCTAssertEqual(engine.describe(nowUptimeMS: 1_999).direction, .left)
        XCTAssertNil(engine.describe(nowUptimeMS: 2_000).direction)
        XCTAssertEqual(engine.update(frame: frame([box()], 500), nowUptimeMS: 2_000, corridor: full).health, .unavailable)
        XCTAssertEqual(engine.update(frame: frame([box()], 3_000), nowUptimeMS: 2_999, corridor: full).state, .stale)
        _ = confirm(&engine, boxes: [box()], offset: 4_000)
        let next = engine.update(frame: frame([box()], 4_600, session: "new"), nowUptimeMS: 4_600, corridor: full)
        XCTAssertEqual(next.state, .confirming); XCTAssertNil(next.event)
        XCTAssertEqual(engine.pause().health, .paused)
        XCTAssertEqual(engine.describe(nowUptimeMS: 4_700).state, .stale)
    }
    func testRevisionAndRegionChangeRequireNewEvidence() {
        var engine = LocalRiskEngine()
        _ = confirm(&engine, boxes: [box()])
        let changed = engine.update(frame: frame([box()], 600, revision: 1), nowUptimeMS: 600, corridor: full)
        XCTAssertEqual(changed.state, .confirming)
        let changedRegion = engine.update(frame: frame([box()], 700, revision: 1), nowUptimeMS: 700, corridor: center)
        XCTAssertEqual(changedRegion.state, .confirming); XCTAssertNil(changedRegion.event)
    }
    func testQuietStillAllowsRiskUpgradeWithoutCooldown() {
        var engine = LocalRiskEngine(); engine.quiet = true
        let distant = box(y: 0.45, w: 0.04, h: 0.12)
        let first = confirm(&engine, boxes: [distant])
        XCTAssertEqual(first.level, .attention); XCTAssertNil(first.event)
        let upgrade = engine.update(frame: frame([box(y: 0.45, w: 0.04, h: 0.25)], 700), nowUptimeMS: 700, corridor: full)
        XCTAssertEqual(upgrade.level, .action); XCTAssertNotNil(upgrade.event)
        engine.quiet = false
        for t in stride(from: 900.0, to: 10_000, by: 200) {
            XCTAssertNil(engine.update(frame: frame([box(y: 0.45, w: 0.04, h: 0.25)], t), nowUptimeMS: t, corridor: full).event)
        }
    }
    func testAnnouncedR1UpgradesImmediately() {
        var engine = LocalRiskEngine()
        let first = confirm(&engine, boxes: [box(y: 0.45, w: 0.04, h: 0.12)])
        XCTAssertNotNil(first.event)
        let upgrade = engine.update(frame: frame([box(y: 0.45, w: 0.04, h: 0.25)], 700), nowUptimeMS: 700, corridor: full)
        XCTAssertEqual(upgrade.event?.reasonCodes, ["risk_upgrade"])
    }
    func testOcclusionRemainsUnresolvedBeyondTrackMemory() {
        var engine = LocalRiskEngine()
        _ = confirm(&engine, boxes: [box()])
        for time in [600.0, 2_000, 9_000, 100_000] {
            let result = engine.update(frame: frame([], time), nowUptimeMS: time, corridor: full)
            XCTAssertEqual(result.lifecycle, .occludedUnresolved); XCTAssertEqual(result.level, .action)
            XCTAssertNil(result.event); XCTAssertNil(result.direction)
            XCTAssertFalse(result.text.contains("safe"))
        }
    }
    func testVisibleSeparationResolvesOnlyImageConflict() {
        var engine = LocalRiskEngine()
        _ = confirm(&engine, boxes: [box(x: 0.35, w: 0.2)], corridor: center)
        var result: MobileRiskAssessment!
        for (index, x) in [0.28, 0.21, 0.14, 0.07, 0.0, 0.0, 0.0].enumerated() {
            let time = 700.0 + Double(index) * 200
            result = engine.update(frame: frame([box(x: x, w: 0.2)], time), nowUptimeMS: time, corridor: center)
        }
        XCTAssertEqual(result.level, .none)
        XCTAssertTrue(result.text.contains("does not mean")); XCTAssertFalse(result.text.contains("passed"))
    }
    func testNewRelevantObjectNotSuppressedByAnother() {
        var engine = LocalRiskEngine()
        _ = confirm(&engine, boxes: [box(x: 0.15)])
        let result = confirm(&engine, boxes: [box(x: 0.15), box(x: 0.75)], offset: 700)
        XCTAssertEqual(result.event?.reasonCodes, ["new_relevance"])
        XCTAssertEqual(result.event?.direction, .right)
    }
    func testNamingRequiresValidatedClassAndStableIdentity() {
        var engine = LocalRiskEngine(namedLabels: ["pole", "train"])
        _ = engine.update(frame: frame([box("pole")], 0), nowUptimeMS: 0, corridor: full)
        _ = engine.update(frame: frame([box("train")], 200), nowUptimeMS: 200, corridor: full)
        let result = engine.update(frame: frame([box("pole")], 500), nowUptimeMS: 500, corridor: full)
        XCTAssertFalse(result.evidence!.categoryNamingEnabled)
        XCTAssertTrue(result.text.contains("possible obstacle"))
    }
    func testPolygonGapsAndInvalidInputs() {
        let leftMask = [MobilePoint(x: 0.05, y: 0.2), .init(x: 0.15, y: 0.2), .init(x: 0.15, y: 0.95), .init(x: 0.05, y: 0.95)]
        let masked = box(x: 0.05, y: 0.2, w: 0.8, h: 0.75, polygon: leftMask)
        XCTAssertEqual(LocalRiskEngine.intersection(box: masked, corridor: center), 0)
        XCTAssertGreaterThan(LocalRiskEngine.intersection(box: box(x: 0.05, y: 0.2, w: 0.8, h: 0.75), corridor: center), 0.25)
        var engine = LocalRiskEngine()
        XCTAssertEqual(confirm(&engine, boxes: [box(x: .nan), box(h: -1), box("tree")]).state, .unconfirmed)
        XCTAssertFalse(LocalRiskEngine.validCorridor([.init(x: 0, y: 0), .init(x: 1, y: 1), .init(x: 0, y: 1), .init(x: 1, y: 0)]))
        XCTAssertFalse(LocalRiskEngine.validCorridor([.init(x: 0, y: 0), .init(x: 0.01, y: 0), .init(x: 0.01, y: 0.01)]))
    }
    func testDisconnectedMaskComponentsPreserveAllVisibleRegions() {
        let left = [MobilePoint(x: 0.05, y: 0.6), .init(x: 0.15, y: 0.6), .init(x: 0.15, y: 0.95), .init(x: 0.05, y: 0.95)]
        let middle = [MobilePoint(x: 0.4, y: 0.6), .init(x: 0.6, y: 0.6), .init(x: 0.6, y: 0.95), .init(x: 0.4, y: 0.95)]
        var detection = box(x: 0.05, y: 0.6, w: 0.55, h: 0.35, polygon: left)
        XCTAssertEqual(LocalRiskEngine.intersection(box: detection, corridor: center), 0)
        detection.polygons = [left, middle]
        XCTAssertGreaterThan(LocalRiskEngine.intersection(box: detection, corridor: center), 0.6)
        // Duplicate components count once, not twice: overlap is a union.
        let original = LocalRiskEngine.intersection(box: detection, corridor: center)
        detection.polygons = [left, middle, middle]
        XCTAssertEqual(LocalRiskEngine.intersection(box: detection, corridor: center), original)
    }
    func testEventGateExpiresAtCaptureDeadlineAndDoesNotResurrectMutedEvents() throws {
        var engine = LocalRiskEngine()
        let event = try XCTUnwrap(confirm(&engine, boxes: [box()]).event)
        var gate = MobileGuidanceGate()
        XCTAssertEqual(gate.receive(event, nowUptimeMS: 600, sessionID: "other", revision: 0, enabled: true), .wrongSession)
        XCTAssertEqual(gate.receive(event, nowUptimeMS: 600, sessionID: "test", revision: 0, enabled: false), .disabled)
        XCTAssertEqual(gate.receive(event, nowUptimeMS: 700, sessionID: "test", revision: 0, enabled: true), .duplicate)
        var freshGate = MobileGuidanceGate()
        XCTAssertEqual(freshGate.receive(event, nowUptimeMS: 2_000, sessionID: "test", revision: 0, enabled: true), .expired)
        XCTAssertTrue(MobileGuidanceGate.mayInterrupt(incoming: .urgent, current: .action))
        XCTAssertFalse(MobileGuidanceGate.mayInterrupt(incoming: .attention, current: .action))
    }
    func testContractsRoundTrip() throws {
        let original = frame([box()], 500)
        XCTAssertEqual(try JSONDecoder().decode(MobileFrameResult.self, from: JSONEncoder().encode(original)), original)
        var engine = LocalRiskEngine()
        let assessment = confirm(&engine, boxes: [box()])
        XCTAssertEqual(try JSONDecoder().decode(MobileRiskAssessment.self, from: JSONEncoder().encode(assessment)), assessment)
    }
    func testLargeRepeatedCurbBoxesDoNotBecomeIndependentHazards() {
        // A long side boundary can cover foreground pixels without blocking the walker.
        let curbs = [box("curb", x: 0, y: 0.2, w: 0.46, h: 0.7, confidence: 0.97),
                     box("curb", x: 0.01, y: 0.3, w: 0.35, h: 0.65, confidence: 0.95)]
        do {
            var engine = LocalRiskEngine()
            for time in [0.0, 200, 500, 5000] {
                let input = frame(curbs, time)
                let result = engine.update(frame: input, nowUptimeMS: time, corridor: full)
                XCTAssertNil(result.event)
                XCTAssertEqual(result.level, .none)
                XCTAssertEqual(input.detections, curbs)
            }
        }
    }

    func testCurbContextDoesNotSuppressPedestrianOrGroundChangeHazards() {
        for label in ["person", "step", "pothole", "drop-off"] {
            var engine = LocalRiskEngine()
            let curb = box("curb", x: 0, y: 0.2, w: 0.5, h: 0.7, confidence: 0.99)
            let hazard = box(label, x: 0.4, y: 0.65, w: 0.15, h: 0.2)
            let result = confirm(&engine, boxes: [curb, hazard])
            XCTAssertEqual(result.event?.evidence.detectedLabel, label)
        }
    }

}
