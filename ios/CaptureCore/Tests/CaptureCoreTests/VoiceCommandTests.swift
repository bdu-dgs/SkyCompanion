import XCTest
@testable import CaptureCore
final class VoiceCommandTests: XCTestCase {
    func testExactCommands() {
        XCTAssertEqual(VoiceCommand.parse("SkyCompanion, repeat alert!"), .repeatAlert)
        XCTAssertEqual(VoiceCommand.parse("SKYCOMPANION UNMUTE"), .unmute)
        XCTAssertEqual(VoiceCommand.parse("SkyCompanion describe ahead"), .describe)
        XCTAssertEqual(VoiceCommand.parse("SkyCompanion stop listening"), .stop)
    }
    func testRiskControlCommandsAndAmbientRejection() {
        for (text, command) in [("SkyCompanion why", VoiceCommand.explain), ("SkyCompanion got it", .acknowledge),
                                ("SkyCompanion quieter", .quiet), ("SkyCompanion normal alerts", .normal),
                                ("SkyCompanion wrong alert", .reportFalseAlert)] {
            XCTAssertEqual(VoiceCommand.parse(text), command)
            XCTAssertNil(VoiceCommand.parse("Tell " + text))
            XCTAssertNil(VoiceCommand.parse(text + " later"))
        }
    }
    func testRiskRepliesUseWhitelistedReasonsAndMakeNoResolutionClaim() {
        let explanation = VoiceReply.text(code: "risk_explanation", direction: nil,
                                          reasonCodes: ["image_corridor_overlap", "persistent_observation"])!
        XCTAssertTrue(explanation.contains("camera corridor"))
        XCTAssertTrue(explanation.contains("relative to you are unknown"))
        XCTAssertNil(VoiceReply.text(code: "risk_explanation", direction: nil, reasonCodes: ["cross now"]))
        XCTAssertNil(VoiceReply.text(code: "risk_explanation", direction: nil, reasonCodes: []))
        XCTAssertTrue(VoiceReply.text(code: "risk_acknowledged", direction: nil)!.contains("does not mean"))
        XCTAssertTrue(VoiceReply.text(code: "risk_unresolved", direction: nil)!.contains("not been confirmed resolved"))
        for code in ["quiet_enabled", "quiet_disabled", "false_alert_saved", "false_alert_no_evidence"] {
            XCTAssertNotNil(VoiceReply.text(code: code, direction: nil))
        }
        XCTAssertFalse(VoiceReply.text(code: "vision_unavailable", direction: nil)!.contains("Stop"))
    }
    func testCameraQuestionAliasesAreWholeUtterances() {
        for value in ["SkyCompanion what is ahead", "SkyCompanion what's ahead?", "SkyCompanion, what’s ahead?",
                      "SkyCompanion what obstacles are ahead", "SkyCompanion what is around me",
                      "SkyCompanion what obstacles are around me"] {
            XCTAssertEqual(VoiceCommand.parse(value), .describe, value)
        }
        for value in ["what is ahead", "tell SkyCompanion what is ahead", "SkyCompanion what is ahead and turn left",
                      "SkyCompanion what is behind me", "SkyCompanion explain this building"] {
            XCTAssertNil(VoiceCommand.parse(value), value)
        }
    }
    func testDescriptionsStateCameraViewLimits() {
        for (code, direction) in [("unconfirmed_obstacle", "left"), ("no_confirmed_obstacle", "ahead")] {
            let text = VoiceReply.text(code: code, direction: direction)!
            XCTAssertTrue(text.contains("camera view"))
            XCTAssertTrue(text.contains("cannot see outside this view"))
        }
    }
    func testSceneSummaryIncludesVisibleObjectsWithoutClaimingSafety() {
        let objects = [VoiceSceneObject(kind: "person", direction: "ahead", count: 3, vertical: "middle"),
                       VoiceSceneObject(kind: "traffic_light", direction: "right", count: 1, vertical: "upper")]
        let text = VoiceReply.text(code: "scene_summary", direction: nil, objects: objects)!
        XCTAssertTrue(text.contains("several people ahead"))
        XCTAssertTrue(text.contains("a traffic light on the right"))
        XCTAssertTrue(text.contains("upper part of the view"))
        XCTAssertFalse(text.contains("clear"))
        XCTAssertFalse(text.contains("cross"))
        XCTAssertEqual(VoiceReply.text(code: "no_stable_objects", direction: nil),
                       "I cannot identify objects reliably in the current view.")
    }
    func testSceneSummaryRejectsUnknownLabelsCountsAndInjectedDirections() {
        for object in [VoiceSceneObject(kind: "train", direction: "ahead", count: 1, vertical: "middle"),
                       VoiceSceneObject(kind: "person", direction: "cross now", count: 1, vertical: "middle"),
                       VoiceSceneObject(kind: "chair", direction: "left", count: 0, vertical: "lower"),
                       VoiceSceneObject(kind: "car", direction: "right", count: 4, vertical: "upper"),
                       VoiceSceneObject(kind: "dog", direction: "ahead", count: 1, vertical: "safe")] {
            XCTAssertNil(VoiceReply.text(code: "scene_summary", direction: nil, objects: [object]))
        }
        XCTAssertNil(VoiceReply.text(code: "scene_summary", direction: nil, objects: []))
        let four = Array(repeating: VoiceSceneObject(kind: "person", direction: "ahead", count: 1, vertical: "middle"), count: 4)
        XCTAssertNil(VoiceReply.text(code: "scene_summary", direction: nil, objects: four))
    }
    func testAmbientAndSubstringsCannotTrigger() {
        for value in ["stop", "mute", "please tell SkyCompanion mute", "SkyCompanion mute the television", "Obstacle ahead", "SkyCompanion repeat SkyCompanion mute"] {
            XCTAssertNil(VoiceCommand.parse(value), value)
        }
    }
    func testUntrustedRepliesAndDirectionsRejected() {
        XCTAssertNil(VoiceReply.text(code: "turn_left_now", direction: "left"))
        XCTAssertNil(VoiceReply.text(code: "unconfirmed_obstacle", direction: "turn right"))
        XCTAssertNotNil(VoiceReply.text(code: "vision_unavailable", direction: nil))
        XCTAssertTrue(VoiceReply.text(code: "no_confirmed_obstacle", direction: nil)!.contains("does not mean"))
    }
    func testPhoneCaptureClockPreventsNetworkStaleReplay() {
        var gate = VoiceEventGate()
        let old = VoiceEvent(id: "old", direction: .ahead, asset: "risk_camera_obstacle_ahead", ttlMS: 1500,
                             capturedUptimeMS: 1000, maxObservationAgeMS: 1500)
        XCTAssertEqual(gate.receive(old, nowMS: 3000, enabled: true), .expired)
        let fresh = VoiceEvent(id: "fresh", direction: .ahead, asset: "risk_camera_obstacle_ahead", ttlMS: 1500,
                               capturedUptimeMS: 2500, maxObservationAgeMS: 1500)
        XCTAssertEqual(gate.receive(fresh, nowMS: 3000, enabled: true), .play(deadlineMS: 4000))
        let reboot = VoiceEvent(id: "future", direction: .ahead, asset: "risk_camera_obstacle_ahead", ttlMS: 1500,
                                capturedUptimeMS: 5000, maxObservationAgeMS: 1500)
        XCTAssertEqual(gate.receive(reboot, nowMS: 3000, enabled: true), .expired)
    }
}
