import XCTest
@testable import CaptureCore

final class AlertPreferencesTests: XCTestCase {
    private func decoded(_ changes: [String: Any] = [:]) throws -> AlertPreferences {
        var document: [String: Any] = ["schema_version": 1, "revision": 4, "verbosity": "standard",
            "muted_categories": [String](), "repeat_interval_seconds": 8,
            "urgent_alerts_enabled": true, "updated_at_ms": 1_000]
        document.merge(changes) { _, new in new }
        return try JSONDecoder().decode(AlertPreferences.self, from: JSONSerialization.data(withJSONObject: document))
    }

    private func event(_ time: Double, level: MobileRiskLevel = .attention,
                       direction: MobileDirection = .left, verified: Bool = false) -> MobileRiskEvent {
        .init(id: UUID().uuidString, sessionID: "preferences", frameID: UInt64(time), revision: 0,
              capturedUptimeMS: time, trackID: UUID().uuidString, level: level, direction: direction,
              text: "Possible obstacle in the camera view.", evidence: .init(overlap: 0.5, observations: 3,
                durationMS: 500, kind: "lower_visible_body", nearCandidate: true, apparentAreaRatio: 1,
                directionBasis: .cameraImage, verifiedUrgency: verified, categoryNamingEnabled: false))
    }

    private func receive(_ event: MobileRiskEvent, gate: inout MobileGuidanceGate,
                         interval: Int = 8, priority: Int? = nil) -> MobileGuidanceGate.Decision {
        gate.receive(event, nowUptimeMS: event.capturedUptimeMS, sessionID: "preferences", revision: 0,
                     enabled: true, currentSpeechPriority: priority, ordinaryIntervalSeconds: interval)
    }

    func testPreferenceWireDocumentRoundTripsAndDefaultsAreValid() throws {
        XCTAssertTrue(AlertPreferences().isValid)
        let preferences = try decoded(["verbosity": "detailed", "muted_categories": ["tree", "curb"],
            "repeat_interval_seconds": 120, "applied_revision": 4, "applied_at_ms": 1_100])
        XCTAssertTrue(preferences.isValid)
        XCTAssertEqual(preferences.appliedRevision, 4)
        XCTAssertEqual(preferences.mutedCategories, ["tree", "curb"])
        XCTAssertEqual(try JSONDecoder().decode(AlertPreferences.self, from: JSONEncoder().encode(preferences)), preferences)
    }

    func testUnsupportedAndUnsafeDecodedPoliciesFailValidation() throws {
        let invalid: [[String: Any]] = [["schema_version": 2], ["revision": -1], ["verbosity": "verbose"],
            ["muted_categories": ["tree", "tree"]], ["muted_categories": ["traffic light"]],
            ["repeat_interval_seconds": 7], ["repeat_interval_seconds": 121],
            ["urgent_alerts_enabled": false], ["updated_at_ms": -1]]
        for changes in invalid { XCTAssertFalse(try decoded(changes).isValid, "\(changes)") }
        XCTAssertThrowsError(try decoded(["repeat_interval_seconds": "eight"]))
        XCTAssertThrowsError(try JSONDecoder().decode(AlertPreferences.self, from: Data("{}".utf8)))
    }

    func testCategoryAliasesAndUnknownLabels() {
        let aliases = ["LOW HANGING BRANCH": "tree", "bush": "tree", "utility pole": "pole",
            "bollard": "pole", "pedestrian": "person", "truck": "vehicle", "motorcycle": "vehicle",
            "bike": "bicycle", "staircase": "stairs", "steps": "stairs", "curb": "curb",
            "unrecognized label": "obstacle", "": "obstacle"]
        for (label, category) in aliases { XCTAssertEqual(AlertPreferences.category(for: label), category) }
        XCTAssertEqual(AlertPreferences.category(for: nil), "obstacle")
    }

    func testMutedCategoriesOnlySuppressAttention() throws {
        let preferences = try decoded(["muted_categories": ["person", "tree", "obstacle"]])
        for label: String? in ["pedestrian", "bush", "unknown", nil] {
            XCTAssertFalse(preferences.allows(level: .attention, label: label))
            XCTAssertTrue(preferences.allows(level: .action, label: label))
            XCTAssertTrue(preferences.allows(level: .urgent, label: label))
        }
        XCTAssertTrue(preferences.allows(level: .attention, label: "car"))
        XCTAssertTrue(AlertPreferences().allows(level: .attention, label: nil))
    }

    func testVerbosityAddsEvidenceContextWithoutDistanceOrSafetyClaims() throws {
        let minimal = try decoded(["verbosity": "minimal"])
        let standard = try decoded()
        let detailed = try decoded(["verbosity": "detailed"])
        for direction: MobileDirection in [.left, .ahead, .right] {
            let brief = minimal.speech(direction: direction, consequence: "trip", level: .action)
            let normal = standard.speech(direction: direction, consequence: "trip", level: .action)
            let expanded = detailed.speech(direction: direction, consequence: "trip", level: .action)
            XCTAssertLessThan(brief.count, normal.count)
            XCTAssertLessThan(normal.count, expanded.count)
            XCTAssertTrue(expanded.contains("Possible low obstacle in the camera view."))
            for text in [brief, normal, expanded] {
                XCTAssertFalse(text.contains(where: \.isNumber))
                for claim in ["meters", "metres", "feet", "safe", "clear", "approaching", "turn"] {
                    XCTAssertFalse(text.lowercased().contains(claim), text)
                }
            }
            XCTAssertEqual(minimal.speech(direction: direction, consequence: "trip", level: .urgent),
                           detailed.speech(direction: direction, consequence: "trip", level: .urgent))
            XCTAssertTrue(minimal.speech(direction: direction, consequence: "trip", level: .urgent).contains("now"))
        }
        XCTAssertTrue(detailed.speech(direction: .ahead, consequence: "unsupported", level: .action)
            .contains("Possible obstacle in the camera view."))
    }

    func testOrdinaryIntervalHonorsBoundsAndClampsInvalidCallerValues() {
        for (interval, expectedMS) in [(-10, 8_000.0), (8, 8_000), (30, 30_000), (120, 120_000), (999, 120_000)] {
            var gate = MobileGuidanceGate()
            XCTAssertEqual(receive(event(0), gate: &gate, interval: interval), .play(deadlineMS: 1_500))
            XCTAssertEqual(receive(event(expectedMS - 1, direction: .right), gate: &gate, interval: interval), .cooldown)
            XCTAssertEqual(receive(event(expectedMS, direction: .right), gate: &gate, interval: interval),
                           .play(deadlineMS: expectedMS + 1_500))
        }
    }

    func testEscalationBypassesLongIntervalAndUrgencyStillRequiresVerification() {
        var gate = MobileGuidanceGate()
        _ = receive(event(0), gate: &gate, interval: 120)
        XCTAssertEqual(receive(event(200, level: .action), gate: &gate, interval: 120, priority: 1),
                       .play(deadlineMS: 1_700))
        XCTAssertEqual(receive(event(400, level: .urgent), gate: &gate, interval: 120, priority: 2), .invalid)
        XCTAssertEqual(receive(event(600, level: .urgent, verified: true), gate: &gate, interval: 120, priority: 2),
                       .play(deadlineMS: 2_100))
        var actionGate = MobileGuidanceGate()
        _ = receive(event(0, level: .action), gate: &actionGate, interval: 120)
        XCTAssertEqual(receive(event(8_000, level: .action, direction: .right), gate: &actionGate, interval: 120),
                       .play(deadlineMS: 9_500))
    }

    func testAttentionCanPreemptNavigationButNavigationCannotPreemptAlerts() {
        var gate = MobileGuidanceGate()
        XCTAssertEqual(receive(event(0), gate: &gate, priority: -1), .play(deadlineMS: 1_500))
        XCTAssertTrue(MobileGuidanceGate.mayStartSpeech(incoming: 1, current: -1))
        for risk in 1...3 {
            XCTAssertFalse(MobileGuidanceGate.mayStartSpeech(incoming: -1, current: risk))
        }
    }

    func testRiskEvidenceOnlyCarriesConsistentLabelForCategoryFiltering() throws {
        let corridor = [MobilePoint(x: 0, y: 0), .init(x: 1, y: 0), .init(x: 1, y: 1), .init(x: 0, y: 1)]
        func confirm(labels: [String]) -> MobileRiskAssessment {
            var engine = LocalRiskEngine()
            var result: MobileRiskAssessment!
            for (time, label) in zip([0.0, 200, 500], labels) {
                let box = MobileDetection(label: label, confidence: 0.8, x: 0.4, y: 0.45, width: 0.04, height: 0.12)
                let frame = MobileFrameResult(sessionID: "test", frameID: UInt64(time), capturedUptimeMS: time, detections: [box])
                result = engine.update(frame: frame, nowUptimeMS: time, corridor: corridor)
            }
            return result
        }
        let consistent = confirm(labels: ["person", "person", "person"])
        let event = try XCTUnwrap(consistent.event)
        XCTAssertEqual(event.level, .attention)
        XCTAssertEqual(event.evidence.detectedLabel, "person")
        let muted = try decoded(["muted_categories": ["person"]])
        XCTAssertFalse(muted.allows(level: event.level, label: event.evidence.detectedLabel))
        // Baseline tracking keeps an uncertain class generic instead of naming it.
        let unstable = try XCTUnwrap(confirm(labels: ["person", "pole", "person"]).event)
        XCTAssertNil(unstable.evidence.detectedLabel)
        XCTAssertTrue(muted.allows(level: unstable.level, label: unstable.evidence.detectedLabel))
    }

    private func walking(_ objects: [MobileDetection], state: MobilePathState = .inside) -> MobileWalkingObservation {
        let person = MobileDetection(label: "person", confidence: 0.9, x: 0.46, y: 0.60, width: 0.08, height: 0.20)
        let boundary = [MobilePoint(x: 0.1, y: 0.1), .init(x: 0.9, y: 0.1), .init(x: 0.9, y: 0.95), .init(x: 0.1, y: 0.95)]
        var planner = MobileWalkingPlanner()
        var result: MobileWalkingObservation!
        for time in [0.0, 400, 800] {
            let frame = MobileFrameResult(sessionID: "walking", frameID: UInt64(time), capturedUptimeMS: time,
                                          detections: [person] + objects)
            var path = MobilePathObservation(frame: frame, state: state, reason: "test",
                foot: .init(x: 0.5, y: 0.8), boundary: boundary, eventText: nil)
            path.person = person
            result = planner.update(frame: frame, path: path, rearFollowing: true, now: time)
        }
        return result
    }

    private func walkingObstacle(_ label: String, x: Double, y: Double = 0.77) -> MobileDetection {
        .init(label: label, confidence: 0.8, x: x, y: y, width: 0.08, height: 0.06)
    }

    func testWalkingSideFilterRetainsEveryRelevantCategoryAndExcludesWearer() throws {
        let preferences = try decoded(["muted_categories": ["tree"]])
        let trees = walking([walkingObstacle("tree", x: 0.28), walkingObstacle("bush", x: 0.64)])
        XCTAssertTrue(trees.isOrdinarySideReminder)
        XCTAssertEqual(trees.severity, .attention)
        XCTAssertEqual(trees.obstacleLabels, ["bush", "tree"])
        XCTAssertFalse(preferences.allowsWalking(trees))

        let mixed = walking([walkingObstacle("tree", x: 0.28), walkingObstacle("bollard", x: 0.64)])
        XCTAssertEqual(mixed.action, .straight)
        XCTAssertEqual(mixed.obstacleLabels, ["bollard", "tree"])
        XCTAssertTrue(preferences.allowsWalking(mixed))
        // A distant detection is not a reason to re-enable a muted nearby reminder.
        let distant = walking([walkingObstacle("tree", x: 0.28), walkingObstacle("car", x: 0.01, y: 0.1)])
        XCTAssertEqual(distant.obstacleLabels, ["tree"])
        XCTAssertFalse(preferences.allowsWalking(distant))
    }

    func testWalkingLegacyAndUnknownCategoryUseObstacleFallback() throws {
        var legacy = walking([walkingObstacle("tree", x: 0.28)])
        legacy.obstacleLabels = nil
        let treeMuted = try decoded(["muted_categories": ["tree"]])
        let unknownMuted = try decoded(["muted_categories": ["obstacle"]])
        XCTAssertTrue(treeMuted.allowsWalking(legacy))
        XCTAssertFalse(unknownMuted.allowsWalking(legacy))
        legacy.obstacleLabels = []
        XCTAssertFalse(unknownMuted.allowsWalking(legacy))
        let unknown = walking([walkingObstacle("unrecognized", x: 0.28)])
        XCTAssertFalse(unknownMuted.allowsWalking(unknown))

        var json = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(legacy)) as? [String: Any])
        json.removeValue(forKey: "obstacleLabels")
        let decoded = try JSONDecoder().decode(MobileWalkingObservation.self, from: JSONSerialization.data(withJSONObject: json))
        XCTAssertNil(decoded.obstacleLabels)
        XCTAssertEqual(decoded.speech, legacy.speech)
    }

    func testWalkingAvoidanceTrackingAndBoundaryInstructionsCannotBeMutedOrShortenedAway() throws {
        let preferences = try decoded(["muted_categories": Array(AlertPreferences.categories), "verbosity": "minimal"])
        let front = walking([walkingObstacle("tree", x: 0.46, y: 0.58)])
        XCTAssertTrue(front.action == .left || front.action == .right)
        let boundary = walking([], state: .outside)
        let lostTracking = walking([], state: .unknown)
        for observation in [front, boundary, lostTracking] {
            XCTAssertEqual(observation.severity, .action)
            XCTAssertFalse(observation.isOrdinarySideReminder)
            XCTAssertTrue(preferences.allowsWalking(observation))
            XCTAssertEqual(preferences.speech(walking: observation), observation.speech)
            XCTAssertTrue(preferences.speech(walking: observation).contains(try XCTUnwrap(observation.action).text))
        }
    }

    func testWalkingVerbosityOnlyShortensConfirmedOrdinarySideReminder() throws {
        let side = walking([walkingObstacle("tree", x: 0.28)])
        let minimal = try decoded(["verbosity": "minimal"])
        let detailed = try decoded(["verbosity": "detailed"])
        XCTAssertEqual(minimal.speech(walking: side), "Caution left.")
        XCTAssertEqual(AlertPreferences().speech(walking: side), side.speech)
        let expanded = detailed.speech(walking: side)
        XCTAssertTrue(expanded.hasPrefix(side.speech))
        XCTAssertTrue(expanded.contains("camera view"))
        XCTAssertFalse(expanded.contains(side.reason))
        XCTAssertFalse(expanded.contains(where: \.isNumber))
        for claim in ["meters", "feet", "safe", "clear"] { XCTAssertFalse(expanded.contains(claim)) }
        let empty = walking([])
        XCTAssertEqual(empty.severity, .none)
        XCTAssertEqual(detailed.speech(walking: empty), "")
    }
}
