import Foundation

/// Keeps camera-obstacle evidence independent of wearer/path availability.
/// The detector output and the existing risk heuristic remain unchanged.
public struct MobileCameraObstacleMonitor: Sendable {
    private enum Scope { case ordinary, peopleExcluded, walking }
    private var scope: Scope?
    private var risk = LocalRiskEngine()
    public init() {}
    public mutating func reset() { scope = nil; risk.reset() }

    public mutating func update(frame: MobileFrameResult, wearer: MobileWearerObservation?,
                                wearerRequired: Bool, walkingActive: Bool = false,
                                nowUptimeMS: Double, corridor: [MobilePoint]?) -> MobileRiskAssessment {
        let matched = wearer?.matchedIndex(in: frame)
        let excludePeople = wearerRequired && matched == nil
        let next: Scope = excludePeople ? .peopleExcluded : walkingActive ? .walking : .ordinary
        // Never carry a former person track into degraded mode, or consume a
        // camera event during walking mode then suppress it after walking fails.
        if next != scope { risk.reset(); scope = next }
        var environment = wearer?.environment(in: frame) ?? frame
        if excludePeople { environment.detections.removeAll { $0.label == "person" } }
        return risk.update(frame: environment, nowUptimeMS: nowUptimeMS, corridor: corridor)
    }
}

/// A fallback Caution can wait behind the one-time tracking notice, but only
/// while the same obstacle is observed in fresh frames. No stale audio queue.
public struct MobileCameraAlertRetry: Sendable {
    private var pending: MobileRiskEvent?
    public init() {}
    public mutating func reset() { pending = nil }
    public mutating func candidate(frame: MobileFrameResult, assessment: MobileRiskAssessment?,
                                   now: Double, enabled: Bool) -> MobileRiskEvent? {
        guard enabled, frame.isFresh(at: now), let assessment,
              assessment.state == .occupied, assessment.lifecycle == .observed else { reset(); return nil }
        if let event = assessment.event, event.frameID == frame.frameID,
           event.sessionID == frame.sessionID, event.revision == frame.revision,
           event.capturedUptimeMS == frame.capturedUptimeMS, event.isFresh(at: now) { pending = event }
        guard let event = pending, event.sessionID == frame.sessionID, event.revision == frame.revision,
              now >= event.capturedUptimeMS, now - event.capturedUptimeMS < 8_000,
              assessment.trackID == event.trackID, assessment.direction == event.direction,
              let evidence = assessment.evidence, evidence.detectedLabel == event.evidence.detectedLabel else {
            reset(); return nil
        }
        return MobileRiskEvent(id: event.id, sessionID: frame.sessionID, frameID: frame.frameID,
            revision: frame.revision, capturedUptimeMS: frame.capturedUptimeMS, trackID: event.trackID,
            level: assessment.level, direction: event.direction, text: assessment.text,
            evidence: evidence, reasonCodes: event.reasonCodes)
    }
}
