import Foundation

/// Operational health only. No state certifies a clear or safe walking route.
public enum MobileAssistanceStatus: String, Sendable, CaseIterable {
    case active, muted, interrupted, trackingLost, pathUnavailable, unavailable, audioUnavailable
    case idle, waiting, paused
    public var isFault: Bool {
        [.interrupted, .trackingLost, .pathUnavailable, .unavailable, .audioUnavailable].contains(self)
    }
    public func speech() -> String {
        switch self {
        case .active: return "Analyzing. Obstacle alerts are on."
        case .muted: return "Analyzing. Spoken alerts are off. Say SkyCompanion unmute to enable them."
        case .interrupted: return "The video feed has stopped. Obstacle alerts are unavailable."
        case .trackingLost: return "I cannot confirm your position. Direction guidance is paused."
        case .pathUnavailable: return "The path is not confirmed. Direction guidance is paused."
        case .unavailable: return "Analysis is unavailable. Obstacle alerts are unavailable."
        case .audioUnavailable: return "Voice assistance has stopped. Check audio settings in SkyCompanion."
        case .idle: return "Assistance has not started. Connect a video source first."
        case .waiting: return "Waiting for an analyzed frame. Obstacle alerts are not active yet."
        case .paused: return "Analysis is paused. Obstacle alerts are unavailable."
        }
    }
}

public struct MobileAssistanceSnapshot: Sendable {
    public enum Phase: Sendable { case idle, waiting, running, paused, unavailable }
    public var phase: Phase = .idle
    public var failure: MobileAssistanceStatus = .unavailable
    public var sessionID = ""
    public var revision: UInt64 = 0
    public var frame: MobileFrameResult?
    public var analyzing = false
    public var sourceConnected = true
    public var requiresVoiceSession = false
    public var listening = false
    public var muted = false
    public var riskAvailable = false
    public var wearerRequired = false
    public var wearer: MobileWearerObservation?
    public var pathRequired = false
    public var path: MobilePathObservation?
    public init() {}
    /// Camera-relative obstacle evidence does not require user-relative steering.
    /// Mute remains a delivery preference and does not make visual evidence valid.
    public func cameraAlertsAvailable(at now: Double) -> Bool {
        guard phase == .running, analyzing, sourceConnected, riskAvailable,
              !requiresVoiceSession || listening, let frame,
              frame.sessionID == sessionID, frame.revision == revision,
              frame.isFresh(at: now) else { return false }
        return true
    }
    public func walkingGuidanceAvailable(at now: Double) -> Bool {
        cameraAlertsAvailable(at: now) && (!wearerRequired || wearer?.matchedIndex(in: frame!) != nil)
            && (!pathRequired || Self.pathAvailable(path, for: frame!, at: now))
    }
    public func cameraOnlyAlerts(at now: Double) -> Bool {
        cameraAlertsAvailable(at: now) && !walkingGuidanceAvailable(at: now)
    }
    public static func pathAvailable(_ path: MobilePathObservation?, for frame: MobileFrameResult, at now: Double) -> Bool {
        guard let path, path.sessionID == frame.sessionID, path.revision == frame.revision,
              frame.isFresh(at: now), path.capturedUptimeMS <= now, now-path.capturedUptimeMS < 1_500,
              [.inside, .nearBoundary, .outside].contains(path.state) else { return false }
        return true
    }
    public func speech(at now: Double) -> String {
        guard cameraOnlyAlerts(at: now) else { return status(at: now).speech() }
        let userUnknown = wearerRequired && wearer?.matchedIndex(in: frame!) == nil
        let reason = userUnknown ? "Your position is unconfirmed." : "The path is unconfirmed."
        if muted { return reason + " Spoken alerts are off. Say SkyCompanion unmute to enable camera alerts." }
        return reason + (userUnknown
            ? " Camera alerts remain on; people alerts and walking guidance are paused."
            : " Camera alerts remain on; walking guidance is paused.")
    }
    public func status(at now: Double) -> MobileAssistanceStatus {
        switch phase {
        case .idle: return .idle
        case .paused: return .paused
        case .waiting: return .waiting
        case .unavailable: return failure.isFault ? failure : .unavailable
        case .running: break
        }
        guard analyzing else { return .paused }
        guard sourceConnected, let frame, frame.sessionID == sessionID, frame.revision == revision,
              frame.isFresh(at: now) else { return .interrupted }
        guard !requiresVoiceSession || listening else { return .audioUnavailable }
        if wearerRequired && wearer?.matchedIndex(in: frame) == nil { return .trackingLost }
        if pathRequired {
            guard Self.pathAvailable(path, for: frame, at: now) else { return .pathUnavailable }
        }
        guard riskAvailable else { return .unavailable }
        return muted ? .muted : .active
    }
}

/// One announcement per continuous fault episode. Commit only at the speech-start callback.
/// A lower-priority fault cannot repeatedly replace an already announced higher-priority fault.
public struct MobileStatusAnnouncements: Sendable {
    private var announced = Set<MobileAssistanceStatus>()
    private var healthySince: Double?
    public init() {}
    public mutating func observe(_ status: MobileAssistanceStatus, now: Double) -> MobileAssistanceStatus? {
        if status == .active || status == .muted {
            if healthySince == nil { healthySince = now }
            if now-(healthySince ?? now) >= 1_000 { announced.removeAll() }
        } else { healthySince = nil }
        return status.isFault && !announced.contains(status) ? status : nil
    }
    public mutating func didStart(_ status: MobileAssistanceStatus) { announced.insert(status) }
}
