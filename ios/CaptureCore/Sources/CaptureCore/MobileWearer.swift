import Foundation

public struct LocalWearerConfiguration: Codable, Sendable {
    public let referenceJPEG: Data
    public let person: MobileDetection
    public init(referenceJPEG: Data, person: MobileDetection) { self.referenceJPEG = referenceJPEG; self.person = person }
}
public enum MobileWearerState: String, Codable, Sendable { case notSelected, tracked, lost }
public struct MobileWearerObservation: Codable, Sendable {
    public let state: MobileWearerState
    public let sessionID: String
    public let revision: UInt64
    public let frameID: UInt64
    public let capturedUptimeMS: Double
    public let detectionIndex: Int?
    public let reason: String
    public init(frame: MobileFrameResult, state: MobileWearerState, detectionIndex: Int? = nil, reason: String) {
        sessionID=frame.sessionID;revision=frame.revision;frameID=frame.frameID;capturedUptimeMS=frame.capturedUptimeMS
        self.state=state;self.detectionIndex=detectionIndex;self.reason=reason
    }
    /// Exact same-frame role assignment. Never remove a generic nearest/central person.
    public func matchedIndex(in frame: MobileFrameResult) -> Int? {
        guard state == .tracked, sessionID == frame.sessionID, revision == frame.revision,
              frameID == frame.frameID, capturedUptimeMS == frame.capturedUptimeMS,
              let index=detectionIndex,frame.detections.indices.contains(index),
              frame.detections[index].label == "person",frame.detections[index].isValid else { return nil }
        return index
    }
    public func environment(in frame: MobileFrameResult) -> MobileFrameResult {
        guard let index=matchedIndex(in:frame) else { return frame }
        let selected = frame.detections[index]
        var result = frame
        result.detections = frame.detections.enumerated().filter {
            $0.offset != index && !Self.isWeakerDuplicate($0.element, of: selected)
        }.map(\.element)
        return result
    }
    static func isWeakerDuplicate(_ candidate: MobileDetection, of selected: MobileDetection) -> Bool {
        guard candidate.label == "person", selected.label == "person", candidate.isValid, selected.isValid,
              selected.confidence - candidate.confidence >= 0.15,
              candidate.intersectionOverUnion(with: selected) >= 0.35 else { return false }
        let ratio = candidate.height / selected.height
        return (0.75...1.25).contains(ratio)
            && abs(candidate.x + candidate.width/2 - selected.x - selected.width/2) <= min(candidate.width, selected.width)*0.5
            && abs(candidate.y + candidate.height - selected.y - selected.height) <= min(candidate.height, selected.height)*0.08
    }
    /// Match an independently tracked image patch to YOLO, with ambiguity/overlap rejection.
    public static func select(prediction: MobileDetection, detections: [MobileDetection]) -> Int? {
        guard prediction.isValid, prediction.confidence >= 0.65 else { return nil }
        let people=detections.enumerated().filter { $0.element.label == "person" && $0.element.isValid && $0.element.confidence >= 0.55 }
        // A weaker, nearly coincident box can describe the same tracked body. This
        // assigns wearer roles only; the YOLO detections and thresholds remain intact.
        let distinct = people.filter { candidate in
            !people.contains { $0.offset != candidate.offset && isWeakerDuplicate(candidate.element, of: $0.element) }
        }
        let ranked=distinct.map { ($0.offset,$0.element.intersectionOverUnion(with:prediction)) }.sorted { $0.1 > $1.1 }
        guard let best=ranked.first,best.1 >= 0.5, ranked.count < 2 || best.1-ranked[1].1 > 0.25 else { return nil }
        guard distinct.filter({ $0.offset != best.0 }).allSatisfy({ $0.element.intersectionOverUnion(with:detections[best.0]) < 0.08 }) else { return nil }
        return best.0
    }
}
