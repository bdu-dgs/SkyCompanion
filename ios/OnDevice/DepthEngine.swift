import Foundation
import CoreML
import CoreImage
import ImageIO
import CaptureCore

/// One in-flight depth sample, no pending queue. Independent of YOLO's frame mailbox.
final class LocalDepthWorker: @unchecked Sendable {
    private let queue = DispatchQueue(label: "sky.depth", qos: .utility)
    private let lock = NSLock()
    private var busy = false
    private var generation: UInt64 = 0
    private var lastSample = -Double.infinity
    private var model: MLModel?
    private var failed = false
    private let context = CIContext(options: [.useSoftwareRenderer: true, .cacheIntermediates: false])
    func reset() {
        lock.lock(); generation &+= 1; lastSample = -Double.infinity; lock.unlock()
        queue.async { self.model = nil; self.failed = false }
    }
    func submit(image: CIImage, frame: MobileFrameResult, excludingDetectionIndex: Int? = nil, completion: @escaping (MobileDepthResult) -> Void) {
        lock.lock()
        guard !busy, frame.capturedUptimeMS-lastSample >= 2_000 else { lock.unlock(); return }
        busy = true; lastSample = frame.capturedUptimeMS; let token = generation; lock.unlock()
        queue.async { [self] in
            defer { lock.lock(); busy = false; lock.unlock() }
            lock.lock(); let current = generation == token; lock.unlock()
            guard current else { return }
            let start = ProcessInfo.processInfo.systemUptime*1_000
            let result = autoreleasepool { () -> MobileDepthResult in
                func result(_ status: String, _ samples: [MobileDepthSample] = []) -> MobileDepthResult {
                    let now = ProcessInfo.processInfo.systemUptime*1_000
                    return .init(frame: frame, completedMS: now, inferenceMS: now-start, samples: samples, status: status)
                }
                guard ProcessInfo.processInfo.thermalState.rawValue < 2 else {
                    model = nil; return result("Depth suspended for thermal pressure; YOLO continues.")
                }
                guard !failed else { return result("Depth unavailable in this session; disable and re-enable after checking diagnostics.") }
                do {
                    if model == nil {
                        guard let url = Bundle.main.url(forResource: "SkyMetricDepthSmall_392_FP32", withExtension: "mlmodelc") else {
                            throw NSError(domain: "Depth", code: 1, userInfo: [NSLocalizedDescriptionKey: "Bundled depth model is missing"])
                        }
                        let config = MLModelConfiguration(); config.computeUnits = .cpuAndNeuralEngine
                        model = try MLModel(contentsOf: url, configuration: config)
                    }
                    let input = try Self.letterbox(image, context: context)
                    let features = try MLDictionaryFeatureProvider(dictionary: ["image": MLFeatureValue(pixelBuffer: input)])
                    guard let output = try model?.prediction(from: features).featureValue(for: "depth_meters")?.multiArrayValue,
                          output.shape.map(\.intValue) == [1,392,392] else { throw NSError(domain: "Depth", code: 2) }
                    let sy = output.strides[1].intValue, sx = output.strides[2].intValue
                    let extent = image.extent, scale = min(392/extent.width, 392/extent.height)
                    let width = extent.width*scale, height = extent.height*scale
                    let left = (392-width)/2, top = (392-height)/2
                    var samples: [MobileDepthSample] = []
                    for (index, detection) in frame.detections.prefix(24).enumerated() where detection.isValid && index != excludingDetectionIndex {
                        // Inner mask/box samples limit contamination from background at edges.
                        var values: [Double] = []; var pixels = Set<Int>()
                        let components = detection.polygons ?? detection.polygon.map { [$0] } ?? []
                        for yy in 0..<12 { for xx in 0..<12 {
                            let u = detection.x+detection.width*(0.2+0.6*(Double(xx)+0.5)/12)
                            let v = detection.y+detection.height*(0.2+0.6*(Double(yy)+0.5)/12)
                            if !components.isEmpty && !components.contains(where: { MobilePathMonitor.contains(.init(x: u,y: v), polygon: $0) }) { continue }
                            let x = Int(left+u*width), y = Int(top+v*height)
                            guard (0..<392).contains(x), (0..<392).contains(y) else { continue }
                            let offset = y*sy+x*sx
                            if pixels.insert(offset).inserted { values.append(output[offset].doubleValue) }
                        } }
                        samples.append(.init(detectionIndex: index, label: detection.label, values: values))
                    }
                    return result("Experimental depth completed; normal distance guidance remains unknown.", samples)
                } catch { failed = true; model = nil; return result("Depth unavailable: \(error.localizedDescription). YOLO continues.") }
            }
            lock.lock(); let valid = generation == token; lock.unlock()
            if valid { completion(result) }
        }
    }
    static func letterbox(_ image: CIImage, context: CIContext) throws -> CVPixelBuffer {
        var buffer: CVPixelBuffer?
        let status = CVPixelBufferCreate(kCFAllocatorDefault,392,392,kCVPixelFormatType_32BGRA,
            [kCVPixelBufferIOSurfacePropertiesKey: [:]] as CFDictionary,&buffer)
        guard status == kCVReturnSuccess, let buffer else { throw NSError(domain: "Depth",code: 3) }
        let e = image.extent, scale = min(392/e.width,392/e.height)
        let content = image.transformed(by: .init(translationX: -e.minX,y: -e.minY))
            .transformed(by: .init(scaleX: scale,y: scale))
            .transformed(by: .init(translationX: (392-e.width*scale)/2,y: (392-e.height*scale)/2))
        let background = CIImage(color: CIColor(red: 124/255,green: 116/255,blue: 104/255)).cropped(to: CGRect(x:0,y:0,width:392,height:392))
        context.render(content.composited(over: background),to:buffer,bounds: CGRect(x:0,y:0,width:392,height:392),colorSpace:CGColorSpaceCreateDeviceRGB())
        return buffer
    }
}
