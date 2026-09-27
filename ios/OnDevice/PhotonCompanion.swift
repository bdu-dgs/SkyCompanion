import Foundation
import Combine
import Security
import CaptureCore

private struct PhotonLocalState: Codable, Sendable {
    var outbox = PhotonOutbox()
    var messages: [PhotonMessage] = []
    var cursor: Int64 = 0
    // Optional for compatibility with local files saved before lifecycle journaling.
    var openTripID: String?
    var preferences: AlertPreferences?
}

/// Disk work runs away from the audio/vision executor. Older snapshots cannot overwrite newer ones.
private actor PhotonDisk {
    let url: URL
    private var revision: UInt64 = 0
    init(url: URL) { self.url = url }
    func save(_ state: PhotonLocalState, revision: UInt64) throws {
        guard revision >= self.revision else { return }
        let directory = url.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var resource = directory
        var values = URLResourceValues(); values.isExcludedFromBackup = true
        try resource.setResourceValues(values)
        try JSONEncoder().encode(state).write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        self.revision = revision
    }
}

private final class PhotonNoRedirect: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil) // Never forward the bearer token to a redirect destination.
    }
}

/// Optional, noncritical companion transport. Obstacle speech never awaits this object.
@MainActor
final class PhotonCompanion: ObservableObject {
    @Published var enabled = UserDefaults.standard.bool(forKey: "photon.enabled") {
        didSet {
            UserDefaults.standard.set(enabled, forKey: "photon.enabled")
            if enabled { syncNow() } else { status = "Photon disabled. Pending records stay on this phone." }
        }
    }
    @Published var endpoint = UserDefaults.standard.string(forKey: "photon.endpoint") ?? ""
    @Published var token = ""
    @Published private(set) var status = "Photon disabled"
    @Published private(set) var agentName = "SkyCompanion Assistant"
    @Published private(set) var messages: [PhotonMessage] = []
    @Published private(set) var lastAlertID: String?
    @Published private(set) var pendingCount = 0
    @Published private(set) var preferences = AlertPreferences()
    @Published private(set) var preferencesStatus = "Using saved alert preferences"
    var onMessage: ((PhotonMessage) -> Void)?
    var hasCurrentTrip: Bool { currentTrip != nil && state.openTripID == currentTrip }

    private var state = PhotonLocalState()
    private let disk: PhotonDisk
    private let session: URLSession
    private var savedEndpoint = ""
    private var savedToken = ""
    private var revision: UInt64 = 0
    private var generation: UInt64 = 0
    private var worker: Task<Void, Never>?
    private var foreground = true
    private var sessionActive = false
    private var currentTrip: String?
    private var tripOpen: Bool { state.openTripID != nil }
    private var connectedAtMS: Int64 = PhotonCompanion.nowMS
    private var storageOK = true
    private var suppressNextPollSpeech = false
    private var failures = 0
    private var nextAttempt = Date.distantPast
    private static var nowMS: Int64 { Int64(Date().timeIntervalSince1970 * 1_000) }

    init() {
        let url = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("SkyCompanion/Photon/state.json")
        disk = PhotonDisk(url: url)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 12
        configuration.timeoutIntervalForResource = 20
        configuration.httpShouldSetCookies = false
        configuration.urlCache = nil
        session = URLSession(configuration: configuration, delegate: PhotonNoRedirect(), delegateQueue: nil)
        savedEndpoint = endpoint
        savedToken = Self.loadToken(); token = savedToken
        // One bounded startup read occurs before a trip/audio processing starts.
        do {
            if FileManager.default.fileExists(atPath: url.path) {
                let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
                guard size <= 32_000_000 else { throw ClientError.invalidLocalData }
                let loaded = try JSONDecoder().decode(PhotonLocalState.self, from: Data(contentsOf: url))
                guard loaded.outbox.records.count <= PhotonOutbox.capacity, loaded.messages.count <= 200,
                      loaded.cursor >= 0 else { throw ClientError.invalidLocalData }
                state = loaded
                if let preferences = loaded.preferences, preferences.isValid { self.preferences = preferences }
            }
            refreshPublished()
        } catch {
            storageOK = false; status = "Photon local history could not be read. Clear local Photon data to recover."
        }
        if storageOK { _ = recoverInterruptedTrip() }
        #if DEBUG
        // Explicit development-device provisioning; secrets are saved only in Keychain.
        let launchEnvironment = ProcessInfo.processInfo.environment
        if let origin = launchEnvironment["SKY_PHOTON_BOOTSTRAP_URL"],
           let uploadToken = launchEnvironment["SKY_PHOTON_BOOTSTRAP_TOKEN"],
           storageOK {
            if launchEnvironment["SKY_PHOTON_RECONNECT"] == "1", uploadToken == savedToken,
               savedToken.utf16.count >= 24, Self.validEndpoint(origin) != nil {
                // Explicit host provisioning for a renewed tunnel to the SAME account.
                // Keep unsent record IDs, inbox cursor, and preferences; never discard a queue to reconnect.
                savedEndpoint = origin; endpoint = origin
                UserDefaults.standard.set(origin, forKey: "photon.endpoint")
                connectedAtMS = Self.nowMS
                suppressNextPollSpeech = true
                enabled = true
            } else if pendingCount == 0 && !tripOpen {
                endpoint = origin; token = uploadToken
                saveConfiguration()
                if savedEndpoint == origin && savedToken == uploadToken { enabled = true }
            }
        }
        #endif
        if enabled && storageOK { syncNow() }
    }

    /// Changes are explicitly saved; editing a field never reroutes existing records to another account.
    func saveConfiguration() {
        guard storageOK else { return }
        let candidate = endpoint.trimmingCharacters(in: .whitespacesAndNewlines)
        let secret = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard Self.validEndpoint(candidate) != nil, secret.utf16.count >= 24, secret.utf16.count <= 4_096,
              !secret.contains("\n"), !secret.contains("\r") else {
            status = "Enter an HTTPS server origin and an upload token of at least 24 characters. HTTP localhost is simulator-only."; return
        }
        let changed = candidate != savedEndpoint || secret != savedToken
        guard !changed || (pendingCount == 0 && !tripOpen && worker == nil) else {
            status = "Disable Photon after ending the trip and syncing pending records before changing its account/server."; return
        }
        guard Self.storeToken(secret) else { status = "Could not save the Photon token in Keychain."; return }
        savedEndpoint = candidate; savedToken = secret; endpoint = candidate; token = secret
        UserDefaults.standard.set(candidate, forKey: "photon.endpoint")
        if changed {
            state.messages = []; state.cursor = 0; agentName = "SkyCompanion Assistant"
            state.preferences = nil; preferences = AlertPreferences()
            preferencesStatus = "Using default alert preferences"
            connectedAtMS = Self.nowMS; persistSoon(); refreshPublished()
        }
        status = "Photon configuration saved."
        syncNow()
    }

    func startTrip(sessionID: String, source: String, chinese: Bool) {
        guard enabled, validID(sessionID), validID("start-\(sessionID)"), ["drone", "video"].contains(source) else { return }
        if currentTrip == sessionID {
            // Do not replay a start (or reopen an ended trip) with a reused session ID.
            return
        }
        guard Self.validEndpoint(savedEndpoint) != nil, savedToken.utf16.count >= 24 else {
            status = "Save the Photon configuration before starting its trip log."; return
        }
        if let existing = state.openTripID, currentTrip == existing {
            endTrip(sessionID: existing, reason: "A new trip replaced the previous trip; its log may be incomplete.")
        }
        guard recoverInterruptedTrip() else { return }
        var record = PhotonRecord(id: "start-\(sessionID)", kind: "start", sessionID: sessionID, atMS: Self.nowMS)
        record.source = source; record.locale = "en"
        state.openTripID = sessionID
        if enqueue(record) { currentTrip = sessionID; lastAlertID = nil }
        else { state.openTripID = nil }
    }

    /// Call only from the obstacle utterance's playback-start callback, never from detection alone.
    func recordAlert(event: MobileRiskEvent, spokenText: String, category: String, observedAtMS: Int64) {
        recordObstacleSpeech(eventID: event.id, sessionID: event.sessionID, frameID: event.frameID,
            spokenText: spokenText, category: category,
            direction: event.direction == .ahead ? "center" : event.direction.rawValue,
            evidence: event.reasonCodes + ["direction_basis:cameraImage", "kind:\(event.evidence.kind)",
                "observations:\(event.evidence.observations)"], observedAtMS: observedAtMS)
    }

    /// Shared capture for ordinary risk and rear-following obstacle speech. Health/status speech is excluded by the caller.
    func recordObstacleSpeech(eventID: String, sessionID: String, frameID: UInt64, spokenText: String,
                              category: String, direction: String, evidence: [String], observedAtMS: Int64) {
        guard enabled, hasCurrentTrip, currentTrip == sessionID,
              validID(eventID), validID("alert-\(eventID)"), frameID <= 9_007_199_254_740_991,
              ["left", "center", "right", "unknown"].contains(direction),
              observedAtMS >= 946_684_800_000, observedAtMS <= Self.nowMS + 300_000 else { return }
        let cleanText = PhotonPolicy.boundedText(spokenText, limit: 1_000)
        guard !cleanText.isEmpty else { status = "Photon alert text was empty; record was not queued."; return }
        var record = PhotonRecord(id: "alert-\(eventID)", kind: "alert", sessionID: sessionID, atMS: Self.nowMS)
        record.eventID = eventID; record.frameID = frameID
        let cleanCategory = PhotonPolicy.boundedText(category, limit: 100)
        record.category = cleanCategory.isEmpty ? "obstacle" : cleanCategory; record.direction = direction
        record.text = cleanText; record.observedAtMS = observedAtMS; record.speechStatus = "started"
        record.evidence = Array(evidence.prefix(16)).map { PhotonPolicy.boundedText($0, limit: 160) }.filter { !$0.isEmpty }
        if enqueue(record) { lastAlertID = eventID }
    }

    func endTrip(sessionID: String, reason: String) {
        // Closing an already logged trip is durable even if sharing was disabled mid-trip.
        guard state.openTripID == sessionID else { return }
        var record = PhotonRecord(id: "end-\(sessionID)", kind: "end", sessionID: sessionID, atMS: Self.nowMS)
        let cleanReason = PhotonPolicy.boundedText(reason, limit: 500)
        record.reason = cleanReason.isEmpty ? "Trip ended by the app." : cleanReason
        state.openTripID = nil
        if !enqueue(record) { state.openTripID = sessionID }
        // Keep this process's most recent trip eligible for its just-finished summary.
        sessionActive = false
    }

    func reportFalseAlert(eventID: String, sessionID: String, note: String) {
        guard enabled, validID(eventID), validID(sessionID) else { return }
        guard currentTrip == sessionID, lastAlertID == eventID else {
            status = "No matching Photon alert was logged for this correction. The local correction can still be reviewed."; return
        }
        var record = PhotonRecord(kind: "feedback", sessionID: sessionID, atMS: Self.nowMS)
        record.eventID = eventID
        let cleanNote = PhotonPolicy.boundedText(note, limit: 1_000)
        record.note = cleanNote.isEmpty ? "The user reported that this alert was incorrect." : cleanNote
        if enqueue(record) { status = "Correction queued. It will be reviewed; the model is not changed automatically." }
    }

    func ask(question: String, sessionID: String) {
        let question = PhotonPolicy.boundedText(question, limit: 1_000)
        guard enabled, validID(sessionID), !question.isEmpty else { return }
        guard currentTrip == sessionID else { status = "Start a Photon trip log before asking about this trip."; return }
        var record = PhotonRecord(kind: "query", sessionID: sessionID, atMS: Self.nowMS)
        record.question = question; _ = enqueue(record)
    }
    func setForeground(_ value: Bool) {
        if value && !foreground { connectedAtMS = Self.nowMS }
        foreground = value; if value { syncNow() }
    }
    func setSessionActive(_ value: Bool) { sessionActive = value; if value { syncNow() } }

    /// Explicit UI action: discard the local queue/history and token, never remote history.
    func deleteLocalData() {
        enabled = false; generation &+= 1; worker?.cancel(); worker = nil
        state = PhotonLocalState(); preferences = AlertPreferences(); preferencesStatus = "Using default alert preferences"; currentTrip = nil; lastAlertID = nil
        token = ""; savedToken = ""; Self.deleteToken()
        storageOK = true; failures = 0; nextAttempt = .distantPast
        refreshPublished(); persistSoon(); status = "Local Photon records and token deleted."
    }

    func syncNow() {
        guard worker == nil, enabled, storageOK, foreground || sessionActive else { return }
        let epoch = generation
        worker = Task { [weak self] in
            guard let self else { return }
            defer { if self.generation == epoch { self.worker = nil } }
            while !Task.isCancelled && self.generation == epoch && self.enabled && (self.foreground || self.sessionActive) {
                guard self.storageOK, let endpoint = Self.validEndpoint(self.savedEndpoint), self.savedToken.utf16.count >= 24 else {
                    if self.storageOK { self.status = "Save the Photon HTTPS endpoint and token first." }; return
                }
                if Date() >= self.nextAttempt {
                    do {
                        // Persist IDs and ordering before any network request.
                        try await self.disk.save(self.state, revision: self.revision)
                        try Task.checkCancellation()
                        guard self.enabled && (self.foreground || self.sessionActive) else { return }
                        // Preferences are independent of trip recording and take effect only after durable local storage.
                        do {
                            let policy: AlertPreferences = try await self.request(endpoint: endpoint, token: self.savedToken, path: "v1/preferences")
                            guard self.generation == epoch, self.enabled else { return }
                            guard policy.isValid else { throw ClientError.invalidResponse }
                            self.state.preferences = policy; self.revision &+= 1
                            try await self.disk.save(self.state, revision: self.revision)
                            guard self.generation == epoch, self.enabled else { return }
                            self.preferences = policy
                            self.preferencesStatus = "Applied on this iPhone · revision \(policy.revision)"
                            if policy.appliedRevision != policy.revision {
                                let acknowledgement: AlertPreferences = try await self.request(endpoint: endpoint,
                                    token: self.savedToken, path: "v1/preferences/applied", appliedRevision: policy.revision)
                                guard acknowledgement.isValid else { throw ClientError.invalidResponse }
                            }
                        } catch {
                            self.preferencesStatus = "Using saved preferences · sync/confirmation pending"
                        }
                        let batch = self.state.outbox.batch()
                        if !batch.isEmpty {
                            let result: PhotonSyncResponse = try await self.request(endpoint: endpoint, token: self.savedToken, path: "v1/sync", records: batch)
                            guard self.generation == epoch else { return }
                            guard self.state.outbox.acknowledge(batch, accepted: result.accepted, duplicates: result.duplicates) else {
                                throw ClientError.invalidResponse
                            }
                            self.revision &+= 1
                            try await self.disk.save(self.state, revision: self.revision)
                            self.refreshPublished()
                        }
                        guard self.enabled && (self.foreground || self.sessionActive) else { return }
                        let after = self.state.cursor
                        let result: PhotonInboxResponse = try await self.request(endpoint: endpoint, token: self.savedToken, path: "v1/messages", after: after)
                        guard self.generation == epoch else { return }
                        guard PhotonPolicy.validInbox(result, after: after) else { throw ClientError.invalidResponse }
                        let newMessages = result.messages.filter { message in !self.state.messages.contains { $0.id == message.id } }
                        self.state.messages = Array((self.state.messages + newMessages).suffix(200))
                        self.state.cursor = result.cursor; self.agentName = result.agentName; self.revision &+= 1
                        try await self.disk.save(self.state, revision: self.revision)
                        guard self.generation == epoch else { return }
                        self.refreshPublished(); self.failures = 0
                        if self.suppressNextPollSpeech {
                            self.connectedAtMS = Self.nowMS; self.suppressNextPollSpeech = false
                        }
                        self.status = self.pendingCount == 0 ? "Photon connected" : "Photon syncing \(self.pendingCount) records"
                        #if DEBUG
                        if ProcessInfo.processInfo.environment["SKY_PHOTON_BOOTSTRAP_URL"] != nil {
                            print("Photon device sync OK: pending=\(self.pendingCount), inbox=\(self.messages.count), cursor=\(self.state.cursor)")
                        }
                        #endif
                        if self.enabled && (self.foreground || self.sessionActive) {
                            for message in newMessages where message.shouldAnnounce(sessionID: self.currentTrip,
                                connectedAtMS: self.connectedAtMS, nowMS: Self.nowMS) { self.onMessage?(message) }
                        }
                        self.nextAttempt = Date().addingTimeInterval(self.pendingCount > 0 ? 0 : 5)
                    } catch {
                        guard self.generation == epoch, !Task.isCancelled else { return }
                        self.failures = min(self.failures + 1, 6)
                        self.nextAttempt = Date().addingTimeInterval(min(60, pow(2, Double(self.failures))))
                        self.connectedAtMS = Self.nowMS; self.suppressNextPollSpeech = true
                        self.status = "Photon sync failed (\(Self.safeDescription(error))). \(self.pendingCount) records retained; retrying."
                    }
                }
                try? await Task.sleep(nanoseconds: 500_000_000)
            }
        }
    }

    /// A previous process cannot prove trip completion. Close its log explicitly as interrupted.
    @discardableResult private func recoverInterruptedTrip() -> Bool {
        guard let interrupted = state.openTripID else { return true }
        guard currentTrip != interrupted else { return false }
        guard state.outbox.reconcileInterruptedTrip(sessionID: interrupted, atMS: Self.nowMS) else {
            status = "Photon queue is full; the interrupted trip will close after syncing."; return false
        }
        state.openTripID = nil; refreshPublished(); persistSoon()
        status = "Previous Photon trip was interrupted by an app restart; its log may be incomplete."
        return true
    }

    private func enqueue(_ record: PhotonRecord) -> Bool {
        guard storageOK else { status = "Photon local storage is unavailable; this record was not queued."; return false }
        guard state.outbox.append(record) else {
            status = "Photon queue is full. This record was not saved; sync or clear local data before adding more."; return false
        }
        refreshPublished(); persistSoon(); if failures == 0 { nextAttempt = .distantPast }; syncNow(); return true
    }
    private func refreshPublished() { messages = state.messages; pendingCount = state.outbox.records.count }
    private func persistSoon() {
        revision &+= 1
        let snapshot = state, version = revision, epoch = generation
        Task { [weak self, disk] in
            do { try await disk.save(snapshot, revision: version) }
            catch {
                guard let self, self.generation == epoch else { return }
                self.storageOK = false
                self.status = "Photon records could not be saved on this phone. Local obstacle warnings still work."
            }
        }
    }
    private func validID(_ value: String) -> Bool { PhotonPolicy.validIdentifier(value) }
    private static func validEndpoint(_ value: String) -> URL? {
        #if targetEnvironment(simulator)
        return PhotonPolicy.endpoint(value, allowLocalHTTP: true)
        #else
        return PhotonPolicy.endpoint(value, allowLocalHTTP: false)
        #endif
    }
    private nonisolated func request<T: Decodable>(endpoint: URL, token: String, path: String, records: [PhotonRecord]? = nil, after: Int64? = nil, appliedRevision: Int? = nil) async throws -> T {
        var components = URLComponents(url: endpoint.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        if let after { components.queryItems = [URLQueryItem(name: "after", value: String(after))] }
        var request = URLRequest(url: components.url!)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let records {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(["records": records])
        }
        if let appliedRevision {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(["revision": appliedRevision])
        }
        let (bytes, response) = try await session.bytes(for: request)
        guard let response = response as? HTTPURLResponse else { throw ClientError.invalidResponse }
        guard (200..<300).contains(response.statusCode) else { throw ClientError.http(response.statusCode) }
        guard response.expectedContentLength <= 1_000_000 else { throw ClientError.responseTooLarge }
        var data = Data()
        for try await byte in bytes {
            guard data.count < 1_000_000 else { throw ClientError.responseTooLarge }
            data.append(byte)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
    private enum ClientError: Error { case invalidResponse, responseTooLarge, invalidLocalData, http(Int) }
    private static func safeDescription(_ error: Error) -> String {
        if case ClientError.http(let code) = error { return "HTTP \(code)" }
        if error is DecodingError { return "invalid server response" }
        if error is URLError { return "network unavailable" }
        return "response or local storage unavailable"
    }
    private static var keychainQuery: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "SkyCompanion.Photon",
         kSecAttrAccount as String: "ingest-token"]
    }
    private static func loadToken() -> String {
        var query = keychainQuery; query[kSecReturnData as String] = true; query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess, let data = result as? Data else { return "" }
        return String(data: data, encoding: .utf8) ?? ""
    }
    private static func storeToken(_ value: String) -> Bool {
        let attributes: [String: Any] = [kSecValueData as String: Data(value.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        let result = SecItemUpdate(keychainQuery as CFDictionary, attributes as CFDictionary)
        if result == errSecSuccess { return true }
        guard result == errSecItemNotFound else { return false }
        return SecItemAdd(keychainQuery.merging(attributes) { _, new in new } as CFDictionary, nil) == errSecSuccess
    }
    private static func deleteToken() { SecItemDelete(keychainQuery as CFDictionary) }
}
