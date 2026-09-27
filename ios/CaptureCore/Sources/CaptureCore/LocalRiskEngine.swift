import Foundation

/// Port of the backend's bounded image-corridor heuristic. Own on one serial executor.
/// This monitor never infers collision time, metric distance or a verified walking path.
public struct LocalRiskEngine: Sendable {
    private struct Candidate: Sendable {
        let box: MobileDetection
        let overlap: Double
        let kind: String
        let consequence: String
        let relevant: Bool
        var level: MobileRiskLevel { box.attention.nearCandidate || ["surface", "drop", "overhead", "vehicle"].contains(consequence) ? .action : .attention }
        var rank: Double { box.attention.score + 0.1 * overlap }
    }
    private struct Track: Sendable {
        var candidate: Candidate
        let firstMS: Double
        var lastMS: Double
        var observations: Int
        let initialArea: Double
        var consistentLabel: Bool
        var relevantCount = 0
        var relevantSinceMS = 0.0
        var outsideCount = 0
        var outsideSinceMS = 0.0
        var unresolved = false
        var level: MobileRiskLevel = .none
        var announcedLevel: MobileRiskLevel?
        var announcedDirection: MobileDirection?
        var announcedCenter = 0.0
        var directionCandidate: MobileDirection?
        var directionCount = 0
        var directionSinceMS = 0.0
    }
    private var tracks: [String: Track] = [:]
    private var activeTrack: String?
    private var lastFrame: MobileFrameResult?
    private var lastResult: MobileRiskAssessment?
    private var corridor: [MobilePoint]?
    private var unresolvedSummary: (String, MobileRiskLevel)?
    public var quiet = false
    private var trackSequence: UInt64 = 0
    private let namedLabels: Set<String>
    public init(namedLabels: Set<String> = []) { self.namedLabels = namedLabels }

    /// A new session/configuration must never preserve observations or queued events.
    public mutating func reset() {
        tracks.removeAll(); activeTrack = nil; lastFrame = nil; lastResult = nil; corridor = nil; unresolvedSummary = nil
    }
    public mutating func pause() -> MobileRiskAssessment {
        reset()
        return .init(state: .paused, health: .paused, text: MobileCopy.text("Analysis paused."))
    }
    public static func validCorridor(_ points: [MobilePoint]) -> Bool {
        guard (3...8).contains(points.count), points.allSatisfy({ $0.x.isFinite && $0.y.isFinite
            && (0...1).contains($0.x) && (0...1).contains($0.y) }) else { return false }
        var area = 0.0
        var signs = Set<Int>()
        for i in points.indices {
            let a = points[i], b = points[(i + 1) % points.count], c = points[(i + 2) % points.count]
            area += a.x * b.y - b.x * a.y
            let cross = (b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x)
            if abs(cross) > 1e-10 { signs.insert(cross > 0 ? 1 : -1) }
        }
        // Check every nonadjacent edge for intersection as convexity alone misses stars.
        for i in points.indices {
            for j in points.indices where j > i + 1 && !(i == 0 && j == points.count - 1) {
                if segmentsCross(points[i], points[(i + 1) % points.count],
                                 points[j], points[(j + 1) % points.count]) { return false }
            }
        }
        return signs.count == 1 && abs(area) / 2 >= 0.02
    }
    public mutating func update(frame: MobileFrameResult, nowUptimeMS: Double,
                                corridor suppliedCorridor: [MobilePoint]?) -> MobileRiskAssessment {
        guard frame.isFresh(at: nowUptimeMS) else {
            reset()
            return .init(state: .stale, health: .unavailable,
                         text: MobileCopy.text("Live view is unavailable. Current surroundings cannot be assessed."))
        }
        if let last = lastFrame {
            if frame.sessionID != last.sessionID || frame.revision != last.revision
                || frame.capturedUptimeMS < last.capturedUptimeMS || frame.frameID < last.frameID {
                reset()
            } else if suppliedCorridor == corridor,
                      frame.capturedUptimeMS == last.capturedUptimeMS || frame.frameID == last.frameID {
                return lastResult?.withoutEvent() ?? .init(state: .unconfirmed, text: MobileCopy.text("Waiting for a new frame."))
            }
        }
        let valid = suppliedCorridor.flatMap { Self.validCorridor($0) ? $0 : nil }
        if valid != corridor { reset(); corridor = valid }
        guard let corridor else {
            return remember(.init(state: .unconfigured, health: .limited,
                                  text: MobileCopy.text("Confirm a region in the camera view before occupancy alerts can start.")), frame: frame)
        }
        let now = frame.capturedUptimeMS
        let candidates = frame.detections.filter(\.isValid).compactMap { candidate($0, corridor: corridor) }
        for (key, track) in tracks where now - track.lastMS > 5_000 {
            archive(key, track: track); tracks.removeValue(forKey: key)
        }
        var pairs: [(Double, String, Int)] = []
        for (key, track) in tracks where now - track.lastMS <= 800 {
            for (index, candidate) in candidates.enumerated() {
                pairs.append((track.candidate.box.intersectionOverUnion(with: candidate.box), key, index))
            }
        }
        pairs.sort { $0.0 != $1.0 ? $0.0 > $1.0 : $0.1 > $1.1 }
        var matchedTracks = Set<String>(), matchedCandidates = Set<Int>(), assignments: [Int: String] = [:]
        for (score, key, index) in pairs where score >= 0.2 {
            guard !matchedTracks.contains(key), !matchedCandidates.contains(index) else { continue }
            matchedTracks.insert(key); matchedCandidates.insert(index); assignments[index] = key
        }
        var observed: [(String, Track)] = []
        for (index, candidate) in candidates.enumerated() {
            trackSequence &+= 1
            let key = assignments[index] ?? "track-\(trackSequence)"
            var track = tracks[key] ?? Track(candidate: candidate, firstMS: now, lastMS: now,
                observations: 0, initialArea: candidate.box.width * candidate.box.height, consistentLabel: true)
            if track.candidate.box.label != candidate.box.label { track.consistentLabel = false }
            track.candidate = candidate; track.lastMS = now; track.observations += 1
            let direction = candidate.box.direction
            if track.directionCandidate != direction {
                track.directionCandidate = direction; track.directionSinceMS = now; track.directionCount = 0
            }
            track.directionCount += 1
            if candidate.relevant {
                if track.relevantCount == 0 { track.relevantSinceMS = now }
                track.relevantCount += 1; track.outsideCount = 0
            } else {
                track.relevantCount = 0
                if candidate.overlap < 0.1 {
                    if track.outsideCount == 0 { track.outsideSinceMS = now }
                    track.outsideCount += 1
                } else { track.outsideCount = 0 }
            }
            tracks[key] = track; observed.append((key, track))
        }
        if tracks.count > 64 {
            let ordered = tracks.sorted {
                $0.value.lastMS == $1.value.lastMS ? $0.value.candidate.rank < $1.value.candidate.rank : $0.value.lastMS < $1.value.lastMS
            }
            for (key, track) in ordered.prefix(tracks.count - 64) { archive(key, track: track); tracks.removeValue(forKey: key) }
            observed.removeAll { tracks[$0.0] == nil }
        }
        var confirmed: [(String, Track)] = []
        var eventCandidates: [(String, Track, String)] = []
        var resolved = false
        for (key, original) in observed {
            var track = original
            if track.unresolved && stable(track.outsideCount, since: track.outsideSinceMS, now: now) {
                track.unresolved = false; track.announcedLevel = nil; track.announcedDirection = nil
                track.level = .none; resolved = true
            }
            let candidate = track.candidate
            if candidate.relevant && stable(track.relevantCount, since: track.relevantSinceMS, now: now) {
                track.unresolved = true; track.level = candidate.level
                let direction = candidate.box.direction, center = candidate.box.x + candidate.box.width / 2
                var reason: String?
                if track.announcedLevel == nil { reason = "new_relevance" }
                else if track.level > track.announcedLevel! { reason = "risk_upgrade" }
                else if direction != track.announcedDirection && abs(center - track.announcedCenter) >= 0.18
                    && stable(track.directionCount, since: track.directionSinceMS, now: now) { reason = "direction_change" }
                confirmed.append((key, track))
                if let reason, !(quiet && track.level == .attention) { eventCandidates.append((key, track, reason)) }
            }
            tracks[key] = track
        }
        var event: MobileRiskEvent?
        if let (key, track, reason) = eventCandidates.max(by: { ranksBelow($0.1.candidate, $1.1.candidate) }) {
            let box = track.candidate.box
            event = MobileRiskEvent(id: UUID().uuidString, sessionID: frame.sessionID, frameID: frame.frameID,
                revision: frame.revision, capturedUptimeMS: frame.capturedUptimeMS, trackID: key, level: track.level,
                direction: box.direction, text: message(track), evidence: evidence(track, now: now), reasonCodes: [reason])
            tracks[key]?.announcedLevel = track.level; tracks[key]?.announcedDirection = box.direction
            tracks[key]?.announcedCenter = box.x + box.width / 2
        }
        if var chosen = confirmed.max(by: { ranksBelow($0.1.candidate, $1.1.candidate) }) {
            if let active = confirmed.first(where: { $0.0 == activeTrack }), active.1.level == chosen.1.level,
               chosen.1.candidate.box.attention.score - active.1.candidate.box.attention.score <= 0.10 { chosen = active }
            let (key, track) = chosen; activeTrack = key
            return remember(.init(state: .occupied, level: track.level, text: message(track), event: event,
                                  evidence: evidence(track, now: now), direction: track.candidate.box.direction,
                                  trackID: key, lifecycle: .observed), frame: frame)
        }
        let missing = tracks.filter { $0.value.unresolved }.max { $0.value.level < $1.value.level }
        let unresolved = [missing.map { ($0.key, $0.value.level) }, unresolvedSummary].compactMap { $0 }.max { $0.1 < $1.1 }
        if let unresolved {
            return remember(.init(state: .occupied, level: unresolved.1, health: .limited,
                text: MobileCopy.text("The earlier obstacle is no longer visible. It has not been confirmed resolved."),
                trackID: unresolved.0, lifecycle: .occludedUnresolved), frame: frame)
        }
        let relevant = candidates.contains { $0.relevant }
        return remember(.init(state: relevant ? .confirming : .unconfirmed,
            text: relevant ? MobileCopy.text("Confirming a possible image conflict.") : MobileCopy.text("No confirmed image conflict. This does not mean the path is clear."),
            lifecycle: resolved ? .imageConflictResolved : .unknown), frame: frame)
    }
    private func stable(_ count: Int, since: Double, now: Double) -> Bool { count >= 3 && now - since >= 400 - 1e-6 }
    private mutating func archive(_ key: String, track: Track) {
        if track.unresolved && (unresolvedSummary == nil || track.level >= unresolvedSummary!.1) {
            unresolvedSummary = (key, track.level)
        }
    }
    private func evidence(_ track: Track, now: Double) -> MobileRiskEvidence {
        let c = track.candidate, box = c.box
        return MobileRiskEvidence(overlap: rounded(c.overlap), observations: track.observations,
            durationMS: (now - track.firstMS).rounded(), kind: c.kind, nearCandidate: box.attention.nearCandidate,
            apparentAreaRatio: rounded(box.width * box.height / max(1e-9, track.initialArea)), directionBasis: .cameraImage,
            verifiedUrgency: false, categoryNamingEnabled: namedLabels.contains(box.label) && track.consistentLabel && box.confidence >= 0.55,
            hazardConsequence: c.consequence, detectedLabel: track.consistentLabel ? box.label : nil)
    }
    private func message(_ track: Track) -> String {
        let box = track.candidate.box
        // Broad, explicitly uncertain hazard groups; no metric distance or approach claim.
        let grouped = track.consistentLabel && box.confidence >= 0.55
        let groups = ["surface": "ground-level change", "drop": "ground-level change",
                      "trip": "low obstacle", "overhead": "overhead obstacle", "vehicle": "vehicle"]
        let noun = grouped ? (groups[track.candidate.consequence] ?? "obstacle") : "obstacle"
        let template: String
        switch box.direction {
        case .left: template = "Camera left: possible %@."
        case .ahead: template = "Camera center: possible %@."
        case .right: template = "Camera right: possible %@."
        }
        return MobileCopy.format(template, MobileCopy.text(noun))
    }
    /// Rechecks current observation age for explicit describe/repeat commands.
    public func describe(nowUptimeMS: Double) -> MobileRiskAssessment {
        guard let frame = lastFrame, frame.isFresh(at: nowUptimeMS), let result = lastResult else {
            return .init(state: .stale, health: .unavailable,
                         text: MobileCopy.text("Live view is unavailable. Current surroundings cannot be assessed."))
        }
        return result.withoutEvent()
    }
    private mutating func remember(_ result: MobileRiskAssessment, frame: MobileFrameResult) -> MobileRiskAssessment {
        lastFrame = frame; lastResult = result; return result
    }
    private func candidate(_ box: MobileDetection, corridor: [MobilePoint]) -> Candidate? {
        // A curb rectangle alone does not establish a hazard. Confirmed path
        // monitoring owns boundary alerts; retain raw detections for inspection.
        guard box.label != "curb" else { return nil }
        guard !["sidewalk", "traffic light", "tree"].contains(box.label), box.confidence >= 0.25 else { return nil }
        let bottom = box.y + box.height
        var kind = "lower_visible_body", consequence = "collision", region = corridor, fraction = 0.35
        var eligible = bottom >= 0.55
        let elevated = ["overhead obstacle", "hanging sign", "low hanging branch", "awning"].contains(box.label)
        if elevated {
            eligible = bottom >= 0.18 && box.width >= 0.15 && box.height >= 0.04
            let lo = corridor.map(\.x).min()!, hi = corridor.map(\.x).max()!
            region = [.init(x: lo, y: 0), .init(x: hi, y: 0), .init(x: hi, y: 1), .init(x: lo, y: 1)]
            fraction = 1; kind = "elevated_image_alignment"; consequence = "overhead"
        } else {
            if ["stairs", "step", "steps", "pothole", "hole", "drop-off"].contains(box.label) {
                fraction = 1; kind = "surface_change_candidate"; consequence = ["pothole", "hole", "drop-off"].contains(box.label) ? "drop" : "surface"
            } else if ["rock", "boulder", "stone barrier", "stone block", "concrete block", "concrete barrier", "curb", "traffic cone", "cable", "hose", "fallen branch", "debris", "speed bump", "pipe"].contains(box.label) {
                kind = "low_object_candidate"; consequence = "trip"
            }
        }
        if consequence == "collision" && ["car", "truck", "bus", "train", "motorcycle", "bicycle"].contains(box.label) { consequence = "vehicle" }
        let overlap = Self.intersection(box: box, corridor: region, lowerFraction: fraction)
        return Candidate(box: box, overlap: overlap, kind: kind, consequence: consequence, relevant: eligible && overlap >= 0.25)
    }
    private func ranksBelow(_ a: Candidate, _ b: Candidate) -> Bool {
        if a.level != b.level { return a.level < b.level }
        return a.box.attention.score < b.box.attention.score
    }
    private func rounded(_ value: Double) -> Double { (value * 1_000).rounded() / 1_000 }

    /// 160×90 raster overlap, matching the backend's image-space scale and cutoff.
    /// Integer point-in-polygon edges can differ by one boundary pixel from OpenCV fillPoly.
    public static func intersection(box: MobileDetection, corridor: [MobilePoint], lowerFraction: Double = 0.35) -> Double {
        guard box.isValid, corridor.count >= 3, corridor.allSatisfy({ $0.x.isFinite && $0.y.isFinite }),
              lowerFraction.isFinite else { return 0 }
        let fallback = [MobilePoint(x: box.x, y: box.y), MobilePoint(x: box.x + box.width, y: box.y),
                        MobilePoint(x: box.x + box.width, y: box.y + box.height), MobilePoint(x: box.x, y: box.y + box.height)]
        let polygon = box.polygon.flatMap { p in p.count >= 3 && p.allSatisfy({ $0.x.isFinite && $0.y.isFinite }) ? p : nil } ?? fallback
        func scaled(_ points: [MobilePoint]) -> [MobilePoint] {
            points.map { .init(x: Double(Int(min(1, max(0, $0.x)) * 159)), y: Double(Int(min(1, max(0, $0.y)) * 89))) }
        }
        let validComponents = box.polygons?.filter { $0.count >= 3 && $0.allSatisfy { $0.x.isFinite && $0.y.isFinite } } ?? []
        let shapes = (validComponents.isEmpty ? [polygon] : validComponents).map(scaled)
        let allPoints = shapes.flatMap { $0 }
        let region = scaled(corridor)
        let cutoff = Int(max(0, min(90, (box.y + box.height * (1 - lowerFraction)) * 89)))
        var area = 0, overlap = 0
        guard cutoff < 90 else { return 0 }
        let minX = max(0, Int(allPoints.map(\.x).min() ?? 0)), maxX = min(159, Int(allPoints.map(\.x).max() ?? 159))
        let minY = max(cutoff, Int(allPoints.map(\.y).min() ?? 0)), maxY = min(89, Int(allPoints.map(\.y).max() ?? 89))
        guard minX <= maxX, minY <= maxY else { return 0 }
        for y in minY...maxY { for x in minX...maxX {
            let p = MobilePoint(x: Double(x), y: Double(y))
            if shapes.contains(where: { contains(p, in: $0) }) { area += 1; if contains(p, in: region) { overlap += 1 } }
        } }
        return area > 0 ? Double(overlap) / Double(area) : 0
    }
    private static func contains(_ p: MobilePoint, in polygon: [MobilePoint]) -> Bool {
        var inside = false
        for i in polygon.indices {
            let a = polygon[i], b = polygon[(i + 1) % polygon.count]
            let cross = (p.x - a.x) * (b.y - a.y) - (p.y - a.y) * (b.x - a.x)
            if abs(cross) < 1e-9 && p.x >= min(a.x, b.x) && p.x <= max(a.x, b.x)
                && p.y >= min(a.y, b.y) && p.y <= max(a.y, b.y) { return true }
            if (a.y > p.y) != (b.y > p.y), p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x { inside.toggle() }
        }
        return inside
    }
    private static func segmentsCross(_ a: MobilePoint, _ b: MobilePoint, _ c: MobilePoint, _ d: MobilePoint) -> Bool {
        func cross(_ a: MobilePoint, _ b: MobilePoint, _ c: MobilePoint) -> Double {
            (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
        }
        return cross(a, b, c) * cross(a, b, d) < 0 && cross(c, d, a) * cross(c, d, b) < 0
    }
}
