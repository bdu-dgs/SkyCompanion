import Foundation
import CoreMedia
import CoreImage
import ImageIO
import UIKit
import CaptureCore

/// Owns the model and state machines on one serial executor, with a bounded raw-frame mailbox.
final class LocalVisionPipeline: @unchecked Sendable {
    var onPacket: ((LocalPacket) -> Void)?
    private let queue = DispatchQueue(label: "skycompanion.local.vision", qos: .userInitiated)
    private let lock = NSLock()
    private var pending: (CVPixelBuffer, CGImagePropertyOrientation, Double)?
    private var working = false
    private var enabled = false
    private var epoch: UInt64 = 0
    private var settingsEpoch: UInt64 = 0
    private var lastSubmission = -Double.infinity
    private var settings: LocalCaptureSettings?
    private var model: CoreMLVisionEngine?
    private let depth = LocalDepthWorker()
    private var pathEngine: LocalPathEngine?
    private var wearerTracker: LocalWearerTracker?
    private var walkingPlanner = MobileWalkingPlanner()
    private var lastPathAt = -Double.infinity
    private var risk = MobileCameraObstacleMonitor()
    private var latestPath: MobilePathObservation?
    private var scene = LocalSceneDescriber()
    private var frameID: UInt64 = 0
    private var lastPreviewAt = -Double.infinity
    private var layoutGate = MobileLayoutGate()
    private var reportedWaitingForLayout = false
    private var suspendedForLayout = false
    private var readyAfter = 0.0
    private var lastEvidenceAt = -Double.infinity
    private var lastSourcePreviewAt = -Double.infinity
    private let context = CIContext(options: [.useSoftwareRenderer: true, .cacheIntermediates: false])

    func configure(_ configuration: LocalCaptureSettings) {
        lock.lock(); epoch &+= 1; let version = epoch; pending = nil; enabled = configuration.region.valid && (configuration.analyze || configuration.requestPreview); lock.unlock()
        queue.async { [self] in
            walkingPlanner = MobileWalkingPlanner(); depth.reset(); pathEngine = nil; lastPathAt = -Double.infinity; latestPath = nil
            wearerTracker = nil
            let wearerConfig = configuration.wearerConfiguration ?? configuration.pathConfiguration.map {
                LocalWearerConfiguration(referenceJPEG: $0.referenceJPEG, person: $0.person)
            }
            if let wearerConfig, configuration.analyze { wearerTracker = try? LocalWearerTracker(configuration: wearerConfig) }
            if let path = configuration.pathConfiguration, configuration.analyze {
                pathEngine = try? LocalPathEngine(configuration: path)
            }
            settings = configuration; settingsEpoch = version; frameID = 0; lastPreviewAt = -Double.infinity
            lastSourcePreviewAt = -Double.infinity
            layoutGate = MobileLayoutGate()
            reportedWaitingForLayout = false; suspendedForLayout = false
            risk.reset(); scene.reset()
            readyAfter = ProcessInfo.processInfo.systemUptime * 1_000 + 800
            onPacket?(LocalPacket(type: "state", contextSessionID: configuration.sessionID, contextRevision: configuration.revision, message: configuration.analyze ? String(localized: "Waiting for a fresh source frame…") : String(localized: "Preview only. Analysis paused.")))
        }
    }

    func stop() {
        lock.lock(); enabled = false; epoch &+= 1; pending = nil; lock.unlock()
        queue.async { [self] in settings = nil; risk.reset(); scene.reset(); model = nil; depth.reset(); pathEngine = nil; wearerTracker = nil; latestPath = nil }
    }

    func submit(_ pixelBuffer: CVPixelBuffer, orientation: CGImagePropertyOrientation, capturedMS: Double) {
        lock.lock()
        guard enabled, capturedMS - lastSubmission >= (1_000.0 / 15) else { lock.unlock(); return }
        lastSubmission = capturedMS
        pending = (pixelBuffer, orientation, capturedMS)
        guard !working else { lock.unlock(); return }
        working = true
        lock.unlock()
        queue.async { [self] in drain() }
    }

    private func drain() {
        lock.lock()
        guard let item = pending, enabled else { working = false; lock.unlock(); return }
        pending = nil; let revision = epoch; lock.unlock()
        autoreleasepool { process(item, epoch: revision) }
        // Yield to configuration/stop commands between frames; never starve them in an endless loop.
        queue.async { [self] in drain() }
    }

    private func valid(_ expected: UInt64) -> Bool {
        lock.lock(); defer { lock.unlock() }; return enabled && epoch == expected
    }

    private func process(_ item: (CVPixelBuffer, CGImagePropertyOrientation, Double), epoch: UInt64) {
        guard let settings, settingsEpoch == epoch, valid(epoch), !suspendedForLayout, item.2 >= readyAfter else { return }
        let image = CIImage(cvPixelBuffer: item.0).oriented(item.1)
        let size = image.extent.size
        if settings.requestPreview && !settings.analyze && item.2-lastPreviewAt >= 1_000 {
            lastPreviewAt = item.2
            if let preview = preview(image) {
                onPacket?(LocalPacket(type: "preview", contextSessionID: settings.sessionID, contextRevision: settings.revision, preview: preview))
            }
        }
        guard settings.analyze else { return }
        switch layoutGate.evaluate(width: size.width, height: size.height,
                                   orientation: item.1.rawValue, capturedMS: item.2) {
        case .waiting:
            if !reportedWaitingForLayout {
                reportedWaitingForLayout = true
                onPacket?(LocalPacket(type: "state", contextSessionID: settings.sessionID,
                    contextRevision: settings.revision,
                    message: String(localized: "Waiting for a stable source view. Open the DJI Fly camera view using the orientation you confirmed.")))
            }
            return
        case .changed:
            suspend(String(localized: "Source layout changed. Return to SkyCompanion and confirm the video area.")); return
        case .accept: break
        }
        if blank(image, region: settings.region) { suspend(String(localized: "The shared frame is blank or too dark to analyze. Confirm the source in SkyCompanion.")); return }
        do {
            if model == nil {
                onPacket?(LocalPacket(type: "state", contextSessionID: settings.sessionID, contextRevision: settings.revision, message: String(localized: "Loading the model on this iPhone…")))
                model = try CoreMLVisionEngine()
            }
            guard let model else { return }
            let prediction = try model.process(pixelBuffer: item.0, orientation: item.1, roi: settings.region.rect)
            let now = ProcessInfo.processInfo.systemUptime * 1_000
            guard valid(epoch), now - item.2 < 1_500 else { return }
            frameID &+= 1
            let frame = MobileFrameResult(sessionID: settings.sessionID, frameID: frameID,
                                          capturedUptimeMS: item.2, revision: settings.revision,
                                          detections: prediction.detections, inferenceMS: prediction.inferenceMS)
            var evidence: Data?
            var sourcePreview: Data?
            if settings.requestPreview && !settings.recordingContainsLocalVideo && now-lastSourcePreviewAt >= 1_000 {
                lastSourcePreviewAt = now
                sourcePreview = preview(image) // Full DJI screen for crop editing, separate from cropped user selection.
            }
            if (settings.captureEvidence || settings.requestPreview) && now-lastEvidenceAt >= 500 {
                lastEvidenceAt = now
                let bounds = CGRect(x: image.extent.minX + settings.region.x*size.width,
                                    y: image.extent.minY + (1-settings.region.y-settings.region.height)*size.height,
                                    width: settings.region.width*size.width, height: settings.region.height*size.height)
                evidence = preview(image.cropped(to: bounds))
            }
            let bounds = CGRect(x: image.extent.minX + settings.region.x*size.width,
                                y: image.extent.minY + (1-settings.region.y-settings.region.height)*size.height,
                                width: settings.region.width*size.width, height: settings.region.height*size.height)
            let cropped = image.cropped(to: bounds)
            let hasSelection = settings.wearerConfiguration != nil || settings.pathConfiguration != nil
            let wearer = wearerTracker?.process(image: cropped, frame: frame)
                ?? MobileWearerObservation(frame: frame, state: hasSelection ? .lost : .notSelected,
                    reason: hasSelection ? "User tracker unavailable. Select the user again." : "Select the followed user in an analyzed view.")
            let wearerIndex = wearer.matchedIndex(in: frame)
            let environment = wearer.environment(in: frame)
            if settings.depthEnabled {
                depth.submit(image: cropped, frame: frame, excludingDetectionIndex: wearerIndex) { [weak self] result in
                    guard let self, self.valid(epoch) else { return }
                    self.onPacket?(LocalPacket(type: "depth", contextSessionID: settings.sessionID,
                        contextRevision: settings.revision, depth: result))
                }
            }
            var path: MobilePathObservation?
            var walking: MobileWalkingObservation?
            if item.2-lastPathAt >= 300, settings.pathConfiguration != nil {
                lastPathAt = item.2; path = pathEngine?.process(image: cropped, frame: frame, person: wearerIndex.map { frame.detections[$0] })
                latestPath = path
                walking = walkingPlanner.update(frame: environment, path: path, rearFollowing: settings.pathConfiguration?.rearFollowing == true, now: ProcessInfo.processInfo.systemUptime*1_000)
            }
            // Registration time must not make an old YOLO result speakable.
            guard valid(epoch), frame.isFresh(at: ProcessInfo.processInfo.systemUptime*1_000) else { return }
            let walkingActive = settings.pathConfiguration?.rearFollowing == true && wearerIndex != nil
                && MobileAssistanceSnapshot.pathAvailable(latestPath, for: frame, at: now)
            let assessment = risk.update(frame: frame, wearer: wearer,
                wearerRequired: !settings.recordingContainsLocalVideo || hasSelection,
                walkingActive: walkingActive, nowUptimeMS: now, corridor: settings.corridor)
            scene.update(frame: frame, nowUptimeMS: now, wearer: wearer)
            onPacket?(LocalPacket(type: "result", frame: frame, risk: assessment,
                                 summary: scene.describe(nowUptimeMS: now),
                                 preview: settings.requestPreview ? evidence : nil,
                                 sourcePreview: sourcePreview,
                                 evidenceImage: settings.captureEvidence ? evidence : nil, memoryMB: Self.memoryMB,
                                 inferenceTimings: prediction.timings, path: path, walking: walking, wearer: wearer))
        } catch { guard valid(epoch) else { return }; suspend(String.localizedStringWithFormat(String(localized: "Local inference unavailable: %@"), error.localizedDescription), failure: "analysis") }
    }

    private func suspend(_ message: String, failure: String = "source") {
        suspendedForLayout = true; risk.reset(); scene.reset()
        onPacket?(LocalPacket(type: "unavailable", contextSessionID: settings?.sessionID, contextRevision: settings?.revision, message: message, failure: failure))
    }

    private func preview(_ image: CIImage) -> Data? {
        let scale = min(1, 640 / image.extent.width)
        let scaled = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        guard let cg = context.createCGImage(scaled, from: scaled.extent) else { return nil }
        return UIImage(cgImage: cg).jpegData(compressionQuality: 0.6)
    }

    private func blank(_ image: CIImage, region: CaptureRegion) -> Bool {
        let rect = CGRect(x: image.extent.minX + region.x*image.extent.width,
                          y: image.extent.minY + (1-region.y-region.height)*image.extent.height,
                          width: region.width*image.extent.width, height: region.height*image.extent.height)
        let cropped = image.cropped(to: rect).transformed(by: CGAffineTransform(translationX: -rect.minX, y: -rect.minY))
            .transformed(by: CGAffineTransform(scaleX: 16/rect.width, y: 16/rect.height))
        var rgba = [UInt8](repeating: 0, count: 16*16*4)
        rgba.withUnsafeMutableBytes { bytes in
            context.render(cropped, toBitmap: bytes.baseAddress!, rowBytes: 64,
                           bounds: CGRect(x: 0, y: 0, width: 16, height: 16), format: .RGBA8,
                           colorSpace: CGColorSpaceCreateDeviceRGB())
        }
        var sum = 0.0
        for i in Swift.stride(from: 0, to: rgba.count, by: 4) { sum += Double(rgba[i])+Double(rgba[i+1])+Double(rgba[i+2]) }
        return sum / (256*3) < 4
    }
    static var memoryMB: Double {
        var info = mach_task_basic_info()
        var count = mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size / MemoryLayout<natural_t>.size)
        let result = withUnsafeMutablePointer(to: &info) { pointer in
            pointer.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), $0, &count)
            }
        }
        return result == KERN_SUCCESS ? Double(info.resident_size) / 1_048_576 : 0
    }
}
