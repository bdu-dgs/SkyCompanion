import CoreImage
import CoreMedia
import ImageIO

final class FrameEncoder {
    // Reuse one context. Disable cached intermediates because broadcast extensions
    // have a tighter memory budget than foreground apps.
    private let context = CIContext(options: [.cacheIntermediates: false])
    private let colorSpace = CGColorSpaceCreateDeviceRGB()

    func encode(_ sampleBuffer: CMSampleBuffer, id: Int, capturedMS: Double, orientation: Int) -> CaptureFrame? {
        guard let pixels = CMSampleBufferGetImageBuffer(sampleBuffer) else { return nil }
        // On the verified iOS 18 capture path, undo the ReplayKit landscape
        // quarter turn when baking JPEG pixels. Applying it in the same direction
        // made the actual iPhone landscape feed 180° off.
        let pixelOrientation = orientation == 6 ? 8 : orientation == 8 ? 6 : orientation
        var image = CIImage(cvPixelBuffer: pixels, options: [.applyOrientationProperty: false])
            .oriented(forExifOrientation: Int32(pixelOrientation))
        // Rotation is baked into pixels. Never ask a JPEG decoder to rotate again.
        image = image.settingProperties([:])
        image = image.transformed(by: CGAffineTransform(translationX: -image.extent.minX, y: -image.extent.minY))
        let longest = max(image.extent.width, image.extent.height)
        guard longest > 0 else { return nil }
        let scale = min(1, 960 / longest)
        let width = max(1, Int(floor(image.extent.width * scale)))
        let height = max(1, Int(floor(image.extent.height * scale)))
        image = image.transformed(by: CGAffineTransform(scaleX: CGFloat(width) / image.extent.width,
                                                       y: CGFloat(height) / image.extent.height))
            .cropped(to: CGRect(x: 0, y: 0, width: width, height: height))
        guard let jpeg = context.jpegRepresentation(of: image, colorSpace: colorSpace,
                    options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.65]) else {
            return nil
        }
        return CaptureFrame(id: id, capturedMS: capturedMS, width: width, height: height,
                            orientation: orientation, jpeg: jpeg)
    }
}
