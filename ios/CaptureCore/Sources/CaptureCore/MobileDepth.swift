import Foundation

public struct MobileDepthSample: Codable, Sendable {
    public let detectionIndex: Int
    public let label: String
    /// Experimental optical-axis depth. Never a validated range or wearer distance.
    public let rawMedianMeters: Double?
    public let spatialP10Meters: Double?
    public let spatialP90Meters: Double?
    public let validPixels: Int
    public let reason: String
    public init(detectionIndex: Int, label: String, values: [Double]) {
        self.detectionIndex = detectionIndex; self.label = label
        let v = values.filter { $0.isFinite && $0 > 0.1 && $0 < 79.5 }.sorted()
        validPixels = v.count
        guard v.count >= 16, v.count >= Int(Double(values.count)*0.8) else {
            rawMedianMeters = nil; spatialP10Meters = nil; spatialP90Meters = nil
            reason = "Insufficient valid depth pixels"; return
        }
        let median = v[v.count/2], lo = v[Int(Double(v.count-1)*0.1)], hi = v[Int(Double(v.count-1)*0.9)]
        spatialP10Meters = lo; spatialP90Meters = hi
        guard (hi-lo)/median < 0.6 else { rawMedianMeters = nil; reason = "Depth varies too much within the object"; return }
        rawMedianMeters = median; reason = "Unvalidated raw optical-axis depth; not for guidance"
    }
}
public struct MobileDepthResult: Codable, Sendable {
    public let sessionID: String
    public let revision: UInt64
    public let frameID: UInt64
    public let capturedUptimeMS: Double
    public let completedUptimeMS: Double
    public let modelID: String
    public let preprocessingID: String
    public let inferenceMS: Double
    public let samples: [MobileDepthSample]
    public let status: String
    public let measurementReference: String
    public let validationState: String
    public init(frame: MobileFrameResult, completedMS: Double, inferenceMS: Double, samples: [MobileDepthSample], status: String) {
        sessionID = frame.sessionID; revision = frame.revision; frameID = frame.frameID
        capturedUptimeMS = frame.capturedUptimeMS; completedUptimeMS = completedMS
        modelID = "SkyMetricDepthSmall_392_FP32:9203e538d35255c9"
        preprocessingID = "roi-letterbox392-rgb124116104-imagenet-v1"
        self.inferenceMS = inferenceMS; self.samples = samples; self.status = status
        measurementReference = "camera_optical_axis"; validationState = "unvalidated"
    }
    /// No validation profile has been accepted for this build. Fail closed in normal use.
    public var guidanceDistanceText: String { "Camera-to-obstacle distance unknown. Depth calibration is not validated." }
}
