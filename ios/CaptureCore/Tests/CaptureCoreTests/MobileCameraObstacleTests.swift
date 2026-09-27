import XCTest
@testable import CaptureCore

final class MobileCameraObstacleTests: XCTestCase {
    let corridor: [MobilePoint] = [.init(x:0.02,y:0.1),.init(x:0.98,y:0.1),.init(x:0.98,y:1),.init(x:0.02,y:1)]
    let user = MobileDetection(label:"person",confidence:0.95,x:0.42,y:0.2,width:0.16,height:0.65)
    let car = MobileDetection(label:"car",confidence:0.92,x:0.08,y:0.45,width:0.22,height:0.4)
    func frame(_ t: Double, _ boxes: [MobileDetection]) -> MobileFrameResult {
        .init(sessionID:"drone",frameID:UInt64(t)+1,capturedUptimeMS:t,revision:4,detections:boxes)
    }
    func wearer(_ f: MobileFrameResult, _ state: MobileWearerState) -> MobileWearerObservation {
        .init(frame:f,state:state,detectionIndex:state == .tracked ? 0 : nil,reason:"test")
    }
    func snapshot(_ f: MobileFrameResult, _ state: MobileWearerState) -> MobileAssistanceSnapshot {
        var s = MobileAssistanceSnapshot()
        s.phase = .running; s.sessionID = f.sessionID; s.revision = f.revision; s.frame = f
        s.analyzing = true; s.listening = true; s.requiresVoiceSession = true; s.riskAvailable = true
        s.wearerRequired = true; s.wearer = wearer(f,state)
        return s
    }
    func testUnknownUserDoesNotSilenceConfirmedCarOrChangeDetections() {
        for state in [MobileWearerState.lost,.notSelected] {
            var monitor = MobileCameraObstacleMonitor()
            var result: MobileRiskAssessment?
            for t in [0.0,200,400] {
                let f = frame(t,[user,car])
                result = monitor.update(frame:f,wearer:wearer(f,state),wearerRequired:true,nowUptimeMS:t,corridor:corridor)
                XCTAssertEqual(f.detections,[user,car])
            }
            XCTAssertEqual(result?.event?.evidence.detectedLabel,"car")
            XCTAssertEqual(result?.event?.direction,.left)
            XCTAssertEqual(result?.health,.available)
        }
    }
    func testUnknownPeopleAndSelectedUserNeverCreateSelfAlert() {
        let other = MobileDetection(label:"person",confidence:0.9,x:0.1,y:0.25,width:0.2,height:0.6)
        for state in [MobileWearerState.lost,.notSelected,.tracked] {
            var monitor = MobileCameraObstacleMonitor()
            for t in [0.0,200,400,800,1200] {
                let f = frame(t,state == .tracked ? [user] : [user,other])
                let r = monitor.update(frame:f,wearer:wearer(f,state),wearerRequired:true,nowUptimeMS:t,corridor:corridor)
                XCTAssertNil(r.event); XCTAssertEqual(r.level,.none)
            }
        }
    }
    func testTrackedOtherPedestrianStillWarnsAndLossClearsOldPersonTracks() {
        let other = MobileDetection(label:"person",confidence:0.9,x:0.1,y:0.25,width:0.2,height:0.6)
        var monitor = MobileCameraObstacleMonitor()
        var events = [MobileRiskEvent]()
        for t in [0.0,200,400] {
            let f = frame(t,[user,other])
            let r = monitor.update(frame:f,wearer:wearer(f,.tracked),wearerRequired:true,nowUptimeMS:t,corridor:corridor)
            if let e = r.event { events.append(e) }
        }
        XCTAssertEqual(events.last?.direction,.left); XCTAssertEqual(events.last?.evidence.detectedLabel,"person")
        for t in [600.0,800,1000] {
            let f = frame(t,[user,other])
            let r = monitor.update(frame:f,wearer:wearer(f,.lost),wearerRequired:true,nowUptimeMS:t,corridor:corridor)
            XCTAssertNil(r.event); XCTAssertEqual(r.level,.none); XCTAssertNotEqual(r.lifecycle,.occludedUnresolved)
        }
    }
    func testOrdinaryLocalVideoWithoutWearerRequirementPreservesPeopleAlerts() {
        var monitor = MobileCameraObstacleMonitor()
        var last: MobileRiskAssessment?
        for t in [0.0,200,400] {
            last = monitor.update(frame:frame(t,[user]),wearer:nil,wearerRequired:false,nowUptimeMS:t,corridor:corridor)
        }
        XCTAssertEqual(last?.event?.evidence.detectedLabel,"person")
    }
    func testWalkingFailureRequiresFreshCameraConfirmation() {
        var monitor = MobileCameraObstacleMonitor()
        var last: MobileRiskAssessment?
        for t in [0.0,200,400,600,800,1000] {
            let f = frame(t,[user,car])
            last = monitor.update(frame:f,wearer:wearer(f,.tracked),wearerRequired:true,
                                  walkingActive:t < 600,nowUptimeMS:t,corridor:corridor)
            if t == 600 { XCTAssertNil(last?.event) }
        }
        XCTAssertEqual(last?.event?.evidence.detectedLabel,"car")
    }
    func testCapabilitySplitNeverAuthorizesSteeringOrStaleCameraAlerts() {
        let f = frame(1000,[user,car])
        var s = snapshot(f,.lost)
        XCTAssertTrue(s.cameraAlertsAvailable(at:1100)); XCTAssertTrue(s.cameraOnlyAlerts(at:1100))
        XCTAssertFalse(s.walkingGuidanceAvailable(at:1100))
        XCTAssertTrue(s.speech(at:1100).contains("people alerts and walking guidance are paused"))
        s.muted = true
        XCTAssertTrue(s.cameraAlertsAvailable(at:1100)) // mute is enforced separately by speech delivery
        XCTAssertTrue(s.speech(at:1100).contains("Spoken alerts are off"))
        for mode in 0..<7 {
            var failed = s
            switch mode {
            case 0: failed.phase = .paused
            case 1: failed.sourceConnected = false
            case 2: failed.listening = false
            case 3: failed.riskAvailable = false
            case 4: failed.sessionID = "old"
            case 5: failed.revision += 1
            default: failed.analyzing = false
            }
            XCTAssertFalse(failed.cameraAlertsAvailable(at:1100))
        }
        XCTAssertFalse(s.cameraAlertsAvailable(at:2500)); XCTAssertFalse(s.cameraAlertsAvailable(at:999))
        s = snapshot(f,.tracked); s.pathRequired = true
        XCTAssertTrue(s.cameraOnlyAlerts(at:1100)); XCTAssertFalse(s.walkingGuidanceAvailable(at:1100))
        s.path = .init(frame:f,state:.inside,reason:"confirmed",foot:.init(x:0.5,y:0.8),boundary:corridor,eventText:nil)
        XCTAssertTrue(s.walkingGuidanceAvailable(at:1100)); XCTAssertFalse(s.cameraOnlyAlerts(at:1100))
    }
    func testTrackingNoticeCannotPermanentlyConsumeFirstCameraCaution() throws {
        var monitor = MobileCameraObstacleMonitor(), retry = MobileCameraAlertRetry(), gate = MobileGuidanceGate()
        var spoken: MobileRiskEvent?
        for t in stride(from:0.0,through:2400,by:200) {
            let f = frame(t,[user,car])
            let risk = monitor.update(frame:f,wearer:wearer(f,.lost),wearerRequired:true,nowUptimeMS:t,corridor:corridor)
            guard let event = retry.candidate(frame:f,assessment:risk,now:t,enabled:true) else { continue }
            let currentSpeech: Int? = t < 2000 ? 3 : nil // one-time loss notice
            guard MobileGuidanceGate.mayStartSpeech(incoming:event.level.rawValue,current:currentSpeech) else { continue }
            if case .play = gate.receive(event,nowUptimeMS:t,sessionID:f.sessionID,revision:f.revision,enabled:true) { spoken = event }
            retry.reset()
        }
        let event = try XCTUnwrap(spoken)
        XCTAssertEqual(event.capturedUptimeMS,2000)
        XCTAssertEqual(event.expiresUptimeMS,3500) // fresh evidence, not an extended old deadline
        XCTAssertEqual(event.evidence.detectedLabel,"car")
    }
    func testPendingCameraCautionIsDroppedWhenOccludedOrSessionChanges() {
        for discontinuity in 0..<3 {
            var monitor = MobileCameraObstacleMonitor(), retry = MobileCameraAlertRetry()
            for t in [0.0,200,400] {
                let f = frame(t,[user,car])
                let r = monitor.update(frame:f,wearer:wearer(f,.lost),wearerRequired:true,nowUptimeMS:t,corridor:corridor)
                _ = retry.candidate(frame:f,assessment:r,now:t,enabled:true)
            }
            var f = frame(600,discontinuity == 0 ? [user] : [user,car])
            if discontinuity == 1 { f.sessionID = "new" }
            let r = monitor.update(frame:f,wearer:wearer(f,.lost),wearerRequired:true,nowUptimeMS:600,corridor:corridor)
            XCTAssertNil(retry.candidate(frame:f,assessment:r,now:discontinuity == 2 ? 2100 : 600,enabled:true))
        }
    }
    func testCameraSpeechNamesFrameDirectionWithoutSteeringOrClassNames() {
        XCTAssertEqual(MobileAlertSpeech.cameraObstacle(direction:.left),"Caution. Camera left.")
        XCTAssertEqual(MobileAlertSpeech.cameraObstacle(direction:.right),"Caution. Camera right.")
        XCTAssertEqual(MobileAlertSpeech.cameraObstacle(direction:.ahead),"Caution. Camera front.")
    }
}
