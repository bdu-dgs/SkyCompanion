import SwiftUI
import CaptureCore

struct CompanionScreen: View {
    @ObservedObject var model: LocalSessionModel
    @ObservedObject var companion: PhotonCompanion
    @State private var question = ""
    @State private var correction = ""
    @State private var confirmDelete = false

    var body: some View {
        Form {
            Section {
                Text(companion.agentName).font(.headline).accessibilityAddTraits(.isHeader)
                Text("Ask about recorded reminders, review a trip, or correct an alert. Obstacle reminders always take priority over the assistant's speech.")
                Text(companion.status).font(.footnote).foregroundStyle(.secondary)
                if companion.pendingCount > 0 { Text("\(companion.pendingCount) records waiting to sync") }
            }
            Section("Personal alert preferences") {
                LabeledContent("Detail", value: companion.preferences.verbosity.capitalized)
                LabeledContent("Ordinary alert interval", value: "\(companion.preferences.repeatIntervalSeconds) seconds")
                LabeledContent("Quiet categories", value: companion.preferences.mutedCategories.isEmpty ? "None" : companion.preferences.mutedCategories.joined(separator: ", "))
                Text(companion.preferencesStatus).font(.footnote).foregroundStyle(.secondary)
                Text("Message the assistant in iMessage: “Say less”, “Don't mention trees”, or “Show my preferences”. Changes sync here and work offline after they are applied.")
                    .font(.footnote)
                Text("Confirmed high-risk and urgent warnings remain enabled. Preferences never retrain the detector.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            if !model.tripSummary.isEmpty {
                Section("Latest trip summary") {
                    Text(model.tripSummary).accessibilityLabel("Trip summary: " + model.tripSummary)
                    Button("Read summary aloud") { model.readCompanionMessage(id: "summary", text: model.tripSummary) }
                }
            }
            Section("Ask the assistant") {
                TextField("Question about this trip", text: $question, axis: .vertical)
                    .lineLimit(1...4).accessibilityLabel("Question for SkyCompanion Assistant")
                Button("Send question") {
                    model.askCompanion(question); question = ""
                }.disabled(!companion.enabled || !model.hasCompanionTrip || question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Button("Why was I warned?") { model.askCompanion("Why did you warn me?") }
                    .disabled(!companion.enabled || !model.hasCompanionTrip)
                Button("Summarize this trip") { model.askCompanion("Trip summary?") }
                    .disabled(!companion.enabled || !model.hasCompanionTrip)
            }
            Section("Correct the last spoken alert") {
                if !model.lastReportedAlert.isEmpty { Text(model.lastReportedAlert) }
                TextField("What was incorrect?", text: $correction, axis: .vertical)
                    .lineLimit(2...4).accessibilityLabel("Correction for the last spoken obstacle alert")
                Button("Save incorrect-alert feedback") {
                    model.reportFalseAlert(note: correction.isEmpty ? "User reported an incorrect alert" : correction)
                    correction = ""
                }.disabled(!model.canReportAlert)
                Text("Feedback is linked to the original reminder. Corrections wait for review before they can become training examples; reporting does not immediately change the model.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            Section("Messages") {
                if companion.messages.isEmpty { Text("No synchronized messages yet.").foregroundStyle(.secondary) }
                ForEach(companion.messages.reversed()) { item in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(Date(timeIntervalSince1970: Double(item.createdAtMS) / 1_000), style: .time)
                            .font(.caption).foregroundStyle(.secondary)
                        Text(item.text).textSelection(.enabled)
                            .accessibilityLabel(companion.agentName + ": " + item.text)
                        Button("Read message aloud") { model.readCompanionMessage(id: item.id, text: item.text) }
                            .accessibilityHint("Waits for obstacle reminders and can be interrupted by a new obstacle.")
                    }.padding(.vertical, 4)
                }
            }
            Section("Speech and accessibility") {
                Toggle("Read new assistant replies aloud", isOn: $model.readCompanionMessages)
                Text("Messages and controls are readable with VoiceOver. Automatic assistant speech uses SkyCompanion's interruptible voice queue. In Apple's Messages app, VoiceOver and notification speech follow your iPhone settings.")
                    .font(.footnote).foregroundStyle(.secondary)
                Text("Old or interrupted replies remain here to read later. Automatic speech respects mute.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            Section("Photon connection") {
                TextField("HTTPS service address", text: $companion.endpoint)
                    .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                    .accessibilityLabel("Photon companion service HTTPS address")
                SecureField("Upload token", text: $companion.token)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                    .accessibilityLabel("Device upload token")
                Button("Save connection") { companion.saveConfiguration() }.disabled(model.phase != .idle)
                Toggle("Sync trips with Photon", isOn: $companion.enabled).disabled(model.phase != .idle)
                Text("Save the connection and enable sync before starting a trip. Only reminder records and your feedback are uploaded; photos, video, and microphone audio stay on this iPhone. The upload token is stored in Keychain.")
                    .font(.footnote).foregroundStyle(.secondary)
                Button("Sync now") { companion.syncNow() }.disabled(!companion.enabled)
                Button("Delete local Photon data and token", role: .destructive) { confirmDelete = true }
                    .disabled(model.phase != .idle)
            }
        }
        .navigationTitle("Assistant").navigationBarTitleDisplayMode(.inline)
        .confirmationDialog("Delete unsent records, local messages, and this phone's upload token? Remote records will remain.", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete local Photon data", role: .destructive) { companion.deleteLocalData() }
            Button("Cancel", role: .cancel) {}
        }
    }
}
