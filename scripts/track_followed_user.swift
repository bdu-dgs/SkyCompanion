import Foundation
import AVFoundation
import CoreImage
import ImageIO
import CaptureCore
// Uses an explicitly reviewed detection index; never automatically chooses a person.
// Usage: track_followed_user <detections.json> <video> <out.json> <first-frame-person-index> [stride] [phase]
@main struct Check {
 struct Row:Decodable {let second:Double;let detections:[MobileDetection]}
 struct Out:Encodable {let second:Double;let state:String;let index:Int?;let reason:String}
 static func main() throws {
 let input=try JSONDecoder().decode([Row].self,from:Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1])))
 let asset=AVURLAsset(url:URL(fileURLWithPath:CommandLine.arguments[2]))
 let gen=AVAssetImageGenerator(asset:asset);gen.appliesPreferredTrackTransform=true;gen.requestedTimeToleranceBefore = .zero;gen.requestedTimeToleranceAfter = .zero
 let original=try gen.copyCGImage(at:.zero,actualTime:nil)
 let context=CIContext(options:[.useSoftwareRenderer:true,.cacheIntermediates:false])
 let scale=min(1,640.0/Double(original.width))
 let preview=CIImage(cgImage:original).transformed(by:.init(scaleX:scale,y:scale))
 let first=context.createCGImage(preview,from:preview.extent)!
 let data=NSMutableData();let dest=CGImageDestinationCreateWithData(data,"public.jpeg" as CFString,1,nil)!
 CGImageDestinationAddImage(dest,first,[kCGImageDestinationLossyCompressionQuality:0.6] as CFDictionary);CGImageDestinationFinalize(dest)
 let index=Int(CommandLine.arguments[4])!
 guard input[0].detections.indices.contains(index), input[0].detections[index].label == "person" else {
  fatalError("The selected index must refer to a person in the first frame.")
 }
 let selected=input[0].detections[index]
 let stride=CommandLine.arguments.count>5 ? max(1,Int(CommandLine.arguments[5])!) : 1
 let phase=CommandLine.arguments.count>6 ? Int(CommandLine.arguments[6])! : 0
 let tracker=try LocalWearerTracker(configuration:.init(referenceJPEG:data as Data,person:selected))
 var rows=[Out]()
 for (i,row) in input.enumerated() {
  if i % stride != phase {
   rows.append(Out(second:row.second,state:"not_sampled",index:nil,reason:"Sampling scenario")); continue
  }
  let cg=try gen.copyCGImage(at:CMTime(seconds:row.second,preferredTimescale:600),actualTime:nil)
  let frame=MobileFrameResult(sessionID:"review",frameID:UInt64(i+1),capturedUptimeMS:row.second*1000,revision:1,detections:row.detections)
  let tracked=tracker.process(image:CIImage(cgImage:cg),frame:frame,nowUptimeMS:row.second*1000)
  rows.append(Out(second:row.second,state:tracked.state.rawValue,index:tracked.matchedIndex(in:frame),reason:tracked.reason))
 }
 try JSONEncoder().encode(rows).write(to:URL(fileURLWithPath:CommandLine.arguments[3]))
 }
}
