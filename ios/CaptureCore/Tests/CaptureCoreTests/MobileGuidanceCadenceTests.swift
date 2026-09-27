import XCTest
@testable import CaptureCore

final class MobileGuidanceCadenceTests: XCTestCase {
    private func event(_ time: Double, level: MobileRiskLevel = .action,
                       direction: MobileDirection = .left, verified: Bool = false) -> MobileRiskEvent {
        .init(id: UUID().uuidString, sessionID: "test", frameID: UInt64(time), revision: 0,
              capturedUptimeMS: time, trackID: UUID().uuidString, level: level, direction: direction,
              text: "Possible obstacle in the camera view.", evidence: .init(overlap: 0.5, observations: 3,
                durationMS: 500, kind: "lower_visible_body", nearCandidate: true, apparentAreaRatio: 1,
                directionBasis: .cameraImage, verifiedUrgency: verified, categoryNamingEnabled: false))
    }
    private func receive(_ event: MobileRiskEvent, gate: inout MobileGuidanceGate,
                         priority: Int? = nil, enabled: Bool = true) -> MobileGuidanceGate.Decision {
        gate.receive(event, nowUptimeMS: event.capturedUptimeMS, sessionID: "test", revision: 0,
                     enabled: enabled, currentSpeechPriority: priority)
    }

    func testHapticsDeliverFreshObstacleWhileSpeechIsBusyWithoutInterruptingVoice() {
        var gate = MobileGuidanceGate()
        let alert = event(0)
        XCTAssertEqual(gate.receive(alert, nowUptimeMS:0, sessionID:"test", revision:0,
            enabled:true,currentSpeechPriority:2,hapticsEnabled:true), .play(deadlineMS:1_500))
        XCTAssertFalse(MobileGuidanceGate.mayStartSpeech(incoming:1,current:2))
        XCTAssertEqual(gate.receive(alert, nowUptimeMS:0, sessionID:"test", revision:0,
            enabled:true,currentSpeechPriority:2,hapticsEnabled:true), .duplicate)
        let stale = event(200)
        XCTAssertEqual(gate.receive(stale, nowUptimeMS:2_000, sessionID:"test", revision:0,
            enabled:true,currentSpeechPriority:2,hapticsEnabled:true), .expired)
    }




    func testRapidNewTrackIDsDoNotRestartSameAlert() {
        var gate = MobileGuidanceGate()
        XCTAssertEqual(receive(event(0), gate: &gate), .play(deadlineMS: 1_500))
        for time in stride(from: 200.0, to: 20_000, by: 200) {
            XCTAssertEqual(receive(event(time), gate: &gate), .duplicate)
        }
        XCTAssertEqual(receive(event(40_000), gate: &gate), .play(deadlineMS: 41_500))
    }
    func testDifferentDirectionsRespectGlobalGap() {
        var gate = MobileGuidanceGate()
        _ = receive(event(0), gate: &gate)
        XCTAssertEqual(receive(event(7_999, direction: .right), gate: &gate), .cooldown)
        XCTAssertEqual(receive(event(8_000, direction: .right), gate: &gate), .play(deadlineMS: 9_500))
        XCTAssertEqual(receive(event(16_000), gate: &gate), .duplicate)
    }
    func testUpgradeBypassesCooldownAndInterruptsLowerSpeech() {
        var gate = MobileGuidanceGate()
        _ = receive(event(0, level: .attention), gate: &gate)
        XCTAssertEqual(receive(event(200), gate: &gate, priority: 1), .play(deadlineMS: 1_700))
        XCTAssertEqual(receive(event(400, level: .urgent), gate: &gate, priority: 2), .invalid)
        XCTAssertEqual(receive(event(600, level: .urgent, verified: true), gate: &gate, priority: 2), .play(deadlineMS: 2_100))
    }
    func testSamePrioritySpeechFinishesAndDroppedEventIsNotQueued() {
        var gate = MobileGuidanceGate()
        let dropped = event(0)
        XCTAssertEqual(receive(dropped, gate: &gate, priority: 2), .busy)
        XCTAssertEqual(receive(dropped, gate: &gate), .duplicate)
        XCTAssertEqual(receive(event(200), gate: &gate), .play(deadlineMS: 1_700))
        XCTAssertFalse(MobileGuidanceGate.mayStartSpeech(incoming: 2, current: 2))
        XCTAssertTrue(MobileGuidanceGate.mayStartSpeech(incoming: 2, current: 2, explicitRequest: true))
        XCTAssertFalse(MobileGuidanceGate.mayStartSpeech(incoming: 1, current: 2, explicitRequest: true))
    }
    func testContinuousObservationAndOcclusionNeverCausePeriodicReminders() {
        var gate = MobileGuidanceGate()
        let initial = event(0)
        _ = receive(initial, gate: &gate)
        let observation = MobileRiskAssessment(state: .occupied, level: .action, text: initial.text,
            evidence: initial.evidence, direction: initial.direction, trackID: initial.trackID, lifecycle: .observed)
        for time in stride(from: 500.0, through: 60_000, by: 500) {
            gate.observe(observation, nowUptimeMS: time)
        }
        XCTAssertEqual(receive(event(60_100), gate: &gate), .duplicate)
        gate.observe(.init(state: .occupied, level: .action, health: .limited,
            text: "Unresolved", lifecycle: .occludedUnresolved), nowUptimeMS: 90_000)
        XCTAssertEqual(receive(event(90_100), gate: &gate), .duplicate)
        gate.observe(.init(state: .unconfirmed, text: "No confirmed conflict",
            lifecycle: .imageConflictResolved), nowUptimeMS: 100_000)
        XCTAssertEqual(receive(event(100_100), gate: &gate), .play(deadlineMS: 101_600))
    }

    func testCommandInteractionUsesHapticAdmissionWithoutOrdinarySpeechInterruption() {
        var gate = MobileGuidanceGate()
        let alert = event(0)
        XCTAssertEqual(gate.receive(alert, nowUptimeMS: 0, sessionID: "test", revision: 0,
            enabled: true, currentSpeechPriority: 0, protectingCommand: true), .play(deadlineMS: 1_500))
        XCTAssertFalse(MobileGuidanceGate.mayStartSpeech(incoming: 2, current: 0, protectingCommand: true))
        XCTAssertFalse(MobileGuidanceGate.mayStartSpeech(incoming: 2, current: nil, protectingCommand: true))
        XCTAssertTrue(MobileGuidanceGate.mayStartSpeech(incoming: 3, current: 0, protectingCommand: true))
        XCTAssertTrue(MobileGuidanceGate.mayStartSpeech(incoming: 0, current: nil, explicitRequest: true, protectingCommand: true))
        XCTAssertEqual(gate.receive(event(200), nowUptimeMS: 200, sessionID: "test", revision: 0,
            enabled: true, currentSpeechPriority: 0, protectingCommand: true), .duplicate)
    }

    func testMuteExpiryAndNewSessionDoNotReplayOldEvents() {
        var gate = MobileGuidanceGate()
        let muted = event(0)
        XCTAssertEqual(receive(muted, gate: &gate, enabled: false), .disabled)
        XCTAssertEqual(receive(muted, gate: &gate), .duplicate)
        XCTAssertEqual(gate.receive(event(10), nowUptimeMS: 2_000, sessionID: "test", revision: 0, enabled: true), .expired)
        _ = receive(event(2_000), gate: &gate)
        gate = MobileGuidanceGate()
        XCTAssertEqual(receive(event(2_100), gate: &gate), .play(deadlineMS: 3_600))
    }
}
