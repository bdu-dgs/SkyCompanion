import Foundation
import Darwin
import CoreImage
import Vision
import CaptureCore
import simd

@main struct VerifyPathRegistration {
 static func main() throws {
    let w=640,h=480
    let c=CGContext(data:nil,width:w,height:h,bitsPerComponent:8,bytesPerRow:w*4,space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGImageAlphaInfo.premultipliedLast.rawValue)!
    var seed:UInt64=39
    func random() -> CGFloat { seed=seed &* 6364136223846793005 &+ 1; return CGFloat(seed >> 32)/CGFloat(UInt32.max) }
    c.setFillColor(CGColor(gray:0.4,alpha:1)); c.fill(CGRect(x:0,y:0,width:w,height:h))
    for _ in 0..<350 {
        c.setFillColor(CGColor(red:random(),green:random(),blue:random(),alpha:1))
        c.fill(CGRect(x:random()*640,y:random()*480,width:5+random()*55,height:5+random()*55))
    }
    let ref=c.makeImage()!, ci=CIImage(cgImage:ref), context=CIContext(options:[.useSoftwareRenderer:true])
    var rows:[[String:Any]]=[]
    for (dx,dy) in [(0.0,0.0),(12.0,8.0),(-8.0,-6.0)] {
        let current=ci.transformed(by:.init(translationX:dx,y:dy)).composited(over:CIImage(color:.black)).cropped(to:ci.extent)
        let cg=context.createCGImage(current,from:current.extent)!
        let request=VNHomographicImageRegistrationRequest(targetedCGImage:cg,options:[:]);request.usesCPUOnly=true
        try VNImageRequestHandler(cgImage:ref,options:[:]).perform([request])
        guard let result=request.results?.first else { fatalError("No homography") }
        let transform=simd_inverse(result.warpTransform)
        let point=LocalPathEngine.map(.init(x:0.5,y:0.5),matrix:transform,width:w,height:h)!
        let error=hypot((point.x-0.5)*Double(w)-dx,(0.5-point.y)*Double(h)-dy)
        let agrees=LocalPathEngine.registrationAgrees(reference:LocalPathEngine.pixels(ref),current:LocalPathEngine.pixels(cg),transform:transform,width:w,height:h,excluded:.init(label:"person",confidence:1,x:0,y:0,width:0.02,height:0.02))
        rows.append(["dx":dx,"dy":dy,"errorPixels":error,"photometricGate":agrees])
        print("translation=\(dx),\(dy) pixelError=\(error) gate=\(agrees)")
        fflush(stdout); guard error<2,agrees else { fatalError("Coordinate or pixel mapping incorrect") }
    }
    let blank=context.createCGImage(CIImage(color:.white).cropped(to:ci.extent),from:ci.extent)!
    let bad=LocalPathEngine.registrationAgrees(reference:LocalPathEngine.pixels(ref),current:LocalPathEngine.pixels(blank),transform:matrix_identity_float3x3,width:w,height:h,excluded:.init(label:"person",confidence:1,x:0,y:0,width:0.02,height:0.02))
    precondition(!bad)
    let region=[MobilePoint(x:0.2,y:0.65),.init(x:0.8,y:0.65),.init(x:0.8,y:0.9),.init(x:0.2,y:0.9)]
    let patch=CIImage(color:.white).cropped(to:CGRect(x:128,y:48,width:384,height:120)).composited(over:ci)
    let patched=context.createCGImage(patch,from:ci.extent)!
    let groundMismatch=LocalPathEngine.registrationAgrees(reference:LocalPathEngine.pixels(ref),current:LocalPathEngine.pixels(patched),transform:matrix_identity_float3x3,width:w,height:h,excluded:.init(label:"person",confidence:1,x:0,y:0,width:0.02,height:0.02),boundary:region)
    precondition(!groundMismatch)
    let report:[String:Any] = ["scope":"Actual Apple Vision homography, synthetic translation and changed-scene gate on Mac. Not person identity or aerial field validation.","cases":rows,"unrelatedSceneRejected":!bad,"localGroundMismatchRejected":!groundMismatch,"passed":true]
    try JSONSerialization.data(withJSONObject:report,options:[.prettyPrinted,.sortedKeys]).write(to:URL(fileURLWithPath:"docs/validation/mobile-2026-09-26/path-registration.json"))
 }
}
