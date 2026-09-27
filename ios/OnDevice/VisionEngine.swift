import Foundation
import CoreML
import CoreVideo
import CoreImage
import ImageIO
import Accelerate
import CaptureCore

struct MobileModelManifest: Decodable {
    struct Tensor: Decodable { let name: String; let shape: [Int] }
    let resourceName: String
    let task: String
    let inputName: String
    let inputSize: Int
    let names: [String]
    let sourceSHA256: String
    let confidenceThreshold: Double
    let iouThreshold: Double
    let maskChannels: Int
    let outputs: [Tensor]
}

struct VisionInferenceResult {
    let detections: [MobileDetection]
    /// Includes preprocessing, model execution, NMS and mask contours, not camera transmission.
    let inferenceMS: Double
    let timings: MobileInferenceTimings
}

protocol VisionEngine {
    func process(pixelBuffer: CVPixelBuffer, orientation: CGImagePropertyOrientation,
                 roi: CGRect) throws -> VisionInferenceResult
}

enum MobileVisionError: LocalizedError {
    case missingResource(String), invalidModel(String), invalidRegion, bufferAllocation
    var errorDescription: String? {
        switch self {
        case .missingResource(let s): return String.localizedStringWithFormat(String(localized: "Model resource missing: %@. Reinstall SkyCompanion with its model."), s)
        case .invalidModel(let s): return String.localizedStringWithFormat(String(localized: "Unsupported model contract: %@"), NSLocalizedString(s, comment: "Model contract diagnostic"))
        case .invalidRegion: return String(localized: "Confirm the upright video region before starting analysis.")
        case .bufferAllocation: return String(localized: "Could not allocate the local vision buffer.")
        }
    }
}

/// One instance per serial inference queue. No network and no runtime model downloads.
final class CoreMLVisionEngine: VisionEngine {
    let manifest: MobileModelManifest
    private let model: MLModel
    private let context = CIContext(options: [.useSoftwareRenderer: true, .cacheIntermediates: false])
    private let colorSpace = CGColorSpaceCreateDeviceRGB()
    private let predictionOutput: String
    private let prototypeOutput: String?
    private var reusableInput: CVPixelBuffer?

    init(bundle: Bundle = .main, manifestName: String = "selectedModel",
         computeUnits: MLComputeUnits = .cpuAndNeuralEngine) throws {
        guard let manifestURL = bundle.url(forResource: manifestName, withExtension: "json") else {
            throw MobileVisionError.missingResource(manifestName)
        }
        manifest = try JSONDecoder().decode(MobileModelManifest.self, from: Data(contentsOf: manifestURL))
        let channels = 4 + manifest.names.count + manifest.maskChannels
        guard !manifest.names.isEmpty, Set(manifest.names).count == manifest.names.count,
              manifest.names.allSatisfy({ !$0.isEmpty }),
              (manifest.task == "detect" && manifest.maskChannels == 0)
                || (manifest.task == "segment" && manifest.maskChannels == 32),
              (0...1).contains(manifest.confidenceThreshold), (0...1).contains(manifest.iouThreshold),
              let prediction = manifest.outputs.first(where: {
                  $0.shape.count == 3 && $0.shape[0] == 1 && $0.shape[1] == channels && $0.shape[2] > 0
              }) else {
            throw MobileVisionError.invalidModel("expected fixed-vocabulary detection or 32-prototype segmentation")
        }
        predictionOutput = prediction.name
        prototypeOutput = manifest.outputs.first(where: {
            $0.shape.count == 4 && $0.shape[0] == 1 && $0.shape[1] == 32
        })?.name
        if manifest.maskChannels > 0 && prototypeOutput == nil {
            throw MobileVisionError.invalidModel("missing segmentation prototype contract")
        }
        guard let url = bundle.url(forResource: manifest.resourceName, withExtension: "mlmodelc") else {
            throw MobileVisionError.missingResource(manifest.resourceName + ".mlmodelc")
        }
        let configuration = MLModelConfiguration()
        // Broadcast extensions may run while another app is foreground. Avoid GPU scheduling.
        configuration.computeUnits = computeUnits
        model = try MLModel(contentsOf: url, configuration: configuration)
        guard let input = model.modelDescription.inputDescriptionsByName[manifest.inputName]?.imageConstraint,
              input.pixelsWide == manifest.inputSize, input.pixelsHigh == manifest.inputSize else {
            throw MobileVisionError.invalidModel("input image dimensions")
        }
    }

    func process(pixelBuffer: CVPixelBuffer, orientation: CGImagePropertyOrientation,
                 roi: CGRect = CGRect(x: 0, y: 0, width: 1, height: 1)) throws -> VisionInferenceResult {
        let start = ProcessInfo.processInfo.systemUptime
        return try autoreleasepool {
            guard [roi.minX, roi.minY, roi.width, roi.height].allSatisfy({ $0.isFinite }),
                  roi.minX >= 0, roi.minY >= 0, roi.maxX <= 1, roi.maxY <= 1,
                  roi.width > 0.01, roi.height > 0.01 else { throw MobileVisionError.invalidRegion }
            let oriented = CIImage(cvPixelBuffer: pixelBuffer).oriented(orientation)
            let extent = oriented.extent
            // CI coordinates are bottom-left; public ROI is top-left upright image space.
            let cropX = (extent.minX + extent.width * roi.minX).rounded()
            let cropY = (extent.minY + extent.height * (1 - roi.maxY)).rounded()
            let crop = CGRect(x: cropX, y: cropY,
                              width: (extent.width * roi.width).rounded(),
                              height: (extent.height * roi.height).rounded())
            let image = oriented.cropped(to: crop).transformed(by: .init(translationX: -crop.minX, y: -crop.minY))
            let size = manifest.inputSize
            let gain = min(CGFloat(size) / crop.width, CGFloat(size) / crop.height)
            let resizedW = (crop.width * gain).rounded(), resizedH = (crop.height * gain).rounded()
            let left = floor((CGFloat(size) - resizedW) / 2), top = floor((CGFloat(size) - resizedH) / 2)
            let bottom = CGFloat(size) - resizedH - top
            let transformed = image.transformed(by: .init(scaleX: resizedW / crop.width, y: resizedH / crop.height))
                .transformed(by: .init(translationX: left, y: bottom))
            let background = CIImage(color: CIColor(red: 114/255, green: 114/255, blue: 114/255))
                .cropped(to: CGRect(x: 0, y: 0, width: size, height: size))
            // The engine is serial and prediction is synchronous: this buffer is safe to reuse.
            if reusableInput == nil {
                let status = CVPixelBufferCreate(kCFAllocatorDefault, size, size, kCVPixelFormatType_32BGRA,
                    [kCVPixelBufferIOSurfacePropertiesKey: [:], kCVPixelBufferCGImageCompatibilityKey: true] as CFDictionary, &reusableInput)
                guard status == kCVReturnSuccess else { throw MobileVisionError.bufferAllocation }
            }
            guard let input = reusableInput else { throw MobileVisionError.bufferAllocation }
            context.render(transformed.composited(over: background), to: input, bounds: background.extent, colorSpace: colorSpace)
            let provider = try MLDictionaryFeatureProvider(dictionary: [manifest.inputName: MLFeatureValue(pixelBuffer: input)])
            let modelStart = ProcessInfo.processInfo.systemUptime
            let output = try model.prediction(from: provider)
            let decodeStart = ProcessInfo.processInfo.systemUptime
            guard let predictions = output.featureValue(for: predictionOutput)?.multiArrayValue else {
                throw MobileVisionError.invalidModel("missing predictions")
            }
            let prototypes = prototypeOutput.flatMap { output.featureValue(for: $0)?.multiArrayValue }
            let geometry = Letterbox(size: size, width: Double(crop.width), height: Double(crop.height),
                                     gain: Double(gain), left: Double(left), top: Double(top))
            let detections = try decode(predictions, prototypes, geometry)
            let end = ProcessInfo.processInfo.systemUptime
            return .init(detections: detections, inferenceMS: (end - start) * 1000,
                timings: .init(preprocessMS: (modelStart-start)*1000,
                               modelMS: (decodeStart-modelStart)*1000, decodeMS: (end-decodeStart)*1000))
        }
    }

    private struct Letterbox {
        let size: Int; let width: Double; let height: Double; let gain: Double; let left: Double; let top: Double
        func point(_ x: Double, _ y: Double) -> MobilePoint {
            .init(x: min(1, max(0, (x - left) / gain / width)),
                  y: min(1, max(0, (y - top) / gain / height)))
        }
    }
    private struct Candidate { let anchor: Int; let label: Int; let score: Double; let rect: CGRect }

    private func decode(_ prediction: MLMultiArray, _ prototype: MLMultiArray?,
                        _ geometry: Letterbox) throws -> [MobileDetection] {
        let shape = prediction.shape.map(\.intValue)
        let classes = manifest.names.count
        guard shape.count == 3, shape[0] == 1, shape[1] == 4 + classes + manifest.maskChannels,
              shape[2] > 0 else {
            throw MobileVisionError.invalidModel("output dimensions changed")
        }
        let pred = TensorReader(prediction)
        var candidates = [Candidate]()
        // Predictions are channel-major. Scan contiguous anchors for each class.
        var bestScores = [Double](repeating: 0, count: shape[2])
        var bestLabels = [Int](repeating: 0, count: shape[2])
        // Dispatch tensor type once, rather than calling Objective-C metadata getters millions of times.
        func scan<T: BinaryFloatingPoint>(_ values: UnsafePointer<T>) {
            for c in 0..<classes {
                let row = (4+c)*pred.strides[1]
                for anchor in 0..<shape[2] {
                    let score = Double(values[row + anchor*pred.strides[2]])
                    if score > bestScores[anchor] { bestScores[anchor] = score; bestLabels[anchor] = c }
                }
            }
        }
        switch prediction.dataType {
        case .float32: scan(UnsafePointer(prediction.dataPointer.assumingMemoryBound(to: Float.self)))
        case .float16: scan(UnsafePointer(prediction.dataPointer.assumingMemoryBound(to: Float16.self)))
        case .double: scan(UnsafePointer(prediction.dataPointer.assumingMemoryBound(to: Double.self)))
        default:
            for c in 0..<classes { for anchor in 0..<shape[2] {
                let score = pred.value3(0, 4+c, anchor)
                if score > bestScores[anchor] { bestScores[anchor] = score; bestLabels[anchor] = c }
            } }
        }
        for anchor in 0..<shape[2] {
            let best = bestScores[anchor], label = bestLabels[anchor]
            guard best > manifest.confidenceThreshold, best.isFinite else { continue }
            let cx = pred.value3(0, 0, anchor), cy = pred.value3(0, 1, anchor)
            let w = pred.value3(0, 2, anchor), h = pred.value3(0, 3, anchor)
            guard [cx, cy, w, h].allSatisfy(\.isFinite), w > 0, h > 0 else { continue }
            candidates.append(.init(anchor: anchor, label: label, score: best,
                                    rect: CGRect(x: cx-w/2, y: cy-h/2, width: w, height: h)))
        }
        candidates.sort { $0.score == $1.score ? $0.anchor < $1.anchor : $0.score > $1.score }
        var selected = [Candidate]()
        for candidate in candidates.prefix(30_000) {
            if selected.allSatisfy({ Self.iou(candidate.rect, $0.rect) <= manifest.iouThreshold }) {
                selected.append(candidate)
                if selected.count == 300 { break }
            }
        }
        guard !selected.isEmpty else { return [] }
        if manifest.maskChannels == 0 {
            // Detection-only checkpoints have no masks. Preserve nil so downstream
            // geometry uses its explicit bounding-box fallback, never a fabricated mask.
            return selected.compactMap { candidate in
                let a = geometry.point(candidate.rect.minX, candidate.rect.minY)
                let b = geometry.point(candidate.rect.maxX, candidate.rect.maxY)
                guard b.x > a.x, b.y > a.y else { return nil }
                return MobileDetection(label: MobileModelLabel.runtime(manifest.names[candidate.label]),
                    confidence: candidate.score, x: a.x, y: a.y, width: b.x-a.x, height: b.y-a.y)
            }
        }
        guard let prototype else { throw MobileVisionError.invalidModel("missing segmentation prototypes") }
        let pshape = prototype.shape.map(\.intValue)
        guard pshape.count == 4, pshape[0] == 1, pshape[1] == 32, pshape[2] > 0, pshape[3] > 0 else {
            throw MobileVisionError.invalidModel("prototype dimensions changed")
        }
        let proto = TensorReader(prototype)
        let ph = pshape[2], pw = pshape[3], plane = ph * pw
        var protoValues: [Float]
        if prototype.dataType == .float32 && prototype.strides.map(\.intValue) == [32*plane,plane,pw,1] {
            protoValues = Array(UnsafeBufferPointer(start: prototype.dataPointer.assumingMemoryBound(to: Float.self), count: 32*plane))
        } else {
            protoValues = [Float](repeating: 0, count: 32 * plane)
            for c in 0..<32 { for y in 0..<ph { for x in 0..<pw {
                protoValues[c * plane + y * pw + x] = Float(proto.value4(0,c,y,x))
            } } }
        }
        return selected.compactMap { candidate in
            let a = geometry.point(candidate.rect.minX, candidate.rect.minY)
            let b = geometry.point(candidate.rect.maxX, candidate.rect.maxY)
            guard b.x > a.x, b.y > a.y else { return nil }
            var coefficients = (0..<32).map { Float(pred.value3(0,4+classes+$0,candidate.anchor)) }
            var logits = [Float](repeating: 0, count: plane)
            cblas_sgemv(CblasRowMajor, CblasTrans, 32, Int32(plane), 1, &protoValues, Int32(plane),
                        &coefficients, 1, 0, &logits, 1)
            let scale = Double(pw) / Double(geometry.size)
            let box = candidate.rect.applying(CGAffineTransform(scaleX: scale, y: Double(ph)/Double(geometry.size)))
            // Match Ultralytics crop_mask CPU branch (banker rounding for fewer than 50 instances).
            let roundBounds = selected.count < 50
            let x1 = roundBounds ? max(0, box.minX).rounded(.toNearestOrEven) : box.minX
            let y1 = roundBounds ? max(0, box.minY).rounded(.toNearestOrEven) : box.minY
            let x2 = roundBounds ? max(0, box.maxX).rounded(.toNearestOrEven) : box.maxX
            let y2 = roundBounds ? max(0, box.maxY).rounded(.toNearestOrEven) : box.maxY
            for y in 0..<ph { for x in 0..<pw {
                if Double(x) < x1 || Double(x) >= x2 || Double(y) < y1 || Double(y) >= y2 {
                    logits[y*pw+x] = -1
                }
            } }
            let contours = Self.externalContours(logits, width: pw, height: ph)
            let polygons = contours.map { contour in
                contour.map { geometry.point(Double($0.0) / scale, Double($0.1) * Double(geometry.size) / Double(ph)) }
            }
            return MobileDetection(label: manifest.names[candidate.label], confidence: candidate.score,
                                   x: a.x, y: a.y, width: b.x-a.x, height: b.y-a.y,
                                   polygon: polygons.first, polygons: polygons.isEmpty ? nil : polygons)
        }
    }

    private static func iou(_ a: CGRect, _ b: CGRect) -> Double {
        let intersection = a.intersection(b)
        let area = intersection.isNull ? 0 : intersection.width * intersection.height
        return area / max(1e-9, a.width*a.height + b.width*b.height - area)
    }

    /// Trace actual binary mask cell edges, retaining every external component, then bound each contour.
    /// Like the desktop polygon contract, this representation omits holes.
    private static func externalContours(_ values: [Float], width: Int, height: Int) -> [[(Int, Int)]] {
        let stride = width + 1
        func on(_ x: Int, _ y: Int) -> Bool {
            x >= 0 && x < width && y >= 0 && y < height && values[y*width+x] > 0
        }
        var edges = [Int: [Int]]()
        func add(_ x: Int, _ y: Int, _ xx: Int, _ yy: Int) { edges[y*stride+x, default: []].append(yy*stride+xx) }
        for y in 0..<height { for x in 0..<width where on(x,y) {
            if !on(x,y-1) { add(x,y,x+1,y) }; if !on(x+1,y) { add(x+1,y,x+1,y+1) }
            if !on(x,y+1) { add(x+1,y+1,x,y+1) }; if !on(x-1,y) { add(x,y+1,x,y) }
        } }
        var external = [(area: Double, contour: [Int])]()
        while let start = edges.keys.min() {
            var contour = [Int](), current = start
            repeat {
                contour.append(current)
                guard var next = edges[current], let end = next.popLast() else { break }
                if next.isEmpty { edges.removeValue(forKey: current) } else { edges[current] = next }
                current = end
            } while current != start && contour.count <= (width+1)*(height+1)*4
            guard current == start, contour.count >= 3 else { continue }
            var area = 0.0
            for i in contour.indices {
                let a = contour[i], b = contour[(i+1)%contour.count]
                area += Double((a%stride)*(b/stride) - (b%stride)*(a/stride))
            }
            if area > 0 { external.append((area, contour)) }
        }
        return external.sorted { $0.area > $1.area }.map { entry in
            let contour = entry.contour
            let step = max(1, Int(ceil(Double(contour.count)/96)))
            return Swift.stride(from: 0, to: contour.count, by: step).map { (contour[$0]%stride, contour[$0]/stride) }
        }
    }
}

/// Avoid NSNumber boxing for every tensor element; respect Core ML's reported strides.
private struct TensorReader {
    let array: MLMultiArray
    let strides: [Int]
    let type: MLMultiArrayDataType
    let pointer: UnsafeMutableRawPointer
    init(_ array: MLMultiArray) {
        self.array = array; strides = array.strides.map(\.intValue)
        type = array.dataType; pointer = array.dataPointer
    }
    func value3(_ b: Int, _ c: Int, _ a: Int) -> Double { value(b*strides[0]+c*strides[1]+a*strides[2]) }
    func value4(_ b: Int, _ c: Int, _ y: Int, _ x: Int) -> Double { value(b*strides[0]+c*strides[1]+y*strides[2]+x*strides[3]) }
    private func value(_ index: Int) -> Double {
        switch type {
        case .float32: return Double(pointer.assumingMemoryBound(to: Float.self)[index])
        case .double: return pointer.assumingMemoryBound(to: Double.self)[index]
        case .float16: return Double(pointer.assumingMemoryBound(to: Float16.self)[index])
        default: return array[index].doubleValue
        }
    }
}
