import Foundation
import CoreImage
import Vision
import ImageIO
import CaptureCore
import simd

/// Registers a user-confirmed ground polygon using the independently tracked user.
/// Ground registration failure does not reset user identity.
final class LocalPathEngine {
    private let config: LocalPathConfiguration
    private let reference: CGImage
    private let context = CIContext(options: [.useSoftwareRenderer: true, .cacheIntermediates: false])
    private var failed = false
    private var monitor = MobilePathMonitor()
    private let referencePixels: [UInt8]
    init(configuration: LocalPathConfiguration) throws {
        guard MobilePathMonitor.validBoundary(configuration.boundary), configuration.person.label == "person",
              let source = CGImageSourceCreateWithData(configuration.referenceJPEG as CFData,nil),
              let cg = CGImageSourceCreateImageAtIndex(source,0,nil) else { throw NSError(domain:"Path",code:1) }
        config = configuration; reference = cg
        referencePixels = Self.pixels(cg)

    }
    func process(image: CIImage, frame: MobileFrameResult, person: MobileDetection?) -> MobilePathObservation {
        let start = ProcessInfo.processInfo.systemUptime*1_000
        func unavailable(_ reason: String, latch: Bool = true) -> MobilePathObservation {
            if latch { failed = true }
            return monitor.update(frame:frame,foot:nil,boundary:[],reliable:false,
                now:ProcessInfo.processInfo.systemUptime*1_000,reason:reason,processingMS:ProcessInfo.processInfo.systemUptime*1_000-start)
        }
        guard !failed, let person else { return unavailable("Select the person and confirm the path again; tracking was lost.") }
        let e = image.extent
        let resized = image.transformed(by:.init(translationX:-e.minX,y:-e.minY))
            .transformed(by:.init(scaleX:Double(reference.width)/e.width,y:Double(reference.height)/e.height))
        guard let cg = context.createCGImage(resized,from:resized.extent) else { return unavailable("No registration image.") }
        do {
            guard person.y+person.height < 0.98 else { return unavailable("Feet are outside the camera view.") }
            let request = VNHomographicImageRegistrationRequest(targetedCGImage:cg,options:[:]); request.usesCPUOnly = true
            try VNImageRequestHandler(cgImage:reference,options:[:]).perform([request])
            guard let alignment = request.results?.first else { return unavailable("Path registration unavailable.") }
            // Vision warps floating/current pixels TO reference pixels in lower-left coordinates.
            let inverse = simd_inverse(alignment.warpTransform)
            let mapped = config.boundary.compactMap { Self.map($0, matrix:inverse,width:reference.width,height:reference.height) }
            guard MobilePathMonitor.validBoundary(mapped),
                  zip(config.boundary,mapped).allSatisfy({ hypot($0.x-$1.x,$0.y-$1.y) < 0.10 }),
                  Self.registrationAgrees(reference:referencePixels,current:Self.pixels(cg),
                transform:inverse,width:reference.width,height:reference.height,excluded:config.person,boundary:config.boundary) else {
                return unavailable("Camera motion or scene change prevents reliable path registration.")
            }
            let foot = MobilePoint(x:person.x+person.width/2,y:person.y+person.height)
            var result = monitor.update(frame:frame,foot:foot,boundary:mapped,reliable:true,
                now:ProcessInfo.processInfo.systemUptime*1_000,processingMS:ProcessInfo.processInfo.systemUptime*1_000-start)
            result.person = person; return result
        } catch { return unavailable("Path tracking unavailable: \(error.localizedDescription)") }
    }
    static func map(_ p: MobilePoint, matrix: simd_float3x3, width:Int,height:Int) -> MobilePoint? {
        let v = matrix * SIMD3(Float(p.x*Double(width)),Float((1-p.y)*Double(height)),1)
        guard v.x.isFinite,v.y.isFinite,v.z.isFinite,abs(v.z) > 1e-5 else { return nil }
        return .init(x:Double(v.x/v.z)/Double(width),y:1-Double(v.y/v.z)/Double(height))
    }
    static func pixels(_ image:CGImage) -> [UInt8] {
        var data = [UInt8](repeating:0,count:64*64)
        data.withUnsafeMutableBytes { bytes in
            let c = CGContext(data:bytes.baseAddress,width:64,height:64,bitsPerComponent:8,bytesPerRow:64,
                              space:CGColorSpaceCreateDeviceGray(),bitmapInfo:0)!
            // Match top-left normalized coordinates used by detections.
            c.draw(image,in:CGRect(x:0,y:0,width:64,height:64))
        }
        return data
    }
    static func registrationAgrees(reference:[UInt8],current:[UInt8],transform:simd_float3x3,width:Int,height:Int,excluded:MobileDetection,boundary:[MobilePoint] = []) -> Bool {
        var checked=0, agreed=0, textured=0, groundChecked=0, groundAgreed=0, groundTextured=0
        for y in stride(from:4,to:60,by:3) { for x in stride(from:4,to:60,by:3) {
            let p = MobilePoint(x:(Double(x)+0.5)/64,y:(Double(y)+0.5)/64)
            if p.x >= excluded.x-0.05 && p.x <= excluded.x+excluded.width+0.05 && p.y >= excluded.y-0.05 && p.y <= excluded.y+excluded.height+0.05 { continue }
            guard let q = map(p,matrix:transform,width:width,height:height),q.x>=0,q.x<1,q.y>=0,q.y<1 else { continue }
            let a=Int(reference[y*64+x]), b=Int(current[Int(q.y*64)*64+Int(q.x*64)])
            checked += 1; if abs(a-b)<25 { agreed += 1 }
            let texture = abs(a-Int(reference[y*64+x-2]))>12 || abs(a-Int(reference[(y-2)*64+x]))>12
            if texture { textured += 1 }
            if MobilePathMonitor.contains(p,polygon:boundary) {
                groundChecked += 1; if abs(a-b)<25 { groundAgreed += 1 }; if texture { groundTextured += 1 }
            }
        } }
        let groundValid = boundary.isEmpty || (groundChecked >= 20 && groundTextured >= 5 && Double(groundAgreed)/Double(groundChecked) >= 0.85)
        return groundValid && checked >= 160 && textured >= 25 && Double(agreed)/Double(checked) >= 0.75
    }
}
