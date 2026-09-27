// Offline scheduling comparison on cached native detections. No inference or audio playback.
import Foundation
import CaptureCore
@main struct Evaluate {
 struct Input:Decodable {let second:Double;let detections:[MobileDetection]}
 struct Spoken:Codable,Equatable {let second:Double;let direction:String;let label:String;let text:String}
 struct Role:Decodable {let state:String;let index:Int?}
 struct Run:Codable {let scenario:String;let speech:[Spoken]}
 static func main() throws {
 let input=try JSONDecoder().decode([Input].self,from:Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1])))
 let roles: [Role]? = CommandLine.arguments.count > 4 ? try JSONDecoder().decode([Role].self,from:Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[4]))) : nil
 let alternateRoles: [[Role]] = CommandLine.arguments.count > 6 ? try [5,6].map {
  try JSONDecoder().decode([Role].self, from: Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[$0])))
 } : []
 let speechMS = CommandLine.arguments.count > 7 ? Double(CommandLine.arguments[7])! : 2500
 let mode=CommandLine.arguments[3]
 let revised=mode=="revised"
 let corridor=[MobilePoint(x:0.35,y:0.45),.init(x:0.65,y:0.45),.init(x:0.9,y:1),.init(x:0.1,y:1)]
 var runs=[Run]()
 for variant in 0..<5 {
  var risk=LocalRiskEngine(),gate=MobileGuidanceGate(),spoken=[Spoken](),busyUntil = -1.0
  for (i,row) in input.enumerated() {
   if variant==3 && i % 2 != 0 {continue}
   if variant==4 && i % 2 != 1 {continue}
   let now=row.second*1000
   let frame=MobileFrameResult(sessionID:"reference",frameID:UInt64(i+1),capturedUptimeMS:now,revision:0,detections:row.detections)
   let result: MobileRiskAssessment
   if let defaultRoles = roles {
    let roles = variant >= 3 && alternateRoles.count == 2 ? alternateRoles[variant-3] : defaultRoles
    guard roles[i].state == "tracked", let index=roles[i].index else {continue}
    let wearer=MobileWearerObservation(frame:frame,state:.tracked,detectionIndex:index,reason:"Explicit reference selection")
    result=risk.update(frame:wearer.environment(in:frame),nowUptimeMS:now,corridor:corridor)
   } else {result=risk.update(frame:frame,nowUptimeMS:now,corridor:corridor)}
   gate.observe(result,nowUptimeMS:now)
   // JSON optional field permits the same harness to compile against both versions.
   let encoded=try JSONEncoder().encode(result)
   let data=try JSONSerialization.jsonObject(with:encoded) as! [String:Any]
   let candidates:[MobileRiskEvent]
   if revised,let list=data["guidanceCandidates"] {
    candidates=try JSONDecoder().decode([MobileRiskEvent].self,from:JSONSerialization.data(withJSONObject:list))
   } else {candidates=result.event.map {[$0]} ?? []}
   for event in candidates {
    let decision=gate.receive(event,nowUptimeMS:now,sessionID:"reference",revision:0,enabled:true,
      currentSpeechPriority:now<busyUntil ? 2:nil,ordinaryIntervalSeconds:8)
    if case .play = decision {
     spoken.append(.init(second:row.second,direction:event.direction.rawValue,label:event.evidence.detectedLabel ?? "obstacle",
       text:MobileAlertSpeech.obstacle(direction:event.direction)))
     busyUntil=now+speechMS // Controlled assumption, not a measured iPhone speech duration.
     break
    }
   }
  }
  runs.append(.init(scenario:variant<3 ? "repeat-\(variant+1)-5fps":"phase-\(variant-3)-2.5fps",speech:spoken))
 }
 try JSONEncoder().encode(runs).write(to:URL(fileURLWithPath:CommandLine.arguments[2]))
 }
}
