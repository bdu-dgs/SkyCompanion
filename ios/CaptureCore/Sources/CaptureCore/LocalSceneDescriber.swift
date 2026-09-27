import Foundation

/// Bounded camera-relative descriptions, independent of collision warnings.
public struct LocalSceneDescriber: Sendable {
    private struct Track: Sendable {
        let box: MobileDetection
        let kind: String
        let firstMS: Double
        let lastMS: Double
        let observations: Int
    }
    private struct Group {
        var object: MobileSceneObject
        var rank: Double
    }
    private var tracks: [Track] = []
    private var lastFrame: MobileFrameResult?
    private var objects: [MobileSceneObject] = []
    private var wearerState: MobileWearerState?
    public init() {}
    public mutating func reset() { tracks.removeAll(); lastFrame = nil; objects.removeAll(); wearerState = nil }
    public mutating func update(frame rawFrame: MobileFrameResult, nowUptimeMS: Double, wearer: MobileWearerObservation? = nil) {
        var frame = wearer?.environment(in: rawFrame) ?? rawFrame
        let state = wearer.map { $0.matchedIndex(in:rawFrame) != nil ? MobileWearerState.tracked : $0.state == .notSelected ? .notSelected : .lost }
        if state != wearerState { reset() }
        guard frame.isFresh(at: nowUptimeMS) else { reset(); return }
        if let last = lastFrame {
            if last.sessionID != frame.sessionID || last.revision != frame.revision
                || frame.capturedUptimeMS < last.capturedUptimeMS || frame.frameID < last.frameID { reset() }
            else if frame.capturedUptimeMS == last.capturedUptimeMS || frame.frameID == last.frameID { return }
        }
        wearerState = state
        let peopleUncertain = state != nil && state != .tracked && rawFrame.detections.contains { $0.label == "person" }
        if peopleUncertain { frame.detections.removeAll { $0.label == "person" } }
        let now = frame.capturedUptimeMS
        let old = tracks.filter { now - $0.lastMS <= 600 }
        let candidates = frame.detections.filter { box in
            box.isValid && box.confidence >= (box.label == "traffic light" ? 0.4 : 0.5) && Self.kind(for: box.label) != nil
        }.sorted { $0.confidence > $1.confidence }.prefix(64)
        var used = Set<Int>(), next: [Track] = []
        for box in candidates {
            let kind = Self.kind(for: box.label)!
            let matches = old.enumerated().filter { !used.contains($0.offset) && $0.element.kind == kind }
            let match = matches.max { $0.element.box.intersectionOverUnion(with: box) < $1.element.box.intersectionOverUnion(with: box) }
            if let match, match.element.box.intersectionOverUnion(with: box) >= 0.2 {
                used.insert(match.offset)
                next.append(Track(box: box, kind: kind, firstMS: match.element.firstMS, lastMS: now,
                                  observations: match.element.observations + 1))
            } else { next.append(Track(box: box, kind: kind, firstMS: now, lastMS: now, observations: 1)) }
        }
        tracks = next; lastFrame = frame
        var groups: [String: Group] = [:], insertionOrder: [String] = []
        for track in tracks where track.observations >= 3 && now - track.firstMS >= 300 {
            let box = track.box, attention = box.attention
            if track.kind == "obstacle" && !attention.nearCandidate { continue }
            let key = "\(track.kind)|\(box.direction.rawValue)"
            let rank = attention.score + (attention.nearCandidate ? 0.5 : 0)
            if var group = groups[key] {
                group.object = MobileSceneObject(kind: group.object.kind, direction: group.object.direction,
                                                 count: min(3, group.object.count + 1), vertical: group.object.vertical)
                group.rank = max(group.rank, rank); groups[key] = group
            } else {
                let cy = box.y + box.height / 2
                groups[key] = Group(object: MobileSceneObject(kind: track.kind, direction: box.direction,
                    count: 1, vertical: cy < 0.35 ? "upper" : cy > 0.7 ? "lower" : "middle"), rank: rank)
                insertionOrder.append(key)
            }
        }
        let ordered = insertionOrder.enumerated().sorted {
            let a = groups[$0.element]!.rank, b = groups[$1.element]!.rank
            return a == b ? $0.offset < $1.offset : a > b
        }
        var chosen: [MobileSceneObject] = [], kinds = Set<String>()
        for item in ordered {
            let object = groups[item.element]!.object
            if kinds.insert(object.kind).inserted {
                let sameKind = insertionOrder.compactMap { groups[$0]?.object }.filter { $0.kind == object.kind }
                var combined = MobileSceneObject(kind: object.kind, direction: object.direction,
                    count: min(3, sameKind.reduce(0) { $0 + $1.count }), vertical: object.vertical)
                combined.directions = sameKind.map(\.direction)
                chosen.append(combined)
            }
            if chosen.count == 3 { break }
        }
        objects = chosen
    }
    public func describe(nowUptimeMS: Double) -> MobileSceneSummary {
        guard let frame = lastFrame, frame.isFresh(at: nowUptimeMS) else {
            return .init(code: .visionUnavailable, objects: [],
                         text: MobileCopy.text("Live view is unavailable. Current surroundings cannot be assessed."),
                         sessionID: nil, frameID: nil, revision: nil, capturedUptimeMS: nil, directionBasis: .cameraImage)
        }
        var text: String
        if objects.isEmpty {
            text = MobileCopy.text("No stable objects identified in the camera view. This does not mean the path is clear.")
        } else {
            let phrases = objects.map { object -> String in
                let name = object.kind.replacingOccurrences(of: "_", with: " ")
                let plural = name == "person" ? "people" : name == "bus" ? "buses" : "\(name)s"
                let noun = object.count == 1 ? MobileCopy.format("one %@", MobileCopy.text(name))
                    : object.count == 2 ? MobileCopy.format("two %@", MobileCopy.text(plural))
                    : MobileCopy.format("several %@", MobileCopy.text(plural))
                let positions = (object.directions ?? [object.direction]).map { MobileCopy.position($0) }
                let position = positions.joined(separator: MobileCopy.text(" and "))
                return MobileCopy.format("%@ %@", noun, position)
            }
            text = MobileCopy.format("In the camera view: %@.", phrases.joined(separator: MobileCopy.text("; ")))
        }
        return .init(code: objects.isEmpty ? .noStableObjects : .sceneSummary, objects: objects, text: text,
                     sessionID: frame.sessionID, frameID: frame.frameID, revision: frame.revision,
                     capturedUptimeMS: frame.capturedUptimeMS, directionBasis: .cameraImage)
    }
    private static func kind(for label: String) -> String? {
        let kinds = ["person": "person", "car": "car", "bicycle": "bicycle", "motorcycle": "motorcycle",
                     "bus": "bus", "truck": "truck", "traffic light": "traffic_light", "chair": "chair",
                     "bench": "bench", "dining table": "table", "table": "table", "dog": "dog", "potted plant": "plant"]
        if let kind = kinds[label] { return kind }
        let structures: Set<String> = ["pole", "light pole", "tree trunk", "fence", "railing", "construction barrier",
            "traffic cone", "construction barrel", "bollard", "stone block", "stone barrier", "rock", "boulder",
            "kiosk", "newsstand", "stairs", "curb", "pothole", "concrete block", "bus stop shelter",
            "fire hydrant", "trash can", "stroller", "scooter", "barrier gate", "overhead obstacle",
            "bicycle rack", "parking meter", "mailbox", "suitcase", "shopping cart", "wheelchair",
            "walker", "skateboard", "traffic sign", "a frame sign", "scaffolding", "ladder", "awning",
            "low hanging branch", "open door", "hanging sign", "cable", "hose", "fallen branch",
            "debris", "hole", "speed bump", "patio umbrella", "vending machine", "box", "statue",
            "umbrella", "cabinet", "pipe", "bush"]
        return structures.contains(label) ? "obstacle" : nil
    }
}

/// Start-deadline gate for mobile risk events. Does not enqueue audio or revive old observations.
public struct MobileGuidanceGate: Sendable {
    public enum Decision: Equatable, Sendable { case play(deadlineMS: Double), duplicate, expired, disabled, wrongSession, invalid, cooldown, busy }
    private var seen: Set<String> = []
    private var order: [String] = []
    private var lastAlert: (time: Double, level: MobileRiskLevel)?
    private var recentContent: [String: (lastObserved: Double, level: MobileRiskLevel)] = [:]
    public init() {}
    /// Repeated observations keep an announced obstacle quiet; disappearance is not resolution.
    public mutating func observe(_ assessment: MobileRiskAssessment, nowUptimeMS: Double) {
        guard nowUptimeMS.isFinite else { return }
        if assessment.lifecycle == .imageConflictResolved {
            recentContent.removeAll()
        } else if assessment.lifecycle == .occludedUnresolved {
            for key in Array(recentContent.keys) { recentContent[key]?.lastObserved = nowUptimeMS }
        } else if let direction = assessment.direction, let evidence = assessment.evidence {
            let key = "\(direction.rawValue)|\(evidence.hazardConsequence)"
            recentContent[key]?.lastObserved = nowUptimeMS
        }
    }
    public mutating func receive(_ event: MobileRiskEvent, nowUptimeMS: Double,
                                 sessionID: String, revision: UInt64, enabled: Bool, currentSpeechPriority: Int? = nil, protectingCommand: Bool = false, ordinaryIntervalSeconds: Int = 8, hapticsEnabled: Bool = false) -> Decision {
        guard !event.id.isEmpty, event.level != .none,
              event.level != .urgent || event.evidence.verifiedUrgency else { return .invalid }
        guard event.sessionID == sessionID, event.revision == revision else { return .wrongSession }
        guard seen.insert(event.id).inserted else { return .duplicate }
        order.append(event.id)
        if order.count > 256 { seen.remove(order.removeFirst()) }
        guard enabled else { return .disabled }
        guard event.isFresh(at: nowUptimeMS) else { return .expired }
        // Do not queue: the next observation must still be fresh when admitted.
        guard hapticsEnabled || protectingCommand || Self.mayStartSpeech(incoming: event.level.rawValue, current: currentSpeechPriority) else { return .busy }
        recentContent = recentContent.filter { nowUptimeMS - $0.value.lastObserved < 20_000 }
        let key = "\(event.direction.rawValue)|\(event.evidence.hazardConsequence)"
        let previous = recentContent[key]
        recentContent[key]?.lastObserved = nowUptimeMS
        if let previous, event.level <= previous.level { return .duplicate }
        let upgrade = (lastAlert.map { event.level > $0.level } ?? false)
            || (previous.map { event.level > $0.level } ?? false)
        let interval = event.level >= .action ? 8_000.0 : Double(min(120, max(8, ordinaryIntervalSeconds))) * 1_000
        if !upgrade, let lastAlert, nowUptimeMS - lastAlert.time < interval { return .cooldown }
        lastAlert = (nowUptimeMS, event.level)
        recentContent[key] = (nowUptimeMS, event.level)
        return .play(deadlineMS: event.expiresUptimeMS)
    }
    public static func mayStartSpeech(incoming: Int, current: Int?, explicitRequest: Bool = false, protectingCommand: Bool = false) -> Bool {
        if protectingCommand && !explicitRequest && incoming < MobileRiskLevel.urgent.rawValue { return false }
        guard let current else { return true }
        return incoming > current || (explicitRequest && incoming == current)
    }
    public static func mayInterrupt(incoming: MobileRiskLevel, current: MobileRiskLevel?) -> Bool {
        guard let current else { return true }
        return incoming > current
    }
}
