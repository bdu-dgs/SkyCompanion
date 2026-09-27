import Foundation
import Vision
import CoreImage
import ImageIO
import CaptureCore

/// Followed-user identity is independent of fixed-ground registration and path availability.
final class LocalWearerTracker {
    private var sequence = VNSequenceRequestHandler()
    private let context = CIContext(options: [.useSoftwareRenderer:true,.cacheIntermediates:false])
    private var observation: VNDetectedObjectObservation
    private let size: CGSize
    private var lost = false
    private var uncertainSinceMS: Double?
    init(configuration:LocalWearerConfiguration) throws {
        guard configuration.person.label == "person",configuration.person.isValid,
              let source=CGImageSourceCreateWithData(configuration.referenceJPEG as CFData,nil),
              let reference=CGImageSourceCreateImageAtIndex(source,0,nil) else { throw NSError(domain:"Wearer",code:1) }
        size=CGSize(width:reference.width,height:reference.height)
        let p=configuration.person
        observation=VNDetectedObjectObservation(boundingBox:CGRect(x:p.x,y:1-p.y-p.height,width:p.width,height:p.height))
        let seed=VNTrackObjectRequest(detectedObjectObservation:observation);seed.trackingLevel = .accurate;seed.usesCPUOnly=true
        try sequence.perform([seed],on:reference)
        guard let initial=seed.results?.first as? VNDetectedObjectObservation else { throw NSError(domain:"Wearer",code:2) }
        observation=initial
    }
    func process(image:CIImage,frame:MobileFrameResult, nowUptimeMS: Double? = nil) -> MobileWearerObservation {
        func fail(_ reason:String) -> MobileWearerObservation { lost=true;return .init(frame:frame,state:.lost,reason:reason) }
        guard !lost else { return fail("Followed user lost. Select the user again; another person will not be substituted.") }
        guard frame.isFresh(at:nowUptimeMS ?? ProcessInfo.processInfo.systemUptime*1_000) else { return fail("User tracking frame expired.") }
        let e=image.extent
        let scaled=image.transformed(by:.init(translationX:-e.minX,y:-e.minY)).transformed(by:.init(scaleX:size.width/e.width,y:size.height/e.height))
        guard let cg=context.createCGImage(scaled,from:scaled.extent) else { return fail("User tracking image unavailable.") }
        do {
            let request=VNTrackObjectRequest(detectedObjectObservation:observation);request.trackingLevel = .accurate;request.usesCPUOnly=true
            try sequence.perform([request],on:cg)
            guard let next=request.results?.first as? VNDetectedObjectObservation else { return fail("User tracking unavailable.") }
            let r=next.boundingBox
            let predicted=MobileDetection(label:"person",confidence:Double(next.confidence),x:r.minX,y:1-r.maxY,width:r.width,height:r.height)
            guard let index=MobileWearerObservation.select(prediction:predicted,detections:frame.detections) else {
                // Keep only the existing optical track during brief ambiguity or lower confidence. No
                // person is excluded and no directional alert is authorized meanwhile.
                // Never reseed from a new detector box during this uncertain interval.
                if predicted.isValid && predicted.confidence >= 0.4 {
                    observation = next
                    if uncertainSinceMS == nil { uncertainSinceMS = frame.capturedUptimeMS }
                    if frame.capturedUptimeMS - uncertainSinceMS! < 800 {
                        return .init(frame: frame, state: .lost, reason: "User identity uncertain; direction guidance paused while the same visual track is checked.")
                    }
                }
                return fail("User identity is ambiguous, overlapping or no longer detected.")
            }
            uncertainSinceMS = nil
            // Correct gradual optical-box shrinkage only after the independent
            // tracker and detector have agreed on the same explicitly selected user.
            let matched = frame.detections[index]
            if predicted.intersectionOverUnion(with: matched) < 0.75 {
                // A new observation starts a new Vision tracker. Replace the sequence
                // too, so corrections do not accumulate trackers until Vision's limit.
                sequence = VNSequenceRequestHandler()
                let corrected = VNDetectedObjectObservation(boundingBox: CGRect(x: matched.x,
                    y: 1-matched.y-matched.height, width: matched.width, height: matched.height))
                let seed = VNTrackObjectRequest(detectedObjectObservation: corrected)
                seed.trackingLevel = .accurate; seed.usesCPUOnly = true
                try sequence.perform([seed], on: cg)
                guard let correctedResult = seed.results?.first as? VNDetectedObjectObservation else {
                    return fail("User tracking correction unavailable.")
                }
                observation = correctedResult
            } else { observation = next }
            return .init(frame:frame,state:.tracked,detectionIndex:index,reason:"Selected user tracked independently of the path region.")
        } catch { return fail("User tracking unavailable: \(error.localizedDescription)") }
    }
}
