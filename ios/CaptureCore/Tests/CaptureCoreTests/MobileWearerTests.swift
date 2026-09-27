import XCTest
@testable import CaptureCore

final class MobileWearerTests: XCTestCase {
    func person(_ x: Double = 0.4) -> MobileDetection { .init(label:"person",confidence:0.9,x:x,y:0.25,width:0.15,height:0.65) }
    func frame(_ boxes:[MobileDetection],_ time:Double = 0,revision:UInt64 = 0) -> MobileFrameResult {
        .init(sessionID:"wearer",frameID:UInt64(time),capturedUptimeMS:time,revision:revision,detections:boxes)
    }
    func role(_ f:MobileFrameResult,_ index:Int = 0) -> MobileWearerObservation { .init(frame:f,state:.tracked,detectionIndex:index,reason:"test") }
    func testExcludeOnlyExplicitSameFramePerson() {
        let f=frame([person(),person(0.05)])
        XCTAssertEqual(role(f).environment(in:f).detections.count,1)
        XCTAssertEqual(role(f).environment(in:f).detections.first?.x,0.05)
        XCTAssertEqual(role(f).environment(in:frame(f.detections,1)).detections.count,2)
        XCTAssertEqual(role(f).environment(in:frame(f.detections,revision:1)).detections.count,2)
        XCTAssertEqual(MobileWearerObservation(frame:f,state:.lost,reason:"lost").environment(in:f).detections.count,2)
    }
    func testWeakerDuplicateOfSelectedBodyDoesNotBecomeAnotherObstacle() {
        let user=MobileDetection(label:"person",confidence:0.97,x:0.480,y:0.375,width:0.083,height:0.484)
        let duplicate=MobileDetection(label:"person",confidence:0.59,x:0.443,y:0.359,width:0.101,height:0.514)
        let independent=MobileDetection(label:"person",confidence:0.9,x:0.469,y:0.383,width:0.085,height:0.48)
        let f=frame([user,duplicate,person(0.05)])
        XCTAssertEqual(MobileWearerObservation.select(prediction:independent,detections:f.detections),0)
        XCTAssertEqual(role(f).environment(in:f).detections,[person(0.05)])
        var realOther=duplicate;realOther.confidence=0.95
        XCTAssertNil(MobileWearerObservation.select(prediction:independent,detections:[user,realOther]))
    }
    func testDuplicateUserStaysOutOfRiskAndDescriptionWithoutChangingDetections() {
        let user = MobileDetection(label:"person",confidence:0.97,x:0.480,y:0.375,width:0.083,height:0.484)
        let duplicate = MobileDetection(label:"person",confidence:0.59,x:0.443,y:0.359,width:0.101,height:0.514)
        let cars = [0.05,0.75].map { MobileDetection(label:"car",confidence:0.9,x:$0,y:0.3,width:0.2,height:0.4) }
        let corridor = [MobilePoint(x:0.05,y:0.1),.init(x:0.95,y:0.1),.init(x:0.95,y:1),.init(x:0.05,y:1)]
        var risk = LocalRiskEngine(), scene = LocalSceneDescriber()
        for time in stride(from:0.0,through:2000,by:200) {
            let ownFrame = frame([user,duplicate],time)
            let assessment = risk.update(frame:role(ownFrame).environment(in:ownFrame),nowUptimeMS:time,corridor:corridor)
            XCTAssertNil(assessment.event)
            XCTAssertEqual(assessment.level,.none)
            XCTAssertEqual(ownFrame.detections,[user,duplicate])
            let sceneFrame = frame([user,duplicate]+cars,time)
            scene.update(frame:sceneFrame,nowUptimeMS:time,wearer:role(sceneFrame))
        }
        let description = scene.describe(nowUptimeMS:2000)
        XCTAssertEqual(description.objects.map(\.kind),["car"])
        XCTAssertEqual(description.objects.first?.count,2)
    }
    func testWalkingExcludesUserDuplicatesAndStillWarnsForOtherPedestrian() {
        let user = MobileDetection(label:"person",confidence:0.97,x:0.480,y:0.375,width:0.083,height:0.484)
        let duplicate = MobileDetection(label:"person",confidence:0.59,x:0.443,y:0.359,width:0.101,height:0.514)
        let passerby = MobileDetection(label:"person",confidence:0.9,x:0.30,y:0.78,width:0.08,height:0.1)
        let boundary = [MobilePoint(x:0.1,y:0.1),.init(x:0.9,y:0.1),.init(x:0.9,y:0.95),.init(x:0.1,y:0.95)]
        for hasOtherPerson in [false,true] {
            var planner = MobileWalkingPlanner()
            var result: MobileWalkingObservation?
            for time in [0.0,400,800] {
                let raw = frame([user,duplicate]+(hasOtherPerson ? [passerby] : []),time)
                var path = MobilePathObservation(frame:raw,state:.inside,reason:"test",
                    foot:.init(x:user.x+user.width/2,y:user.y+user.height),boundary:boundary,eventText:nil)
                path.person = user
                result = planner.update(frame:role(raw).environment(in:raw),path:path,rearFollowing:true,now:time)
            }
            if hasOtherPerson {
                XCTAssertEqual(result?.caution,.left)
                XCTAssertEqual(result?.action,.straight)
                XCTAssertEqual(result?.event,true)
            } else {
                XCTAssertNil(result?.action)
                XCTAssertEqual(result?.event,false)
            }
        }
    }
    func testIndependentMatchRejectsAmbiguityAndOverlap() {
        XCTAssertEqual(MobileWearerObservation.select(prediction:person(),detections:[person(0.05),person()]),1)
        XCTAssertNil(MobileWearerObservation.select(prediction:person(),detections:[person(),person(0.42)]))
        XCTAssertNil(MobileWearerObservation.select(prediction:person(),detections:[person(0.05)]))
    }
    func testWearerAndTwoCarsAcrossDirections() {
        var scene=LocalSceneDescriber()
        let boxes=[person()]+[0.05,0.75].map { MobileDetection(label:"car",confidence:0.9,x:$0,y:0.3,width:0.2,height:0.4) }
        for t in [0.0,200,400] { let f=frame(boxes,t);scene.update(frame:f,nowUptimeMS:t,wearer:role(f)) }
        let result=scene.describe(nowUptimeMS:450)
        XCTAssertEqual(result.objects.map(\.kind),["car"])
        XCTAssertEqual(result.objects.first?.count,2)
        XCTAssertTrue(result.text.contains("two cars"))
        XCTAssertTrue(result.text.contains("left"));XCTAssertTrue(result.text.contains("right"))
        XCTAssertFalse(result.text.contains("person"))
    }
    func testLostWearerDescriptionKeepsCarsWithoutTrackingDisclaimer() {
        var scene = LocalSceneDescriber()
        let boxes = [person()] + [0.05, 0.7].map { MobileDetection(label:"car",confidence:0.9,x:$0,y:0.4,width:0.2,height:0.3) }
        for time in [0.0, 200, 400, 600] {
            let f = frame(boxes,time)
            scene.update(frame:f,nowUptimeMS:time,wearer:.init(frame:f,state:.lost,reason:"lost"))
        }
        let result = scene.describe(nowUptimeMS:600)
        XCTAssertEqual(result.objects.first(where: { $0.kind == "car" })?.count,2)
        XCTAssertFalse(result.objects.contains { $0.kind == "person" })
        XCTAssertTrue(result.text.contains("two cars"))
        XCTAssertFalse(result.text.lowercased().contains("tracking"))
        XCTAssertFalse(result.text.lowercased().contains("counted"))
    }

    func testOtherPedestrianRemainsAndLossClearsOldPeopleCount() {
        var scene=LocalSceneDescriber()
        for t in [0.0,200,400] { let f=frame([person(),person(0.05)],t);scene.update(frame:f,nowUptimeMS:t,wearer:role(f)) }
        XCTAssertEqual(scene.describe(nowUptimeMS:450).objects.first?.count,1)
        let f=frame([person(),person(0.05)],600)
        scene.update(frame:f,nowUptimeMS:600,wearer:.init(frame:f,state:.lost,reason:"occluded"))
        let result=scene.describe(nowUptimeMS:650)
        XCTAssertTrue(result.objects.isEmpty)
        XCTAssertFalse(result.text.contains("People are not counted"))
        XCTAssertFalse(result.text.contains("User tracking unavailable"))
    }
    func testSelectedUserDoesNotCreateRiskButOtherPersonStillDoes() {
        var wearerOnly=LocalRiskEngine(),otherPerson=LocalRiskEngine()
        var own:MobileRiskAssessment?,other:MobileRiskAssessment?
        for t in stride(from:0.0,through:2000,by:200) {
            let f=frame([person()],t)
            own=wearerOnly.update(frame:role(f).environment(in:f),nowUptimeMS:t,corridor:[.init(x:0.2,y:0.1),.init(x:0.8,y:0.1),.init(x:0.95,y:1),.init(x:0.05,y:1)])
            let p=frame([person(0.05),person()],t)
            other=otherPerson.update(frame:role(p).environment(in:p),nowUptimeMS:t,corridor:[.init(x:0.2,y:0.1),.init(x:0.8,y:0.1),.init(x:0.95,y:1),.init(x:0.05,y:1)])
        }
        XCTAssertEqual(own?.level,MobileRiskLevel.none)
        XCTAssertNotEqual(other?.level,MobileRiskLevel.none)
    }
}
