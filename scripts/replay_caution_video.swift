// Offline diagnostic replay using shipping inference and risk rules. No model conversion.
import Foundation
import AVFoundation
import CoreImage
import CoreVideo
import CaptureCore
@main struct Replay {
 static func main() async throws {
 guard CommandLine.arguments.count == 4, let bundle = Bundle(path: CommandLine.arguments[1]) else {
  fatalError("Usage: replay_caution_video <model.bundle> <video> <output.json>")
 }
 let engine = try CoreMLVisionEngine(bundle: bundle, computeUnits:.cpuOnly)
 let asset=AVURLAsset(url:URL(fileURLWithPath:CommandLine.arguments[2]))
 let generator=AVAssetImageGenerator(asset:asset); generator.appliesPreferredTrackTransform=true
 generator.requestedTimeToleranceBefore = .zero; generator.requestedTimeToleranceAfter = .zero
 let context=CIContext(options:[.useSoftwareRenderer:true,.cacheIntermediates:false])
 var risk=LocalRiskEngine(), gate=MobileGuidanceGate()
 let corridor=[MobilePoint(x:0.35,y:0.45),MobilePoint(x:0.65,y:0.45),MobilePoint(x:0.9,y:1),MobilePoint(x:0.1,y:1)]
 struct Row: Codable { let second:Double; let detections:[MobileDetection]; let risk:MobileRiskAssessment; let gate:String?; let admitted:MobileRiskEvent? }
 var rows=[Row]()
 let duration=try await asset.load(.duration).seconds
 for i in 0..<Int(ceil(duration*5)) {
  let second=Double(i)/5
  let cg=try generator.copyCGImage(at:CMTime(seconds:second,preferredTimescale:600),actualTime:nil)
  let image=CIImage(cgImage:cg)
  var buffer:CVPixelBuffer?
  CVPixelBufferCreate(kCFAllocatorDefault,cg.width,cg.height,kCVPixelFormatType_32BGRA,[kCVPixelBufferIOSurfacePropertiesKey:[:]] as CFDictionary,&buffer)
  context.render(image,to:buffer!)
  let prediction=try engine.process(pixelBuffer:buffer!,orientation:.up,roi:CGRect(x:0,y:0,width:1,height:1))
  let frame=MobileFrameResult(sessionID:"replay",frameID:UInt64(i+1),capturedUptimeMS:second*1000,revision:0,detections:prediction.detections)
  let assessment=risk.update(frame:frame,nowUptimeMS:second*1000,corridor:corridor)
  gate.observe(assessment,nowUptimeMS:second*1000)
  var admitted:MobileRiskEvent?
  var decision:String?
  for candidate in assessment.event.map({ [$0] }) ?? [] {
   let result=gate.receive(candidate,nowUptimeMS:second*1000,sessionID:"replay",revision:0,enabled:true)
   decision=String(describing:result)
   if case .play = result { admitted=candidate;break }
  }
  rows.append(Row(second:second,detections:prediction.detections,risk:assessment,gate:decision,admitted:admitted))
 }
 let encoder=JSONEncoder();encoder.outputFormatting=[.sortedKeys]
 try encoder.encode(rows).write(to:URL(fileURLWithPath:CommandLine.arguments[3]))
 }
}
