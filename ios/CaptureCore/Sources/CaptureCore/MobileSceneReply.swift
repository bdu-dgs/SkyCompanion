import Foundation

/// Prepare explicit descriptions from a current, matching observation. A small
/// synthesis budget prevents starting work on a frame that is about to expire.
public struct MobileSceneReply: Sendable {
    public let text: String
    public let expiresMS: Double
    public let isObservation: Bool
    public static func unavailable(now: Double) -> Self {
        .init(text: "A fresh camera view is unavailable.", expiresMS: now + 3_000, isObservation: false)
    }
    public static func current(frame: MobileFrameResult?, summary: MobileSceneSummary?, running: Bool, now: Double) -> Self? {
        guard running, let frame, frame.isFresh(at: now), let summary,
              summary.sessionID == frame.sessionID, summary.revision == frame.revision,
              summary.frameID == frame.frameID, summary.capturedUptimeMS == frame.capturedUptimeMS,
              !summary.text.isEmpty else { return unavailable(now: now) }
        let deadline = frame.capturedUptimeMS + 1_500
        guard deadline - now >= 350 else { return nil } // Wait for a new frame, not a longer TTL.
        return .init(text: summary.text, expiresMS: deadline, isObservation: true)
    }
}
