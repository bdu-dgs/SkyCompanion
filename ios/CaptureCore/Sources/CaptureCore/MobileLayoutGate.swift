/// Ignores app-switch/rotation frames during startup; never tolerates a layout change after acceptance.
public struct MobileLayoutGate {
    public enum Decision: Equatable { case waiting, accept, changed }
    private struct Layout: Equatable {
        let width: Double
        let height: Double
        let orientation: UInt32
    }
    private var candidate: Layout?
    private var candidateSince = 0.0
    private var accepted: Layout?

    public init() {}

    public mutating func evaluate(width: Double, height: Double, orientation: UInt32,
                                  capturedMS: Double) -> Decision {
        let layout = Layout(width: width, height: height, orientation: orientation)
        if let accepted { return layout == accepted ? .accept : .changed }
        guard width.isFinite, height.isFinite, capturedMS.isFinite, width > 0, height > 0 else {
            candidate = nil
            return .waiting
        }
        if candidate != layout || capturedMS < candidateSince {
            candidate = layout; candidateSince = capturedMS
            return .waiting
        }
        guard capturedMS - candidateSince >= 500 else { return .waiting }
        accepted = layout
        return .accept
    }
}
