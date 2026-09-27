import ReplayKit
import SwiftUI

struct ContentView: View {
    @StateObject private var connection = ConnectionModel()
    @StateObject private var voice = VoiceModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Label("Phone video playback test", systemImage: "iphone.gen3.radiowaves.left.and.right")
                    Text("Complete the sound check and enable continuous voice assistance below, then start the landscape video test and screen broadcast. Alerts play on the phone; the desktop page is an optional monitor.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Section("1 · Connect to the analysis service") {
                    LabeledContent("Receiver address") {
                        Text(connection.configuration?.serverURL.absoluteString ?? "Not configured")
                            .font(.caption.monospaced())
                            .textSelection(.enabled)
                            .multilineTextAlignment(.trailing)
                    }
                    Button {
                        Task { await connection.checkConnection() }
                    } label: {
                        HStack {
                            Text(connection.checking ? "Checking…" : "Check connection")
                            Spacer()
                            if connection.checking { ProgressView() }
                            else { Image(systemName: "network") }
                        }
                    }
                    .disabled(connection.checking || connection.configuration == nil)
                    Text(connection.status).font(.subheadline)
                        .foregroundStyle(connection.canBroadcast ? Color.green : Color.secondary)
                }
                Section("2 · Start screen broadcast") {
                    HStack(spacing: 16) {
                        BroadcastPicker()
                            .frame(width: BroadcastPicker.side, height: BroadcastPicker.side)
                            .background(Color.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 16))
                            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color.red.opacity(0.4), lineWidth: 1))
                            .allowsHitTesting(connection.canBroadcast)
                            .opacity(connection.canBroadcast ? 1 : 0.35)
                            .accessibilityLabel("Start screen broadcast")
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Share your screen").font(.headline)
                            Text(connection.canBroadcast
                                 ? "Tap the recording icon on the left, then choose Start Broadcast in the system dialog."
                                 : "Complete Check connection above, then tap the recording icon on the left.")
                                .font(.subheadline)
                        }
                    }
                    Text("Choose the app broadcast in the system dialog. After the countdown, switch to the video player.")
                        .font(.caption).foregroundStyle(.secondary)
                    Text("Capture target: 15 fps. Actual throughput depends on playback, network conditions and receiver processing.")
                        .font(.caption).foregroundStyle(.secondary)
                    Text("Broadcasting includes visible screen content. Disable notification previews during testing. Screen sharing does not capture microphone audio or save a recording. Voice assistance requests microphone access separately.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Section("Phone voice · English") {
                    Toggle("Enable phone voice receiver", isOn: Binding(
                        get: { voice.enabled },
                        set: { enabled in
                            if enabled { voice.enable(configuration: connection.configuration) }
                            else { voice.disable() }
                        }
                    ))
                    Text(voice.status).font(.subheadline)
                        .foregroundStyle(voice.connected ? Color.green : Color.secondary)
                    Picker("English voice", selection: $voice.selectedVoiceID) {
                        Text("Automatic · best installed quality").tag("")
                        ForEach(voice.installedVoices) { item in Text(item.label).tag(item.id) }
                    }
                    HStack {
                        Text("Speech speed")
                        Slider(value: $voice.speechRate, in: 0.35...0.60, step: 0.01)
                            .accessibilityLabel("Speech speed")
                        Text(String(format: "%.2f", voice.speechRate)).monospacedDigit()
                    }
                    Button("Refresh installed voices") { voice.refreshVoices() }
                    Text("Automatic prefers installed Premium or Enhanced English voices. You can download voices in iPhone Accessibility speech settings, return here and refresh. No cloud voice service is used.")
                        .font(.caption).foregroundStyle(.secondary)
                    Button("Play local sound check") { voice.testSound() }
                    Text("Sound check identifies camera-view alerts. It is not a detection.")
                        .font(.caption).foregroundStyle(.secondary)
                    if !voice.lastSpoken.isEmpty {
                        LabeledContent("Last playback", value: voice.lastSpoken)
                            .font(.caption)
                    }
                    Picker("Alert output", selection: Binding(get: { voice.output }, set: { value in
                        voice.configure(connection.configuration)
                        Task { await voice.command("voice_output", extra: ["output": value]) }
                    })) {
                        Text("Off").tag("off")
                        Text("Phone").tag("phone")
                        Text("Computer").tag("mac")
                        Text("Both").tag("both")
                    }
                    Button("Send receiver sound check") {
                        voice.configure(connection.configuration)
                        Task { await voice.command("voice_test") }
                    }
                    Toggle("Continuous voice assistance · microphone", isOn: Binding(
                        get: { voice.assistanceActive || voice.assistanceStarting },
                        set: { value in
                            if value { Task { await voice.startAssistance(configuration: connection.configuration) } }
                            else { voice.stopAssistance() }
                        }))
                    Text(voice.microphoneStatus).font(.subheadline)
                    Text("Start here before switching to Bilibili or DJI Fly. This continuously listens for English commands on the phone, even during silence. Audio is not saved or uploaded. Stop this switch to turn the microphone off. Background operation still needs this device's test; interruptions may require returning to SkyCompanion.")
                        .font(.caption).foregroundStyle(.secondary)
                    Text("Say: ‘SkyCompanion why’, ‘SkyCompanion got it’, ‘SkyCompanion quieter’, ‘SkyCompanion normal alerts’, ‘SkyCompanion wrong alert’, ‘SkyCompanion repeat’, ‘SkyCompanion mute’, ‘SkyCompanion unmute’, ‘SkyCompanion describe’, ‘SkyCompanion stop listening’. Mute turns off alerts but keeps command listening on. During SkyCompanion speech, command recognition pauses to prevent echo commands. Use the buttons below while speech is playing.")
                        .font(.caption).foregroundStyle(.secondary)
                    Text("You can also ask ‘SkyCompanion what is ahead?’ or ‘SkyCompanion what obstacles are around me?’ These request a brief summary of visible people, objects and their directions in the current camera view only; they do not inspect behind you or start an open-ended AI conversation.")
                        .font(.caption).foregroundStyle(.secondary)
                    Text("Risk R0–R3 describes a possible camera-view conflict, separately from evidence confidence and perception health. R0 does not mean a clear path. Current camera-only inputs cannot establish physical R3 urgency, your walking direction, or metric distance.")
                        .font(.caption).foregroundStyle(.secondary)
                    voiceCommandButton("Acknowledge alert", command: "acknowledge",
                                       hint: "Reduces repeated alerts without marking an obstacle resolved.")
                    voiceCommandButton("Explain alert", command: "explain",
                                       hint: "Explains the evidence for the latest valid alert.")
                    voiceCommandButton("Quieter alerts", command: "quiet",
                                       hint: "Reduces low risk alerts. Higher risk alerts remain enabled.")
                    voiceCommandButton("Normal alerts", command: "normal",
                                       hint: "Restores normal alert frequency.")
                    voiceCommandButton("Repeat alert", command: "repeat",
                                       hint: "Repeats only a recent valid alert.")
                    voiceCommandButton("Describe camera view", command: "describe",
                                       hint: "Summarizes visible objects in the camera view.")
                    voiceCommandButton("Mute alerts", command: "mute",
                                       hint: "Stops phone alerts immediately and keeps command listening on.")
                    voiceCommandButton("Unmute alerts", command: "unmute",
                                       hint: "Enables alerts again.")
                    voiceCommandButton("Report false alert", command: "report_false_alert",
                                       hint: "Saves the latest available alert evidence for review.")
                    Text("Uses the current speaker or headphones. Headphone removal stops voice assistance. Return to SkyCompanion to restart after an interruption that cannot recover.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Section("Phone test controls") {
                    Text("For recorded first-person video only: use the full landscape screen and its center as an experimental walking area. Direction means camera left/right; this is not a measured path or a drone-to-person direction.")
                        .font(.caption).foregroundStyle(.secondary)
                    Button("Arm landscape video test · center area") {
                        voice.configure(connection.configuration)
                        Task { await voice.armTestAnalysis() }
                    }
                    Text("Arm before starting the broadcast, then switch to a landscape video within 120 seconds. Portrait pauses analysis. Confirm the selected video view again after reconnecting; do not use this test setting for walking.")
                        .font(.caption).foregroundStyle(.secondary)
                    Button("Pause analysis") {
                        voice.configure(connection.configuration)
                        Task { await voice.command("pause") }
                    }
                    Text(voice.controlStatus).font(.subheadline)

                }
                Section("3 · Play and inspect analysis") {
                    Text("Enable continuous voice assistance, then select Arm landscape video test · center area to confirm the test region. Start broadcasting and play a video in landscape in Bilibili or VLC. Keep the phone unlocked; no desktop start action is required.")
                    Text("Turn off continuous voice assistance, then stop broadcasting using the iPhone recording indicator or Control Center. Control results appear above; the desktop page is an optional diagnostic monitor.")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("SkyCompanionCapture")
            .onAppear { voice.configure(connection.configuration) }
            .onChange(of: scenePhase) { _, phase in
                voice.setForeground(phase == .active)
            }
        }
    }

    private func voiceCommandButton(_ title: String, command: String, hint: String) -> some View {
        Button(title) {
            voice.configure(connection.configuration)
            Task { await voice.command(command) }
        }
        .frame(minHeight: 44)
        .accessibilityLabel(title)
        .accessibilityHint(hint)
    }
}

private struct BroadcastPicker: UIViewRepresentable {
    static let side: CGFloat = 72

    func makeUIView(context: Context) -> RPSystemBroadcastPickerView {
        // ReplayKit lays out its system button when the picker is created. A
        // zero initial frame can leave that button invisible after SwiftUI sizes
        // the wrapper. Give UIKit the same nonzero size used by SwiftUI.
        let picker = RPSystemBroadcastPickerView(
            frame: CGRect(x: 0, y: 0, width: Self.side, height: Self.side)
        )
        picker.tintColor = .systemRed
        let configuredID = Bundle.main.object(forInfoDictionaryKey: "SkyCompanionBroadcastExtensionIdentifier") as? String
        picker.preferredExtension = configuredID
        picker.showsMicrophoneButton = false
        return picker
    }

    func updateUIView(_ uiView: RPSystemBroadcastPickerView, context: Context) {}

    func sizeThatFits(_ proposal: ProposedViewSize, uiView: RPSystemBroadcastPickerView,
                      context: Context) -> CGSize? {
        CGSize(width: Self.side, height: Self.side)
    }
}
