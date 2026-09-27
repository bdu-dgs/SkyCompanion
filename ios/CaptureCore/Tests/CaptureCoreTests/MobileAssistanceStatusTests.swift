import XCTest
@testable import CaptureCore

final class MobileAssistanceStatusTests: XCTestCase {
    func active() -> MobileAssistanceSnapshot {
        var s = MobileAssistanceSnapshot()
        s.phase = .running; s.sessionID = "current"; s.revision = 2; s.analyzing = true; s.riskAvailable = true
        s.requiresVoiceSession = true; s.listening = true
        s.frame = .init(sessionID:"current",frameID:10,capturedUptimeMS:1_000,revision:2,detections:[.init(label:"person",confidence:0.9,x:0.4,y:0.2,width:0.2,height:0.6)])
        return s
    }
    func testHealthyAndMutedAreOperationalNotSafeClaims() {
        var s=active()
        XCTAssertEqual(s.status(at:1_200),.active)
        XCTAssertEqual(s.status(at:1_200).speech(),"Analyzing. Obstacle alerts are on.")
        s.muted=true
        XCTAssertEqual(s.status(at:1_200),.muted)
        XCTAssertEqual(s.status(at:1_200).speech(),"Analyzing. Spoken alerts are off. Say SkyCompanion unmute to enable them.")
        for state in MobileAssistanceStatus.allCases {
            XCTAssertFalse(state.speech().contains("safe"))
        }
    }
    func testFreshnessUsesCaptureTimeAndCurrentSessionNotRecentDelivery() {
        var s=active(); s.muted=true
        XCTAssertEqual(s.status(at:2_499),.muted)
        XCTAssertEqual(s.status(at:2_500),.interrupted)
        XCTAssertEqual(s.status(at:999),.interrupted)
        XCTAssertEqual(s.status(at:Double.nan),.interrupted)
        s.frame?.sessionID="previous";XCTAssertEqual(s.status(at:1_200),.interrupted)
        s=active();s.revision=3;XCTAssertEqual(s.status(at:1_200),.interrupted)
        s=active();s.sourceConnected=false;XCTAssertEqual(s.status(at:1_200),.interrupted)
    }
    func testTrackingFailureBeatsMuteAndNeverHidesVideoFailure() {
        var s=active();s.wearerRequired=true;s.muted=true
        s.wearer = .init(frame:s.frame!,state:.lost,reason:"overlap")
        XCTAssertEqual(s.status(at:1_200),.trackingLost)
        XCTAssertEqual(s.status(at:1_200).speech(),"I cannot confirm your position. Direction guidance is paused.")
        XCTAssertEqual(s.status(at:2_500),.interrupted)
        s.wearer = .init(frame:s.frame!,state:.tracked,detectionIndex:0,reason:"tracked")
        XCTAssertEqual(s.status(at:1_200),.muted)
        s.frame?.frameID=11;XCTAssertEqual(s.status(at:1_200),.trackingLost)
    }
    func testRequiredFollowedUserCannotEnableDirectionAlertsBeforeSelection() {
        var s = active(); s.wearerRequired = true
        XCTAssertEqual(s.status(at:1_200),.trackingLost)
        s.wearer = .init(frame:s.frame!,state:.notSelected,reason:"Awaiting user selection")
        XCTAssertEqual(s.status(at:1_200),.trackingLost)
        s.wearer = .init(frame:s.frame!,state:.tracked,detectionIndex:0,reason:"Explicit selected user")
        XCTAssertEqual(s.status(at:1_200),.active)
    }
    func testPausedWaitingAndIdleDoNotBecomeHealthy() {
        var s=active()
        s.phase = .paused;XCTAssertEqual(s.status(at:1_200),.paused)
        s.phase = .waiting;XCTAssertEqual(s.status(at:1_200),.waiting)
        s.phase = .idle;XCTAssertEqual(s.status(at:1_200),.idle)
        s.phase = .unavailable;s.failure = .interrupted;XCTAssertEqual(s.status(at:1_200),.interrupted)
        s=active();s.listening=false;XCTAssertEqual(s.status(at:1_200),.audioUnavailable)
        s=active();s.riskAvailable=false;XCTAssertEqual(s.status(at:1_200),.unavailable)
    }
    func testPathHealthIsIndependentOfUserIdentity() {
        var s=active();s.pathRequired=true
        XCTAssertEqual(s.status(at:1_200),.pathUnavailable)
        s.path = .init(frame:s.frame!,state:.inside,reason:"",foot:.init(x:0.5,y:0.8),boundary:[],eventText:nil)
        XCTAssertEqual(s.status(at:1_200),.active)
        s.path = .init(frame:s.frame!,state:.unknown,reason:"registration",foot:nil,boundary:[],eventText:nil)
        XCTAssertEqual(s.status(at:1_200),.pathUnavailable)
    }
    func testFaultIsOncePerEpisodeAndRejectedSpeechCanRetry() {
        var gate=MobileStatusAnnouncements()
        XCTAssertEqual(gate.observe(.interrupted,now:0),.interrupted)
        XCTAssertEqual(gate.observe(.interrupted,now:250),.interrupted) // not yet delivered
        gate.didStart(.interrupted)
        for t in [500.0,1_000,5_000,30_000] { XCTAssertNil(gate.observe(.interrupted,now:t)) }
        XCTAssertEqual(gate.observe(.trackingLost,now:30_100),.trackingLost)
        gate.didStart(.trackingLost)
        XCTAssertNil(gate.observe(.interrupted,now:30_200))
        XCTAssertNil(gate.observe(.active,now:31_000))
        XCTAssertNil(gate.observe(.interrupted,now:31_100)) // brief recovery does not re-arm
        XCTAssertNil(gate.observe(.muted,now:32_000))
        XCTAssertNil(gate.observe(.muted,now:33_000))
        XCTAssertEqual(gate.observe(.interrupted,now:33_001),.interrupted)
    }
    func testEnglishQueriesAndRecoveryRequireAnExplicitWakePhrase() {
        for q in ["SkyCompanion, are you working?", "Sky Companion are you working", "SKYCOMPANION STATUS", "SkyCompanion is it working", "SkyCompanion can I rely on alerts"] {
            XCTAssertEqual(MobileVoiceCommand.parse(q), .status, q)
        }
        for q in ["SkyCompanion unmute", "Sky Companion resume alerts"] {
            XCTAssertEqual(MobileVoiceCommand.parse(q), .unmute, q)
        }
        for q in ["are you working", "unmute", "resume alerts", "do not unmute", "SkyCompanion are you working do not answer", "I heard SkyCompanion status on TV"] {
            XCTAssertNil(MobileVoiceCommand.parse(q), q)
        }
    }
}
