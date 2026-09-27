import XCTest
@testable import CaptureCore

final class MobileSceneReplyTests: XCTestCase {
    func frame(_ time: Double = 100) -> MobileFrameResult {
        .init(sessionID:"scene",frameID:1,capturedUptimeMS:time,revision:2,detections:[])
    }
    func summary(_ f: MobileFrameResult) -> MobileSceneSummary {
        .init(code:.sceneSummary,objects:[],text:"Two cars in the camera view.",sessionID:f.sessionID,
              frameID:f.frameID,revision:f.revision,capturedUptimeMS:f.capturedUptimeMS,directionBasis:.cameraImage)
    }
    func testDescriptionKeepsObservationDeadline() {
        let f = frame(), reply = MobileSceneReply.current(frame:f,summary:summary(f),running:true,now:300)
        XCTAssertEqual(reply?.text,"Two cars in the camera view.")
        XCTAssertEqual(reply?.expiresMS,1600)
        XCTAssertEqual(reply?.isObservation,true)
    }
    func testNearExpiredDescriptionWaitsInsteadOfStoppingSpeechEngine() {
        let f = frame()
        XCTAssertNil(MobileSceneReply.current(frame:f,summary:summary(f),running:true,now:1300))
        let fresh = frame(1300)
        XCTAssertEqual(MobileSceneReply.current(frame:fresh,summary:summary(fresh),running:true,now:1400)?.isObservation,true)
    }
    func testStalePausedMissingAndMismatchedViewsAnswerUnavailable() {
        let f = frame()
        let replies = [
            MobileSceneReply.current(frame:f,summary:summary(f),running:true,now:1700),
            MobileSceneReply.current(frame:f,summary:summary(f),running:false,now:300),
            MobileSceneReply.current(frame:nil,summary:nil,running:true,now:300),
            MobileSceneReply.current(frame:f,summary:summary(frame(200)),running:true,now:300)
        ]
        for reply in replies {
            XCTAssertEqual(reply?.isObservation,false)
            XCTAssertEqual(reply?.text,"A fresh camera view is unavailable.")
        }
    }
}
