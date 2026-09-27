import SwiftUI

struct NavigationScreen: View {
    @ObservedObject var model: LocalSessionModel
    @ObservedObject var navigation: NavigationController
    @State private var destination = ""
    var body: some View {
        Form {
            Section("Walking destination") {
                TextField("Place or street address", text: $destination)
                    .textContentType(.fullStreetAddress).submitLabel(.go)
                    .onSubmit { model.startNavigation(to: destination) }
                    .accessibilityLabel("Walking destination")
                Button("Start walking navigation") { model.startNavigation(to: destination) }
                    .disabled(destination.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .frame(minHeight: 48)
                Button(model.voice.listening ? "Listening for your destination" : "Enable voice destination") {
                    Task { _ = await model.voice.startListening() }
                }.disabled(model.voice.listening || model.voice.starting).frame(minHeight: 48)
                Text("Say “SkyCompanion, navigate to” followed by a place or address.")
                    .font(.footnote).foregroundStyle(.secondary)
                Text(model.voice.status).font(.footnote).foregroundStyle(.secondary)
            }
            Section("Navigation") {
                if !navigation.destination.isEmpty { LabeledContent("Destination", value: navigation.destination) }
                if !navigation.guidanceNotice.isEmpty {
                    Text(navigation.guidanceNotice).font(.footnote).foregroundStyle(.secondary)
                }
                if !navigation.currentInstruction.isEmpty { Text(navigation.currentInstruction) }
                Text(navigation.status).accessibilityLabel("Navigation status: " + navigation.status)
                ForEach(Array(navigation.candidates.enumerated()), id: \.element.id) { index, candidate in
                    Button { navigation.selectCandidate(id: candidate.id) } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("\(index + 1). \(candidate.name)")
                            Text(candidate.detail).font(.footnote).foregroundStyle(.secondary)
                        }.frame(minHeight: 48)
                    }
                }
                if !navigation.candidates.isEmpty {
                    Text("Say “SkyCompanion, choose one”, “choose two”, or “choose three”.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                if navigation.isActive || !navigation.candidates.isEmpty {
                    Button("Stop navigation", role: .destructive) { model.cancelNavigation() }.frame(minHeight: 48)
                }
            }
            Section("Quiet guidance") {
                Text("Short turn cues only. Obstacle warnings interrupt navigation. Apple Maps supplies walking routes without opening the Maps app.")
                Text("Location permission is needed. Route lookup needs internet. Crossing directions describe the route; they do not confirm that traffic is safe.")
                    .font(.footnote).foregroundStyle(.secondary)
                Text("Say “SkyCompanion, stop navigation” to end the route.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Navigation").navigationBarTitleDisplayMode(.inline)
    }
}
