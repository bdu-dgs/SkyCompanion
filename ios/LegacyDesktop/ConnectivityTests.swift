import Foundation

@main
struct ConnectivityTests {
    static func main() throws {
        var count = 0
        func check(_ value: @autoclosure () -> Bool, _ name: String) {
            precondition(value(), name)
            count += 1
        }
        let old = Data(#"{"server_url":"http://Mac.local:8000","token":"test-only-pairing-token"}"#.utf8)
        let config = try JSONDecoder().decode(CaptureConfiguration.self, from: old)
        check(config.fallbackServerURLs.isEmpty, "Legacy config remains readable")
        check(config.expectedReceiverID == "9491871c7b0093c5", "Public ID matches SHA256 UTF8 prefix")
        let ip = URL(string: "http://192.168.1.165:8000")!
        let conf = CaptureConfiguration(serverURL: config.serverURL, token: config.token, fallbackServerURLs: [ip, ip])
        check(ReceiverConnectionPolicy.candidates(configuration: conf, lastSuccessful: ip) == [ip, config.serverURL], "Verified cache priority and duplicates")
        check(conf.replacingServerURL(ip).fallbackServerURLs.contains(config.serverURL), "Resolved config retains original hostname fallback")
        check(ReceiverConnectionPolicy.uniqueURLs([ip, URL(string: ip.absoluteString + "/")!]).count == 1, "Trailing-slash duplicates")
        check((1...6).map { ReceiverConnectionPolicy.retryDelay(attempt: $0) } == [1,2,4,8,8,8], "Bounded reconnect backoff")
        check(!ReceiverConnectionPolicy.matches(receiverID: nil, expected: config.expectedReceiverID), "No unpaired Bonjour fallback")
        check(!ReceiverConnectionPolicy.matches(receiverID: "other", expected: config.expectedReceiverID), "Wrong receiver ignored")
        check(ReceiverConnectionPolicy.endpointURL(host: "192.168.1.165", port: 8000)?.absoluteString == ip.absoluteString, "IPv4 discovered URL")
        check(ReceiverConnectionPolicy.endpointURL(host: "2001:db8::1", port: 8000)?.absoluteString == "http://[2001:db8::1]:8000", "IPv6 bracket handling")
        check(ReceiverConnectionPolicy.endpointURL(host: "fe80::1%en0", port: 8000)?.absoluteString.contains("%25en0") == true, "IPv6 scoped URL escaping")
        check(ReceiverConnectionPolicy.endpointURL(host: "192.168.1.1", port: 8000, scheme: "ftp") == nil, "Unsupported discovery scheme rejected")
        for json in [
            #"{"server_url":"http://Mac.local:8000","token":"test-only-pairing-token","receiver_id":"wrong"}"#,
            #"{"server_url":"http://Mac.local:8000","token":"test-only-pairing-token","fallback_server_urls":["ftp://192.168.1.1"]}"#,
            #"{"server_url":"http://user:secret@Mac.local:8000","token":"test-only-pairing-token"}"#
        ] {
            do { _ = try JSONDecoder().decode(CaptureConfiguration.self, from: Data(json.utf8)); preconditionFailure("Invalid config accepted") }
            catch { count += 1 }
        }
        print("PASS: \(count) desktop connectivity policy checks")
    }
}
