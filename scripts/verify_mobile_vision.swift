// Compile together with VisionEngine.swift and CaptureCore on macOS.
// Runs the actual shipping Swift preprocessor and mask decoder, not a Python approximation.
import Foundation
import CoreImage
import CoreVideo
import ImageIO
import CaptureCore

@main
struct VerifyMobileVision {
    static func main() throws {
        let args = CommandLine.arguments
        guard args.count >= 3, let bundle = Bundle(path: args[1]) else {
            fatalError("Usage: verify-mobile-vision <fixture.bundle> <image> ...")
        }
        let engine = try CoreMLVisionEngine(bundle: bundle, computeUnits: .cpuOnly)
        let context = CIContext(options: [.useSoftwareRenderer: true, .cacheIntermediates: false])
        struct Row: Codable { let path: String; let variant: String; let detections: [MobileDetection]; let elapsedMS: Double }
        var rows = [Row]()
        for path in args.dropFirst(2) {
            guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
                  let cg = CGImageSourceCreateImageAtIndex(source, 0, nil) else { fatalError("Could not read image") }
            let original = CIImage(cgImage: cg)
            let paddedBounds = CGRect(x: 0, y: 0, width: cg.width+40, height: cg.height+80)
            let padded = original.transformed(by: .init(translationX: 20, y: 40))
                .composited(over: CIImage(color: CIColor.black).cropped(to: paddedBounds))
            let variants: [(String, CIImage, CGImagePropertyOrientation, CGRect)] = [
                ("upright", original, .up, CGRect(x: 0, y: 0, width: 1, height: 1)),
                ("rotated90", original.oriented(.right), .left, CGRect(x: 0, y: 0, width: 1, height: 1)),
                ("paddedROI", padded, .up, CGRect(x: 20/paddedBounds.width, y: 40/paddedBounds.height,
                                                width: CGFloat(cg.width)/paddedBounds.width, height: CGFloat(cg.height)/paddedBounds.height))
            ]
            for (variant, image, orientation, roi) in variants {
                let bounds = image.extent
                let normalized = image.transformed(by: .init(translationX: -bounds.minX, y: -bounds.minY))
                var buffer: CVPixelBuffer?
                guard CVPixelBufferCreate(kCFAllocatorDefault, Int(bounds.width), Int(bounds.height), kCVPixelFormatType_32BGRA,
                                          [kCVPixelBufferIOSurfacePropertiesKey: [:]] as CFDictionary, &buffer) == kCVReturnSuccess,
                      let buffer else { fatalError("Pixel buffer allocation failed") }
                context.render(normalized, to: buffer, bounds: normalized.extent, colorSpace: CGColorSpaceCreateDeviceRGB())
                let result = try engine.process(pixelBuffer: buffer, orientation: orientation, roi: roi)
                rows.append(.init(path: path, variant: variant, detections: result.detections, elapsedMS: result.inferenceMS))
            }
        }
        for i in Swift.stride(from: 0, to: rows.count, by: 3) {
            precondition(rows[i].detections == rows[i+1].detections, "Rotation changed detections")
            precondition(rows[i].detections == rows[i+2].detections, "ROI crop changed detections")
        }
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        print(String(decoding: try encoder.encode(rows), as: UTF8.self))
    }
}
