import XCTest
@testable import CaptureCore

final class VoiceEventTests: XCTestCase {
    private func event(_ id: String = "event-1", ttl: Double = 1_200,
                       asset: String = "risk_camera_obstacle_ahead", named: Bool = false,
                       capture: Double = 19_900) -> VoiceEvent {
        VoiceEvent(id: id, direction: .ahead, asset: asset, ttlMS: ttl, categoryNamingEnabled: named,
                   capturedUptimeMS: capture, maxObservationAgeMS: 1_500)
    }

    func testNetworkEventsCannotInjectSpeechOrMismatchedDirections() throws {
        let json = #"{"schema_version":2,"id":"e1","speech_code":"camera_obstacle","risk_level":"R2","direction_frame":"camera_image","direction":"ahead","asset":"risk_camera_obstacle_ahead","priority":"obstacle","ttl_ms":1200,"category_naming_enabled":false,"captured_uptime_ms":19900,"max_observation_age_ms":1500,"text":"Safe to cross, train ahead."}"#
        let value = try JSONDecoder().decode(VoiceEvent.self, from: Data(json.utf8))
        XCTAssertTrue(value.isAllowed)
        XCTAssertEqual(value.safeText, "Caution. Possible obstacle ahead in the camera view. Your direction is unverified.")
        XCTAssertFalse(event(asset: "risk_camera_obstacle_left").isAllowed)
        XCTAssertFalse(event(asset: "../../arbitrary").isAllowed)
        XCTAssertFalse(event(named: true).isAllowed)
    }

    func testLegacyProductionRejectedAndLegacyTestHasSafeCameraPhrase() {
        let production = VoiceEvent(id: "old", direction: .ahead, asset: "stop_obstacle_ahead", ttlMS: 1200, schemaVersion: nil)
        XCTAssertFalse(production.isAllowed)
        let test = VoiceEvent(id: "test", direction: .left, asset: "stop_obstacle_left", priority: "test", ttlMS: 1200, schemaVersion: nil)
        XCTAssertTrue(test.isAllowed)
        XCTAssertTrue(test.safeText.contains("camera view"))
        XCTAssertFalse(test.safeText.contains("Stop"))
    }

    func testEveryRiskSpeechCodeIsLocalAndDirectionScoped() {
        for (code, noun) in [("camera_obstacle", "obstacle"), ("camera_surface", "ground change"),
                             ("camera_overhead", "overhead obstruction"), ("camera_vehicle", "vehicle conflict")] {
            let risk = VoiceEvent(id: code, direction: .right, asset: "risk_\(code)_right", ttlMS: 1500,
                                  capturedUptimeMS: 100, maxObservationAgeMS: 1500, speechCode: code)
            XCTAssertTrue(risk.isAllowed)
            XCTAssertEqual(risk.safeText, "Caution. Possible \(noun) on the right in the camera view. Your direction is unverified.")
        }
        XCTAssertFalse(VoiceEvent(id: "bad", direction: .ahead, asset: "risk_camera_obstacle_ahead", ttlMS: 1500).isAllowed)
        XCTAssertFalse(VoiceEvent(id: "bad-frame", direction: .ahead, asset: "risk_camera_obstacle_ahead", ttlMS: 1500,
                                  capturedUptimeMS: 100, maxObservationAgeMS: 1500, directionFrame: "wearer").isAllowed)
    }

    func testProductionSeverityMustMatchPriorityAndR0NeverAlerts() {
        for level in ["R0", "R1", "R2", "R3", "R4"] {
            for priority in ["obstacle", "urgent"] {
                let risk = VoiceEvent(id: "severity", direction: .ahead, asset: "risk_camera_obstacle_ahead",
                                      priority: priority, ttlMS: 1500, capturedUptimeMS: 100,
                                      maxObservationAgeMS: 1500, riskLevel: level)
                let expected = (priority == "urgent" && level == "R3")
                    || (priority == "obstacle" && ["R1", "R2"].contains(level))
                XCTAssertEqual(risk.isAllowed, expected, "\(priority) \(level)")
            }
        }
    }

    func testHealthIsSeparateFromRiskAndHasNoSourceCaptureClock() {
        for code in VoiceEvent.healthPhrases.keys {
            let health = VoiceEvent(id: code, direction: .ahead, asset: "health_\(code)", priority: "health", ttlMS: 1500,
                                    speechCode: code, directionFrame: "unavailable", riskLevel: nil)
            XCTAssertTrue(health.isAllowed)
            XCTAssertEqual(health.safeText, VoiceEvent.healthPhrases[code])
            XCTAssertFalse(health.safeText.contains("Stop"))
        }
        let invalid = VoiceEvent(id: "bad", direction: .ahead, asset: "health_perception_unavailable", priority: "health", ttlMS: 1500,
                                 speechCode: "perception_unavailable", directionFrame: "unavailable", riskLevel: "R3")
        XCTAssertFalse(invalid.isAllowed)
    }

    func testLowerPrioritiesCannotInterruptRiskAndUrgentCannotBeDowngraded() {
        for low in ["test", "query", "health"] {
            for risk in ["obstacle", "urgent"] {
                XCTAssertFalse(VoiceEventGate.mayInterrupt(incomingPriority: low, currentPriority: risk))
                XCTAssertTrue(VoiceEventGate.mayInterrupt(incomingPriority: risk, currentPriority: low))
            }
        }
        XCTAssertFalse(VoiceEventGate.mayInterrupt(incomingPriority: "test", currentPriority: "query"))
        XCTAssertTrue(VoiceEventGate.mayInterrupt(incomingPriority: "query", currentPriority: "test"))
        XCTAssertFalse(VoiceEventGate.mayInterrupt(incomingPriority: "obstacle", currentPriority: "urgent"))
        XCTAssertTrue(VoiceEventGate.mayInterrupt(incomingPriority: "urgent", currentPriority: "obstacle"))
        XCTAssertTrue(VoiceEventGate.mayInterrupt(incomingPriority: "obstacle", currentPriority: "obstacle"))
        XCTAssertTrue(VoiceEventGate.mayInterrupt(incomingPriority: "test", currentPriority: nil))
        XCTAssertFalse(VoiceEventGate.mayInterrupt(incomingPriority: "arbitrary", currentPriority: nil))
    }

    func testDeadlineUsesOnlyReceivingDeviceMonotonicTime() {
        var gate = VoiceEventGate()
        XCTAssertEqual(gate.receive(event(), nowMS: 20_000, enabled: true), .play(deadlineMS: 21_200))
        XCTAssertTrue(VoiceEventGate.canStart(deadlineMS: 21_200, nowMS: 21_199))
        XCTAssertFalse(VoiceEventGate.canStart(deadlineMS: 21_200, nowMS: 21_200))
        XCTAssertFalse(VoiceEventGate.canStart(deadlineMS: 21_200, nowMS: .infinity))
    }

    func testDuplicatesAndExpiredMessagesNeverReplay() {
        var gate = VoiceEventGate()
        XCTAssertEqual(gate.receive(event(ttl: 0), nowMS: 20_000, enabled: true), .expired)
        XCTAssertEqual(gate.receive(event(ttl: 1_500), nowMS: 20_001, enabled: true), .duplicate)
        XCTAssertEqual(gate.receive(event("e2", ttl: 1_501), nowMS: 20_001, enabled: true), .invalid)
        XCTAssertEqual(gate.receive(event("e3", ttl: -.infinity), nowMS: 20_001, enabled: true), .invalid)
    }

    func testRouteChangesCannotReplayDroppedEventsAndHistoryIsBounded() {
        var gate = VoiceEventGate(historyLimit: 2)
        XCTAssertEqual(gate.receive(event("a", capture: 0), nowMS: 1, enabled: false), .disabled)
        XCTAssertEqual(gate.receive(event("a", capture: 0), nowMS: 2, enabled: true), .duplicate)
        _ = gate.receive(event("b", capture: 0), nowMS: 3, enabled: true)
        _ = gate.receive(event("c", capture: 0), nowMS: 4, enabled: true)
        XCTAssertEqual(gate.receive(event("b", capture: 0), nowMS: 5, enabled: true), .duplicate)
        XCTAssertEqual(gate.receive(event("a", capture: 0), nowMS: 6, enabled: true), .play(deadlineMS: 1_206))
    }
}
