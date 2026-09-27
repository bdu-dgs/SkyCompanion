import XCTest
@testable import CaptureCore
final class MobileWalkingPlannerTests:XCTestCase {
    let person=MobileDetection(label:"person",confidence:0.9,x:0.46,y:0.60,width:0.08,height:0.20)
    let wide=[MobilePoint(x:0.1,y:0.1),.init(x:0.9,y:0.1),.init(x:0.9,y:0.95),.init(x:0.1,y:0.95)]
    func obstacle(_ x:Double,_ y:Double,_ w:Double = 0.08,_ h:Double = 0.06) -> MobileDetection {
        .init(label:"bollard",confidence:0.8,x:x,y:y,width:w,height:h)
    }
    func update(_ planner:inout MobileWalkingPlanner,_ time:Double,_ objects:[MobileDetection], boundary:[MobilePoint]? = nil, rear:Bool = true, state:MobilePathState = .inside) -> MobileWalkingObservation {
        let frame=MobileFrameResult(sessionID:"s",frameID:UInt64(time),capturedUptimeMS:time,revision:1,detections:[person]+objects)
        var path=MobilePathObservation(frame:frame,state:state,reason:"test",foot:.init(x:0.5,y:0.8),boundary:boundary ?? wide,eventText:nil)
        path.person=person
        return planner.update(frame:frame,path:path,rearFollowing:rear,now:time)
    }
    func stable(_ objects:[MobileDetection], boundary:[MobilePoint]? = nil) -> MobileWalkingObservation {
        var p=MobileWalkingPlanner();var result:MobileWalkingObservation!
        for t in [0.0,400,800] { result=update(&p,t,objects,boundary:boundary) }
        return result
    }
    func testNearSideHazardsAllowStraightOnlyAfterConfirmation() {
        XCTAssertEqual(stable([obstacle(0.28,0.77)]).speech,"Caution left. Go straight.")
        XCTAssertEqual(stable([obstacle(0.64,0.77)]).speech,"Caution right. Go straight.")
        var p=MobileWalkingPlanner()
        XCTAssertFalse(update(&p,0,[obstacle(0.28,0.77)]).confirmed)
    }
    func testForwardObstacleChoosesOnlyAvailableSide() {
        let front=obstacle(0.46,0.58)
        XCTAssertEqual(stable([front,obstacle(0.64,0.57,0.09,0.20)]).speech,"Caution front. Keep left.")
        XCTAssertEqual(stable([front,obstacle(0.27,0.57,0.09,0.20)]).speech,"Caution front. Keep right.")
    }
    func testTwoBlockedSidesAndNarrowRegionCannotSteer() {
        XCTAssertEqual(stable([obstacle(0.46,0.58),obstacle(0.27,0.57,0.09,0.20),obstacle(0.64,0.57,0.09,0.20)]).action,.checkPath)
        let narrow=[MobilePoint(x:0.42,y:0.1),.init(x:0.58,y:0.1),.init(x:0.58,y:0.95),.init(x:0.42,y:0.95)]
        XCTAssertEqual(stable([obstacle(0.46,0.58)],boundary:narrow).action,.checkPath)
    }
    func testFrontHasPriorityOverNearSideAndOwnBodyIsExcluded() {
        XCTAssertNil(stable([]).action)
        XCTAssertEqual(stable([obstacle(0.28,0.77),obstacle(0.46,0.58)]).caution,.ahead)
        XCTAssertNotEqual(stable([obstacle(0.28,0.77),obstacle(0.46,0.58)]).action,.straight)
    }
    func testUnknownHeadingLostUserAndDisappearingObstacleCannotAuthorizeMovement() {
        var p=MobileWalkingPlanner()
        XCTAssertNil(update(&p,0,[obstacle(0.28,0.77)],rear:false).action)
        XCTAssertEqual(update(&p,400,[obstacle(0.28,0.77)],state:.unknown).action,.checkPath)
        _=update(&p,800,[obstacle(0.28,0.77)])
        XCTAssertEqual(update(&p,1200,[]).action,.checkPath)
    }

    func testStaleOrWrongFrameCannotProduceMovement() {
        var planner=MobileWalkingPlanner()
        let frame=MobileFrameResult(sessionID:"s",frameID:1,capturedUptimeMS:0,revision:1,detections:[person,obstacle(0.28,0.77)])
        var path=MobilePathObservation(frame:frame,state:.inside,reason:"test",foot:.init(x:0.5,y:0.8),boundary:wide,eventText:nil)
        path.person=person
        XCTAssertEqual(planner.update(frame:frame,path:path,rearFollowing:true,now:1500).action,.checkPath)
        let other=MobileFrameResult(sessionID:"other",frameID:1,capturedUptimeMS:0,revision:1,detections:frame.detections)
        XCTAssertEqual(planner.update(frame:other,path:path,rearFollowing:true,now:0).action,.checkPath)
    }
    func testBoundaryAlertsRemainEvenWithoutAnObstacle() {
        var p=MobileWalkingPlanner()
        XCTAssertEqual(update(&p,0,[],state:.outside).action,.checkPath)
        XCTAssertEqual(update(&p,400,[],state:.nearBoundary).action,.checkPath)
    }
    func testTripSummaryCountsObstacleSpeechButNotLostTrackingOrBoundaryAdvice() {
        XCTAssertTrue(stable([obstacle(0.46,0.58)]).obstacleRelated)
        XCTAssertTrue(stable([obstacle(0.28,0.77)]).obstacleRelated)
        XCTAssertFalse(stable([]).obstacleRelated)
        var planner = MobileWalkingPlanner()
        XCTAssertFalse(update(&planner,0,[],state:.outside).obstacleRelated)
        XCTAssertFalse(update(&planner,400,[],state:.unknown).obstacleRelated)
    }
    func testChangeRevokesPreviousInstructionBeforeNextMovementIsConfirmed() {
        var p=MobileWalkingPlanner();let side=obstacle(0.28,0.77)
        for t in [0.0,400,800] { _=update(&p,t,[side]) }
        let changed=update(&p,1200,[side,obstacle(0.46,0.58)])
        XCTAssertEqual(changed.action,.checkPath);XCTAssertTrue(changed.event)
        _=update(&p,1600,[side,obstacle(0.46,0.58)])
        let next=update(&p,2000,[side,obstacle(0.46,0.58)])
        XCTAssertNotEqual(next.action,.straight);XCTAssertTrue(next.event)
    }

    func testContinuousHazardDoesNotRepeatAndUnsafeChangeRevokesStraight() {
        var p=MobileWalkingPlanner();let side=obstacle(0.28,0.77)
        for t in [0.0,400,800] { _=update(&p,t,[side]) }
        for t in stride(from:1200.0,through:12000.0,by:400) { XCTAssertFalse(update(&p,t,[side]).event) }
        let blocked=update(&p,12400,[side,obstacle(0.2,0.57,0.6,0.16)])
        XCTAssertEqual(blocked.action,.checkPath);XCTAssertTrue(blocked.confirmed);XCTAssertTrue(blocked.event)
    }
    func testCurbContextDoesNotNagButConfirmedPathBoundaryStillWarns() {
        var curb = obstacle(0.2, 0.5, 0.25, 0.45); curb.label = "curb"
        XCTAssertNil(stable([curb]).action)
        var planner = MobileWalkingPlanner()
        for time in [0.0, 400, 800] { _ = update(&planner, time, [curb]) }
        XCTAssertNil(update(&planner, 1200, []).action) // A missing curb is not a lost obstacle event.
        let boundary = update(&planner, 1600, [curb], state: .nearBoundary)
        XCTAssertEqual(boundary.action, .checkPath)
        XCTAssertFalse(boundary.obstacleRelated)
    }

    func testQuietCurbStillBlocksAnUnverifiedTurn() {
        var curb = obstacle(0.26, 0.4, 0.1, 0.42); curb.label = "curb"
        let result = stable([obstacle(0.46, 0.58), obstacle(0.64, 0.57, 0.09, 0.20), curb])
        XCTAssertEqual(result.action, .checkPath) // Left curb and right pole leave no validated turn.
        XCTAssertEqual(result.speech, "Caution front. Check your path.")
    }

}
