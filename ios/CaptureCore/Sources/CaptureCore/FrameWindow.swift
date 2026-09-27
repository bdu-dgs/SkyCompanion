import Foundation

/// Fixed time slots avoid reducing 15 FPS to 10 FPS when 30 FPS callbacks have
/// small timing variations. Missed slots are skipped, never queued for catch-up.
public struct CaptureCadence {
    private let intervalMS: Double
    private var nextDueMS: Double?

    public init(framesPerSecond: Double = 15) {
        precondition(framesPerSecond.isFinite && framesPerSecond > 0)
        intervalMS = 1_000 / framesPerSecond
    }

    public mutating func take(at nowMS: Double) -> Bool {
        guard nowMS.isFinite else { return false }
        guard let due = nextDueMS else {
            nextDueMS = nowMS + intervalMS
            return true
        }
        guard nowMS + 0.001 >= due else { return false }
        let skipped = max(0, floor((nowMS - due) / intervalMS))
        nextDueMS = due + (skipped + 1) * intervalMS
        return true
    }

    public mutating func reset() { nextDueMS = nil }
}

/// A single queue owns this value. No raw screen buffers or growing frame queues live here.
public struct CaptureFrame {
    public let id: Int
    public let capturedMS: Double
    public let width: Int
    public let height: Int
    public let orientation: Int
    public let jpeg: Data

    public init(id: Int, capturedMS: Double, width: Int, height: Int, orientation: Int, jpeg: Data) {
        self.id = id
        self.capturedMS = capturedMS
        self.width = width
        self.height = height
        self.orientation = orientation
        self.jpeg = jpeg
    }
}

public struct FrameWindow {
    public private(set) var pending: CaptureFrame?
    public private(set) var unacknowledgedID: Int?
    public private(set) var sentAtMS: Double?
    private var captureTimes: [Int: Double] = [:]
    public let receiptLimit: Int

    public init(receiptLimit: Int = 64) { self.receiptLimit = max(1, receiptLimit) }

    public mutating func offer(_ frame: CaptureFrame) {
        // Encoding can finish after a pause. Caller additionally checks its epoch.
        guard pending == nil || frame.id > pending!.id else { return }
        pending = frame
    }

    public mutating func take(nowMS: Double) -> CaptureFrame? {
        guard unacknowledgedID == nil, let frame = pending else { return nil }
        pending = nil
        // Never send a stale pending screenshot after a slow server/network recovers.
        guard nowMS - frame.capturedMS <= 2_000 else { return nil }
        unacknowledgedID = frame.id
        sentAtMS = nowMS
        captureTimes[frame.id] = frame.capturedMS
        if captureTimes.count > receiptLimit, let oldest = captureTimes.keys.min() {
            captureTimes.removeValue(forKey: oldest)
        }
        return frame
    }

    @discardableResult
    public mutating func accept(frameID: Int) -> Bool {
        guard unacknowledgedID == frameID else { return false }
        unacknowledgedID = nil
        sentAtMS = nil
        return true
    }

    public mutating func displayLatency(frameID: Int, nowMS: Double) -> Double? {
        guard let captured = captureTimes.removeValue(forKey: frameID) else { return nil }
        let latency = nowMS - captured
        return latency >= 0 && latency <= 30_000 ? latency : nil
    }

    public func acknowledgementExpired(nowMS: Double, timeoutMS: Double = 2_500) -> Bool {
        guard let sentAtMS else { return false }
        return nowMS - sentAtMS > timeoutMS
    }

    public mutating func discardPendingAndReceipts() {
        // A pause invalidates images, but an already transmitted packet still
        // occupies the network window until its accepted reply (or timeout).
        pending = nil
        captureTimes.removeAll(keepingCapacity: true)
    }

    public mutating func clear() {
        pending = nil
        unacknowledgedID = nil
        sentAtMS = nil
        captureTimes.removeAll(keepingCapacity: true)
    }
}
