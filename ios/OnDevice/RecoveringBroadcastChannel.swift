import Foundation

/// Broadcast recording outlives its connection to the containing app. This
/// reconnects authenticated IPC; it neither wakes the app nor keeps it running.
final class RecoveringBroadcastChannel: @unchecked Sendable {
    var onPacket: ((LocalPacket) -> Void)?
    var onState: ((Bool, String) -> Void)?
    private let channel: LoopbackChannel
    private let queue = DispatchQueue(label: "sky.broadcast.recovery")
    private var stopped = true
    private var retry: DispatchWorkItem?
    private var attempts = 0
    private var epoch = UUID()

    init(token: String) {
        channel = LoopbackChannel(role: .broadcast, token: token)
        channel.onPacket = { [weak self] packet in
            guard let self else { return }
            self.queue.async { if !self.stopped { self.onPacket?(packet) } }
        }
        channel.onState = { [weak self] connected, message in
            guard let self else { return }
            self.queue.async {
                guard !self.stopped else { return }
                self.retry?.cancel(); self.retry = nil
                self.onState?(connected, message)
                if connected { self.attempts = 0; return }
                let expected = self.epoch
                let delay = min(8.0, 0.5 * pow(2, Double(min(self.attempts, 4))))
                self.attempts += 1
                let work = DispatchWorkItem { [weak self = self] in
                    guard let self, !self.stopped, self.epoch == expected else { return }
                    self.channel.start()
                }
                self.retry = work
                self.queue.asyncAfter(deadline: .now()+delay, execute: work)
            }
        }
    }
    func start() {
        queue.async {
            self.epoch = UUID(); self.stopped = false; self.attempts = 0
            self.retry?.cancel(); self.retry = nil; self.channel.start()
        }
    }
    func send(_ packet: LocalPacket, completion: ((Bool) -> Void)? = nil) {
        channel.send(packet, completion: completion)
    }
    func stop() {
        queue.async {
            self.stopped = true; self.epoch = UUID()
            self.retry?.cancel(); self.retry = nil; self.channel.stop()
        }
    }
}
