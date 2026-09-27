import XCTest
@testable import CaptureCore

final class MobilePathDepthTests: XCTestCase {
    let boundary = [MobilePoint(x:0.2,y:0.1),MobilePoint(x:0.8,y:0.1),MobilePoint(x:0.8,y:0.9),MobilePoint(x:0.2,y:0.9)]
    func frame(_ time:Double, revision:UInt64 = 1) -> MobileFrameResult {
        .init(sessionID:"s",frameID:UInt64(time),capturedUptimeMS:time,revision:revision,detections:[])
    }
    func testContinuousConfirmationAndNoPeriodicRepeat() {
        var m = MobilePathMonitor()
        for time in stride(from:0.0,through:400.0,by:400) {
            XCTAssertEqual(m.update(frame:frame(time),foot:.init(x:0.9,y:0.5),boundary:boundary,reliable:true,now:time).state,.confirming)
        }
        let alert = m.update(frame:frame(800),foot:.init(x:0.9,y:0.5),boundary:boundary,reliable:true,now:800)
        XCTAssertEqual(alert.state,.outside); XCTAssertNotNil(alert.eventText)
        for time in stride(from:1200.0,through:16000.0,by:400) {
            XCTAssertNil(m.update(frame:frame(time),foot:.init(x:0.9,y:0.5),boundary:boundary,reliable:true,now:time).eventText)
        }
    }
    func testOcclusionDoesNotClearDepartureAndStaleCannotAlert() {
        var m = MobilePathMonitor()
        for time in [0.0,400,800] { _ = m.update(frame:frame(time),foot:.init(x:0.9,y:0.5),boundary:boundary,reliable:true,now:time) }
        let lost = m.update(frame:frame(1200),foot:nil,boundary:boundary,reliable:false,now:1200)
        XCTAssertEqual(lost.state,.unknown); XCTAssertFalse(lost.eventText?.contains("within") ?? false)
        XCTAssertEqual(m.update(frame:frame(1300),foot:.init(x:0.5,y:0.5),boundary:boundary,reliable:true,now:4000).state,.unknown)
    }
    func testGapsAndRevisionResetConfirmation() {
        var m = MobilePathMonitor()
        _ = m.update(frame:frame(0),foot:.init(x:0.9,y:0.5),boundary:boundary,reliable:true,now:0)
        _ = m.update(frame:frame(400),foot:.init(x:0.9,y:0.5),boundary:boundary,reliable:true,now:400)
        XCTAssertEqual(m.update(frame:frame(1400),foot:.init(x:0.9,y:0.5),boundary:boundary,reliable:true,now:1400).state,.confirming)
        XCTAssertEqual(m.update(frame:frame(1800,revision:2),foot:.init(x:0.9,y:0.5),boundary:boundary,reliable:true,now:1800).state,.confirming)
    }
    func testCrosswalkStripeGapsRemainInsideWholeCorridor() {
        XCTAssertTrue(MobilePathMonitor.contains(.init(x:0.5,y:0.55),polygon:boundary))
        XCTAssertFalse(MobilePathMonitor.validBoundary([boundary[0],boundary[2],boundary[1],boundary[3]]))
        XCTAssertFalse(MobilePathMonitor.validBoundary([.init(x:.nan,y:0)]+Array(boundary.dropFirst())))
    }
    func testNearBoundaryIsNotOutsideOrMeters() {
        var m = MobilePathMonitor(); var result: MobilePathObservation?
        for time in [0.0,400,800] { result=m.update(frame:frame(time),foot:.init(x:0.21,y:0.5),boundary:boundary,reliable:true,now:time) }
        XCTAssertEqual(result?.state,.nearBoundary)
    }
    func testDepthInvalidAndMixedSurfacesFailClosed() {
        XCTAssertNil(MobileDepthSample(detectionIndex:0,label:"person",values:[.nan,.infinity,0,-1]).rawMedianMeters)
        XCTAssertNil(MobileDepthSample(detectionIndex:0,label:"person",values:Array(repeating:1,count:20)+Array(repeating:10,count:20)).rawMedianMeters)
        let sample=MobileDepthSample(detectionIndex:0,label:"person",values:Array(repeating:3,count:40))
        XCTAssertEqual(sample.rawMedianMeters,3)
        let result=MobileDepthResult(frame:frame(0),completedMS:100,inferenceMS:100,samples:[sample],status:"test")
        XCTAssertEqual(result.validationState,"unvalidated")
        XCTAssertTrue(result.guidanceDistanceText.contains("unknown"))
        XCTAssertEqual(result.measurementReference,"camera_optical_axis")
    }
}
