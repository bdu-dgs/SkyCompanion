import Foundation
import AVFoundation
import Network
import CryptoKit
import CaptureCore

private final class Recorder: @unchecked Sendable {
    private let lock = NSLock()
    private var states: [(Bool,String)] = []
    private var packets: [LocalPacket] = []
    func state(_ ready: Bool, _ message: String) { lock.lock(); states.append((ready,message)); lock.unlock() }
    func packet(_ packet: LocalPacket) { lock.lock(); packets.append(packet); lock.unlock() }
    var allStates: [(Bool,String)] { lock.lock(); defer { lock.unlock() }; return states }
    var allPackets: [LocalPacket] { lock.lock(); defer { lock.unlock() }; return packets }
    var authenticated: Bool { allStates.contains { $0.0 } }
    func failed(_ fragment: String) -> Bool { allStates.contains { !$0.0 && $0.1.contains(fragment) } }
}

private final class RawPeer: @unchecked Sendable {
    let recorder = Recorder()
    let connection = NWConnection(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: DevicePairing.port)!, using: .tcp)
    private let queue = DispatchQueue(label: "skycompanion.test.raw")
    private var buffer = Data()
    init() {
        connection.stateUpdateHandler = { [weak self] state in
            guard let self else { return }
            switch state {
            case .ready: self.recorder.state(true,"TCP ready"); self.receive()
            case .failed(let error): self.recorder.state(false,error.localizedDescription)
            default: break
            }
        }
        connection.start(queue: queue)
    }
    func send(_ packet: LocalPacket) throws { var data = try JSONEncoder().encode(packet); data.append(10); send(data) }
    func send(_ data: Data) { connection.send(content: data, completion: .contentProcessed { _ in }) }
    func close() { connection.cancel() }
    private func receive() {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65_536) { [weak self] data,_,done,error in
            guard let self else { return }
            if let data {
                self.buffer.append(data)
                while let index = self.buffer.firstIndex(of: 10) {
                    let line = self.buffer.prefix(upTo: index); self.buffer.removeSubrange(...index)
                    if let packet = try? JSONDecoder().decode(LocalPacket.self, from: line) { self.recorder.packet(packet) }
                }
            }
            if !done && error == nil { self.receive() }
        }
    }
}

private let sharedKey = String(repeating: "skycompanion-test-secret-", count: 4)
private func wait(_ condition: () -> Bool, timeout: Double = 4) throws {
    let deadline = ProcessInfo.processInfo.systemUptime + timeout
    while !condition() {
        if ProcessInfo.processInfo.systemUptime >= deadline { throw Failure("Condition timed out") }
        Thread.sleep(forTimeInterval: 0.01)
    }
}
private struct Failure: Error, CustomStringConvertible { let description: String; init(_ s: String) { description=s } }
private func require(_ condition: Bool, _ message: String) throws { if !condition { throw Failure(message) } }
private func makeServer() throws -> (LoopbackChannel,Recorder) {
    let recorder=Recorder(), server=LoopbackChannel(role:.app,token:sharedKey)
    server.onState=recorder.state;server.onPacket=recorder.packet;server.start()
    do { try wait { recorder.allStates.contains { $0.1.contains("Ready for") } } }
    catch { server.stop(); throw Failure("Listener could not become ready: \(recorder.allStates)") }
    return (server,recorder)
}
private func close(_ channel: LoopbackChannel, _ peer: RawPeer? = nil) {
    peer?.close();channel.stop();Thread.sleep(forTimeInterval:0.15)
}
private func proof(senderRole: String, senderNonce: String, receiverRole: String, receiverNonce: String) -> String {
    let transcript=Data(["skycompanion-loopback-v1",senderRole,senderNonce,receiverRole,receiverNonce].joined(separator:"\n").utf8)
    return HMAC<SHA256>.authenticationCode(for:transcript,using:SymmetricKey(data:Data(sharedKey.utf8)))
        .map { String(format:"%02x",$0) }.joined()
}
private func rawHandshake(_ peer: RawPeer, server: Recorder) throws -> LocalPacket {
    try wait { peer.recorder.allPackets.contains { $0.type == "hello" } }
    let hello=peer.recorder.allPackets.first { $0.type == "hello" }!
    let nonce=UUID().uuidString.replacingOccurrences(of:"-",with:"").lowercased()+UUID().uuidString.replacingOccurrences(of:"-",with:"").lowercased()
    try peer.send(LocalPacket(type:"hello",handshakeRole:"broadcast",nonce:nonce))
    try wait { peer.recorder.allPackets.contains { $0.type == "authenticate" } }
    let auth=peer.recorder.allPackets.first { $0.type == "authenticate" }!
    try require(auth.proof == proof(senderRole:"app",senderNonce:hello.nonce!,receiverRole:"broadcast",receiverNonce:nonce),"Server HMAC invalid")
    let packet=LocalPacket(type:"authenticate",handshakeRole:"broadcast",proof:proof(senderRole:"broadcast",senderNonce:nonce,receiverRole:"app",receiverNonce:hello.nonce!))
    try peer.send(packet)
    try wait { server.authenticated }
    return packet
}

@main
struct MobileLoopbackTests {
    static func main() {
        var failures=[String]();var passed=[String]()
        func test(_ name:String,_ block:() throws -> Void) {
            do { try block();passed.append(name);print("PASS \(name)") }
            catch { failures.append("\(name): \(error)");print("FAIL \(name): \(error)");Thread.sleep(forTimeInterval:0.2) }
        }
        test("mutual authentication and bidirectional application packets") {
            let (server,a)=try makeServer();let b=Recorder();let client=LoopbackChannel(role:.broadcast,token:sharedKey)
            defer { client.stop();close(server) }
            client.onState=b.state;client.onPacket=b.packet;client.start()
            try wait { a.authenticated && b.authenticated }
            client.send(LocalPacket(type:"state",message:"from broadcast"));server.send(LocalPacket(type:"command",message:"from app"))
            try wait { a.allPackets.count==1 && b.allPackets.count==1 }
            try require(a.allPackets[0].message=="from broadcast" && b.allPackets[0].message=="from app","Wrong bidirectional payload")
        }
        test("stop keeps transport alive through recording completion") {
            let (server,a)=try makeServer(); let b=Recorder()
            let client=LoopbackChannel(role:.broadcast,token:sharedKey)
            defer { client.stop();close(server) }
            client.onState=b.state
            client.onPacket = { packet in
                b.packet(packet)
                if packet.type == "stop" {
                    client.send(LocalPacket(type:"recordingFinished",message:"Video saved to Photos.")) { sent in
                        b.state(sent,"completion flushed")
                    }
                }
            }
            client.start(); try wait { a.authenticated && b.authenticated }
            server.send(LocalPacket(type:"stop")) { sent in a.state(sent,"stop flushed") }
            try wait { a.allPackets.contains { $0.type == "recordingFinished" }
                && b.allStates.contains { $0.0 && $0.1 == "completion flushed" } }
            try require(a.allPackets.last?.message == "Video saved to Photos.","Final recording outcome lost")
        }
        test("command microphone relay requires recording, preserves PCM and stops after drain") {
            let (server,a)=try makeServer(); let b=Recorder(); let client=LoopbackChannel(role:.broadcast,token:sharedKey)
            defer { client.stop();close(server) }
            client.onState=b.state; client.onPacket=b.packet; client.start()
            try wait { a.authenticated && b.authenticated }
            let relay = RecordingAudioRelay()
            let format = AVAudioFormat(commonFormat:.pcmFormatFloat32,sampleRate:48000,channels:2,interleaved:false)!
            let pcm = AVAudioPCMBuffer(pcmFormat:format,frameCapacity:480)!
            pcm.frameLength = 480
            for i in 0..<480 { pcm.floatChannelData![0][i] = 0.25; pcm.floatChannelData![1][i] = 0.75 }
            let time = AVAudioTime(hostTime:mach_absolute_time())
            relay.capture(pcm,at:time,source:.microphone)
            Thread.sleep(forTimeInterval:0.05)
            try require(b.allPackets.isEmpty,"Audio escaped before recording began")
            relay.start(id:"recording-1",channel:server)
            relay.capture(pcm,at:time,source:.microphone)
            let drained = DispatchSemaphore(value:0)
            relay.finish { drained.signal() }
            try require(drained.wait(timeout:.now()+2) == .success,"Audio drain stalled")
            try wait { b.allPackets.count == 1 }
            let audio = b.allPackets[0].recordingAudio!
            try require(audio.valid && audio.recordingID == "recording-1" && audio.source == .microphone,"Missing recording identity")
            let first = audio.pcm.withUnsafeBytes { $0.loadUnaligned(as:Int16.self) }
            try require(abs(Int(first)-16383) <= 1,"Stereo microphone was not downmixed")
            relay.capture(pcm,at:time,source:.microphone)
            Thread.sleep(forTimeInterval:0.05)
            try require(b.allPackets.count == 1,"Audio escaped after Stop")
            var invalid = audio; invalid.hostSeconds = .nan
            try require(!invalid.valid,"Non-finite clock accepted")
            invalid = audio; invalid.pcm = Data(repeating:0,count:100000)
            try require(!invalid.valid,"Oversized PCM accepted")
        }
        test("broadcast reconnects after app link loss and explicit stop cancels retries") {
            let (server,a)=try makeServer(); let b=Recorder()
            let client=RecoveringBroadcastChannel(token:sharedKey)
            defer { client.stop(); close(server) }
            client.onState=b.state; client.onPacket=b.packet; client.start()
            try wait { a.authenticated && b.authenticated }
            server.stop()
            try wait { b.allStates.contains { !$0.0 } }
            server.start()
            try wait({ a.allStates.filter(\.0).count == 2 && b.allStates.filter(\.0).count == 2 },timeout:12)
            server.send(LocalPacket(type:"recordingStarted",recordingID:"same-recording"))
            try wait { b.allPackets.contains { $0.recordingID == "same-recording" } }
            client.stop()
            try wait { a.failed("disconnected") }
            Thread.sleep(forTimeInterval:1.2)
            try require(a.allStates.filter(\.0).count == 2,"Stopped broadcast reconnected")
        }
        test("wrong key rejected by both peers") {
            let (server,a)=try makeServer();let b=Recorder();let client=LoopbackChannel(role:.broadcast,token:"wrong-secret")
            defer { client.stop();close(server) }
            client.onState=b.state;client.onPacket=b.packet;client.start()
            try wait { a.failed("pairing") && b.allStates.contains { !$0.0 } }
            try require(!a.authenticated && !b.authenticated,"Wrong key authorized")
            try require(a.allPackets.isEmpty && b.allPackets.isEmpty,"Wrong key delivered payload")
        }
        test("hello never leaks key; echo/reflection rejected") {
            let (server,a)=try makeServer();let peer=RawPeer();defer { close(server,peer) }
            try wait { !peer.recorder.allPackets.isEmpty }
            let hello=peer.recorder.allPackets[0]
            let wire=String(decoding:try JSONEncoder().encode(hello),as:UTF8.self)
            try require(!wire.contains(sharedKey) && !wire.contains("token"),"Shared secret appeared on wire")
            try peer.send(hello)
            try wait { a.failed("pairing") }
            try require(!a.authenticated,"Echo authorized unknown peer")
        }
        test("server proof cannot be reflected as client proof") {
            let (server,a)=try makeServer();let peer=RawPeer();defer { close(server,peer) }
            try wait { !peer.recorder.allPackets.isEmpty }
            try peer.send(LocalPacket(type:"hello",handshakeRole:"broadcast",nonce:String(repeating:"a",count:64)))
            try wait { peer.recorder.allPackets.contains { $0.type == "authenticate" } }
            let reflected=peer.recorder.allPackets.first { $0.type == "authenticate" }!
            try peer.send(LocalPacket(type:"authenticate",handshakeRole:"broadcast",proof:reflected.proof))
            try wait { a.failed("pairing") };try require(!a.authenticated,"Reflected HMAC authorized peer")
        }
        test("application packet before proof rejected") {
            let (server,a)=try makeServer();let peer=RawPeer();defer { close(server,peer) }
            try wait { !peer.recorder.allPackets.isEmpty };try peer.send(LocalPacket(type:"result",message:"unauthenticated"))
            try wait { a.failed("pairing") };try require(a.allPackets.isEmpty,"Unauthenticated payload delivered")
        }
        test("previous connection proof cannot authorize new connection") {
            let (server,a)=try makeServer();let first=RawPeer();defer { close(server) }
            let oldProof=try rawHandshake(first,server:a)
            first.close();try wait { a.failed("disconnected") }
            let peer=RawPeer();defer { peer.close() }
            try wait { !peer.recorder.allPackets.isEmpty }
            try peer.send(LocalPacket(type:"hello",handshakeRole:"broadcast",nonce:String(repeating:"b",count:64)))
            try peer.send(oldProof)
            try wait { a.failed("pairing") }
            try require(a.allStates.filter(\.0).count==1,"Replayed proof authorized new connection")
        }
        test("oversized unterminated packet closes connection") {
            let (server,a)=try makeServer();let peer=RawPeer();defer { close(server,peer) }
            _=try rawHandshake(peer,server:a)
            peer.send(Data(repeating:65,count:1_048_577))
            try wait { a.failed("size limit") };try require(a.allPackets.isEmpty,"Oversized data delivered")
        }
        test("large valid packet plus coalesced successor remains valid") {
            let (server,a)=try makeServer();let peer=RawPeer();defer { close(server,peer) }
            _=try rawHandshake(peer,server:a)
            let first=LocalPacket(type:"state",message:String(repeating:"x",count:1_048_400))
            let next=LocalPacket(type:"state",message:String(repeating:"y",count:20_000))
            var joined=try JSONEncoder().encode(first);joined.append(10);joined.append(try JSONEncoder().encode(next));joined.append(10)
            peer.send(joined)
            try wait { a.allPackets.count==2 }
            try require(!a.failed("size limit"),"Coalescing falsely rejected bounded packet")
        }
        test("disconnect clears authorization; old connection cannot inject after reconnect") {
            let (server,a)=try makeServer();let first=RawPeer();defer { close(server) }
            _=try rawHandshake(first,server:a);first.close();try wait { a.failed("disconnected") }
            let second=RawPeer();defer { second.close() };_=try rawHandshake(second,server:a)
            try first.send(LocalPacket(type:"state",message:"old connection"))
            try second.send(LocalPacket(type:"state",message:"new connection"))
            try wait { !a.allPackets.isEmpty };Thread.sleep(forTimeInterval:0.1)
            try require(a.allPackets.count==1 && a.allPackets[0].message=="new connection","Old connection injected packet")
        }
        test("idle unauthenticated connection expires") {
            let (server,a)=try makeServer();let peer=RawPeer();defer { close(server,peer) }
            try wait({a.failed("stopped responding")},timeout:4)
            try require(!a.authenticated,"Idle unknown peer authorized")
        }
        let report:[String:Any]=["passed":passed,"failures":failures,"platform":"macOS Network.framework real localhost TCP","applicationSessionBoundary":"Transport isolates connection epochs; frame sessionID/revision/freshness enforced in LocalSessionModel.receive and CaptureCore tests, not claimed by this harness."]
        if let data=try? JSONSerialization.data(withJSONObject:report,options:[.prettyPrinted,.sortedKeys]) { print(String(decoding:data,as:UTF8.self)) }
        if !failures.isEmpty { exit(1) }
    }
}
