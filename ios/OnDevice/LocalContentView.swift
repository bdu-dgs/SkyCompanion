import SwiftUI
import AVKit
import ReplayKit
import UniformTypeIdentifiers
import CaptureCore

/// Native, offline controls. Dynamic system typography and semantic surfaces remain authoritative.
struct LocalContentView: View {
    var openingVisible = false
    @StateObject private var model = LocalSessionModel()
    @AppStorage("skycompanion.onboarding.completed") private var onboardingCompleted = false
    @State private var showOnboarding = false
    #if DEBUG && targetEnvironment(simulator)
    @State private var showSetupPreview = ["drone", "settings", "video", "assistant"].contains(ProcessInfo.processInfo.environment["SKYCOMPANION_PREVIEW_ROUTE"] ?? "")
    #endif
    @Environment(\.scenePhase) private var scenePhase
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    HStack(alignment: .center, spacing: 12) {
                        Text("SkyCompanion").font(.title2.weight(.bold))
                            .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
                            .accessibilityAddTraits(.isHeader)
                        Spacer(minLength: 0)
                        NavigationLink { LocalSettingsScreen(model: model) } label: {
                            Image(systemName: "gearshape").font(.title3)
                                .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
                                .frame(width: 48, height: 48)
                                .background(SkyCompanionTheme.surface, in: Circle())
                        }.accessibilityLabel("Settings")
                    }
                    if model.phase != .idle { sessionCard }
                    NavigationLink { DroneSetupScreen(model: model) } label: {
                        SkyDroneCard()
                    }.buttonStyle(.plain)
                    NavigationLink { LocalVideoScreen(model: model) } label: {
                        SkyActionRow("Test a video", subtitle: "Choose a recording on this iPhone", symbol: "play.rectangle")
                            .modifier(SkyCard())
                    }.buttonStyle(.plain)
                    NavigationLink { NavigationScreen(model: model, navigation: model.navigation) } label: {
                        SkyActionRow("Walking navigation", subtitle: LocalizedStringKey(model.navigation.isActive ? model.navigation.status : "Say a destination · quiet turn cues"), symbol: "location")
                            .modifier(SkyCard())
                    }.buttonStyle(.plain)
                    if model.phase == .idle { sessionCard }
                    NavigationLink { CompanionScreen(model: model, companion: model.photon) } label: {
                        SkyActionRow("Assistant and trip history", subtitle: "Messages, summaries, and feedback", symbol: "bubble.left.and.bubble.right")
                            .modifier(SkyCard())
                    }.buttonStyle(.plain)
                    Button { showOnboarding = true } label: {
                        SkyActionRow("Setup and sound check", symbol: "ear.badge.waveform")
                            .modifier(SkyCard())
                    }.buttonStyle(.plain)
                    Text("Camera directions by default. Distance is not yet verified.")
                        .font(.footnote).foregroundStyle(.secondary).padding(.horizontal, 4)
                }
                .frame(maxWidth: 620)
                .padding(.horizontal, 20).padding(.bottom, 24)
                .frame(maxWidth: .infinity)
            }
            .background(SkyCompanionTheme.background)
            #if DEBUG && targetEnvironment(simulator)
            .navigationDestination(isPresented: $showSetupPreview) {
                switch ProcessInfo.processInfo.environment["SKYCOMPANION_PREVIEW_ROUTE"] {
                case "settings": LocalSettingsScreen(model: model)
                case "video": LocalVideoScreen(model: model)
                case "assistant": CompanionScreen(model: model, companion: model.photon)
                default: DroneSetupScreen(model: model)
                }
            }
            #endif
            .navigationTitle("")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(SkyCompanionTheme.background, for: .navigationBar)
            .sheet(isPresented: $showOnboarding) {
                NavigationStack {
                    OnboardingScreen(model: model) {
                        onboardingCompleted = true; showOnboarding = false
                    }
                }.tint(SkyCompanionTheme.accent)
            }
            .task(id: openingVisible) { if !openingVisible && !onboardingCompleted { showOnboarding = true } }
            .onChange(of: scenePhase) { _, value in
                // System permission/broadcast sheets make the app inactive; they are not a source switch.
                if value == .active { model.setForeground(true) }
                else if value == .background { model.setForeground(false) }
            }
        }
        .tint(SkyCompanionTheme.accent)
        .environment(\.defaultMinListRowHeight, 44)
    }
    private var sessionCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("CURRENT SESSION").font(.caption.weight(.semibold))
                .tracking(1.4).foregroundStyle(SkyCompanionTheme.accent)
                .accessibilityAddTraits(.isHeader)
            SessionStatusCard(model: model)
            if model.phase != .idle {
                Divider()
                if model.phase == .running {
                    Button { model.handle(.describe) } label: {
                        Label("Describe surroundings", systemImage: "text.bubble").frame(minHeight: 56)
                    }
                    Button { model.pause() } label: {
                        Label("Pause analysis", systemImage: "pause.circle").frame(minHeight: 56)
                    }
                }
                NavigationLink { SessionScreen(model: model) } label: {
                    SkyActionRow("Session controls", symbol: "slider.horizontal.3")
                }.buttonStyle(.plain)
            }
        }.modifier(SkyCard())
    }

}

private struct SessionStatusCard: View {
    @ObservedObject var model: LocalSessionModel
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(LocalizedStringKey(model.phase.rawValue), systemImage: statusSymbol).font(.headline)
            Text(model.phase == .idle ? String(localized: "Choose Connect drone or Test a video.") : model.message)
                .font(.subheadline).foregroundStyle(.secondary)
            if model.phase != .idle {
                Label(model.voice.listening ? "Voice commands on" : "Voice commands off",
                      systemImage: model.voice.listening ? "mic.fill" : "mic.slash").font(.subheadline)
                if model.wearerConfigured {
                    Label(model.wearerObservation?.state == .tracked ? "User tracked · excluded from alerts" :
                          model.wearerObservation?.state == .lost ? "User lost · select again" : "User selected · awaiting analysis",
                          systemImage: model.wearerObservation?.state == .lost ? "person.crop.rectangle.badge.exclamationmark" : "person.crop.rectangle")
                        .font(.subheadline)
                }
            }
            if model.analysisAttempted {
                DisclosureGroup("Analysis details") {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(model.phase == .running ? "Analyzing fresh frames." : "Analysis is not running now.")
                        Text(String.localizedStringWithFormat(String(localized: "Analyzed frames this attempt: %lld"), model.analyzedFrameCount))
                        if let last = model.lastAnalysisDate {
                            Text(String.localizedStringWithFormat(String(localized: "Last successful analysis: %@"), last.formatted(date: .omitted, time: .standard)))
                        } else { Text("Waiting for the first analyzed frame.") }
                    }.font(.footnote).foregroundStyle(.secondary).padding(.top, 6)
                }
            }
        }.padding(.vertical, 4)
        // No live region: frame updates must never steal VoiceOver focus.
    }
    private var statusSymbol: String {
        switch model.phase {
        case .running: return "waveform.path"
        case .preparing, .starting: return "hourglass"
        case .armed: return "arrow.up.forward.app"
        case .paused: return "pause.circle"
        case .unavailable: return "exclamationmark.triangle"
        case .preview: return "viewfinder"
        case .idle: return "circle"
        }
    }
}

private struct OnboardingScreen: View {
    @ObservedObject var model: LocalSessionModel
    let finish: () -> Void
    @Environment(\.openURL) private var openURL
    var body: some View {
        Form {
            Section {
                Text("Welcome to SkyCompanion").font(.largeTitle.weight(.bold))
                Text("Visual observations and voice controls run on this iPhone. Optional Photon sync shares reminder records and feedback for messaging; obstacle assistance does not wait for the network.")
            }
            Section("1 · Check the model") {
                Label(model.modelDescription, systemImage: model.modelAvailable ? "shippingbox" : "exclamationmark.triangle")
                Text("A bundled model is required before any scene can be analyzed.").font(.footnote).foregroundStyle(.secondary)
            }
            Section("2 · Voice and microphone") {
                Text("Voice commands need microphone and speech permissions. The selected language must be available on this iPhone.")
                Button { Task { _ = await model.voice.startListening() } } label: {
                    Label(LocalizedStringKey(model.voice.listening ? "Microphone is listening" : "Check voice permissions"), systemImage: "mic")
                        .frame(minHeight: 56)
                }.disabled(model.voice.starting || model.voice.listening)
                Text(model.voice.status).font(.subheadline).foregroundStyle(.secondary)
                Button("Open iPhone Settings") {
                    if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
                }.frame(minHeight: 44)
            }
            Section("3 · Hear the output") {
                Text("Connect your headphones if you plan to use them. Play the sample, then confirm that you heard it through the intended output.")
                Button { model.voice.soundCheck() } label: {
                    Label("Play sound check", systemImage: "speaker.wave.2").frame(minHeight: 56)
                }
                Button { model.voice.confirmSoundHeard() } label: {
                    Label(LocalizedStringKey(model.voice.soundChecked ? "Sound confirmed by you" : "I heard the sound"), systemImage: model.voice.soundChecked ? "checkmark.circle" : "ear")
                        .frame(minHeight: 44)
                }
                Text("This confirmation records what you heard. It is not an automated latency or headphone test.").font(.footnote).foregroundStyle(.secondary)
            }
            Section("How assistance works") {
                instruction("Start in SkyCompanion", text: "Prepare the drone source and start the system screen broadcast.")
                instruction("Choose the camera area", text: "Set the area directly, or adjust it on the last shared DJI Fly preview. You can change it while recording.")
                instruction("Listen and stay in control", text: "Arm analysis, return to DJI Fly and keep the phone unlocked. Returning to SkyCompanion pauses external analysis.")
                Text("Try saying “SkyCompanion describe”, “SkyCompanion repeat”, “SkyCompanion mute” or “SkyCompanion stop listening”. Stopping listening ends assistance.")
            }
            Section {
                Button(action: finish) {
                    Text("Continue to SkyCompanion").font(.headline).frame(maxWidth: .infinity, minHeight: 56)
                }.buttonStyle(.borderedProminent)
                Text("You can return to setup at any time. Camera-relative observations do not establish that a walking route is clear.").font(.footnote).foregroundStyle(.secondary)
            }
        }
        .scrollContentBackground(.hidden).background(SkyCompanionTheme.background)
        .navigationTitle("Setup").navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done", action: finish).frame(minHeight: 44) } }
    }
    private func instruction(_ title: String, text: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(LocalizedStringKey(title)).font(.headline); Text(LocalizedStringKey(text)).foregroundStyle(.secondary)
        }.padding(.vertical, 4)
    }
}

private struct DroneSetupScreen: View {
    @ObservedObject var model: LocalSessionModel
    @State private var expandedStep = 1
    var body: some View {
        Form {
            if model.phase != .idle { Section { SessionStatusCard(model: model) } }
            Section {
                step(1, "Enable voice", complete: model.source == .drone && model.voice.listening && model.phase != .idle) {
                    Text("Connect Neo 2 in DJI Fly first.").foregroundStyle(.secondary)
                    Button { Task {
                        await model.prepareDrone()
                        if model.phase == .preview { expandedStep = 2 }
                    } } label: {
                        Label("Enable voice assistance", systemImage: "mic").font(.headline).frame(minHeight: 56)
                    }.disabled(!model.modelAvailable || model.phase == .preparing || model.savingRecording)
                    Text("Allows voice commands while DJI Fly is open.").font(.footnote).foregroundStyle(.secondary)
                }
            }
            Section {
                step(2, "Share DJI Fly", complete: model.connected) {
                    HStack(spacing: 16) {
                        LocalBroadcastPicker().frame(width:64,height:64)
                            .accessibilityLabel("Start or stop SkyCompanion screen broadcast")
                            .accessibilityHint("Choose SkyCompanion in the system broadcast control.")
                        Text("Tap to broadcast. Choose SkyCompanion.")
                    }
                    Text("Choose an area below now. A DJI Fly preview becomes available after it has been shared.").font(.subheadline).foregroundStyle(.secondary)
                    Label(model.connected ? "Broadcast connected" : "Waiting for broadcast",systemImage:model.connected ? "checkmark.circle" : "clock")
                    Text("Recording includes your voice and SkyCompanion responses while voice assistance is on. Stop recording saves the video to Photos.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Text(model.recordingStatus).font(.footnote)
                    if model.connected || model.savingRecording {
                        Button("Stop recording and save", role: .destructive) {
                            Task { await model.stopRecordingAndEnd() }
                        }.frame(minHeight: 44).disabled(model.savingRecording)
                    }
                }
            }
            Section {
                step(3, "Choose video area", complete:model.regionConfirmed) {
                    Label(model.videoAreaStatus, systemImage: model.regionConfirmed ? "checkmark.circle" : "pencil.circle")
                        .font(.subheadline)
                    Text(model.region.summary).font(.caption).foregroundStyle(.secondary)
                        .accessibilityIdentifier("videoArea.summary")
                    EditableVideoArea(image: model.source == .drone ? model.preview : nil,
                                      region: Binding(get: { model.region }, set: { model.region = $0; model.regionConfirmed = false }))
                    Text("Drag the box to move it. Drag its corner to resize. You can change this while recording.")
                        .font(.subheadline).foregroundStyle(.secondary)
                    DisclosureGroup("Precise adjustment") {
                        CropSlider(title:"Left edge",value:regionBinding(\.x),range:0...max(0,1-model.region.width))
                        CropSlider(title:"Top edge",value:regionBinding(\.y),range:0...max(0,1-model.region.height))
                        CropSlider(title:"Width",value:regionBinding(\.width),range:0.06...max(0.06,1-model.region.x))
                        CropSlider(title:"Height",value:regionBinding(\.height),range:0.06...max(0.06,1-model.region.y))
                    }
                    // These actions share one Form row. Automatic button style makes
                    // a row tap invoke both actions, resetting the crop before Apply.
                    Button("Use full image") { model.resetVideoAreaDraft() }
                        .buttonStyle(.borderless).frame(minHeight:44)
                        .accessibilityIdentifier("videoArea.reset")
                    Button("Apply video area") { model.confirmRegion(); if model.regionConfirmed { expandedStep=4 } }
                        .buttonStyle(.borderless).font(.headline).frame(minHeight:56)
                        .accessibilityIdentifier("videoArea.apply")
                        .disabled(!model.region.valid || model.source != .drone || model.savingRecording)
                    Text("Applies to analysis and the saved recording from this point onward. Recording does not restart.")
                        .font(.footnote).foregroundStyle(.secondary)
                    if model.source != .drone { Text("Enable drone assistance before applying this area.").font(.footnote) }
                }
            }
            Section {
                step(4, "Start analysis", complete:model.phase == .running) {
                    Button { model.armDrone() } label: {
                        Label("Ready — open DJI Fly next",systemImage:"play.circle.fill").font(.headline).frame(minHeight:56)
                    }.disabled(!model.connected || !model.regionConfirmed || !model.voice.listening || !model.region.valid || model.phase == .armed)
                    Text(model.phase == .armed ? "Open DJI Fly now. Analysis has not started yet." : "Tap when ready, then open DJI Fly. You will hear confirmation when analysis starts.")
                        .font(.subheadline).foregroundStyle(.secondary)
                    Text("Returning here pauses analysis.").font(.footnote).foregroundStyle(.secondary)
                    NavigationLink("Select followed user") { PathSetupScreen(model:model) }.frame(minHeight:44)
                    Text("After analysis starts, select yourself in the saved view. Direction alerts wait until your identity is confirmed. Select again after changing the area.").font(.footnote).foregroundStyle(.secondary)
                }
            }
            if model.phase != .idle {
                Section { NavigationLink("Session controls") { SessionScreen(model:model) }.frame(minHeight:44) }
            }
        }
        .scrollContentBackground(.hidden).background(SkyCompanionTheme.background)
        .navigationTitle("Connect drone").navigationBarTitleDisplayMode(.inline)
        .onAppear {
            model.restoreAppliedVideoArea()
            expandedStep = model.regionConfirmed ? 4 : model.preview != nil ? 3 : model.source == .drone && model.phase != .idle ? 2 : 1
        }

    }
    private func step<Content:View>(_ number:Int,_ title:LocalizedStringKey,complete:Bool,@ViewBuilder content:@escaping ()->Content) -> some View {
        DisclosureGroup(isExpanded:Binding(get:{expandedStep == number},set:{
            if $0 && number == 3 { model.restoreAppliedVideoArea() }
            expandedStep = $0 ? number : 0
        })) {
            VStack(alignment:.leading,spacing:12) { content() }.padding(.vertical,8)
        } label: {
            HStack(spacing:12) {
                Image(systemName:complete ? "checkmark.circle.fill" : "\(number).circle").foregroundStyle(SkyCompanionTheme.accent)
                Text(title).font(.headline)
                if complete { Text("Done").font(.caption).foregroundStyle(.secondary) }
            }.frame(minHeight:44)
        }
    }
    private func regionBinding(_ path:WritableKeyPath<CaptureRegion,Double>)->Binding<Double> {
        Binding(get:{model.region[keyPath:path]},set:{model.region[keyPath:path]=$0;model.regionConfirmed=false})
    }
}

/// Edits a normalized screen rectangle before or during a broadcast. A missing
/// external preview is a coordinate guide, never represented as live DJI video.
private struct EditableVideoArea: View {
    let image: UIImage?
    @Binding var region: CaptureRegion
    @AppStorage("skycompanion.drone.areaLandscape") private var landscape = false
    @State private var moveStart: CaptureRegion?
    @State private var resizeStart: CaptureRegion?
    private var ratio: CGFloat {
        if let image { return image.size.width / max(1,image.size.height) }
        let screen = UIScreen.main.bounds.size
        let portrait = min(screen.width,screen.height)/max(screen.width,screen.height)
        return landscape ? 1/portrait : portrait
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if image == nil {
                Picker("Screen orientation", selection: $landscape) {
                    Text("Portrait").tag(false); Text("Landscape").tag(true)
                }.pickerStyle(.segmented)
                Text("Screen guide — no DJI Fly preview yet.").font(.caption).foregroundStyle(.secondary)
            } else {
                Text("Last shared view — not live while editing.").font(.caption).foregroundStyle(.secondary)
            }
            GeometryReader { proxy in
                let size = proxy.size
                ZStack(alignment: .topLeading) {
                    if let image { Image(uiImage: image).resizable().frame(width:size.width,height:size.height) }
                    else {
                        RoundedRectangle(cornerRadius: 12).fill(Color.secondary.opacity(0.15))
                        Text("Video area").font(.caption).foregroundStyle(.secondary)
                            .frame(width:size.width,height:size.height)
                    }
                    Rectangle().fill(Color.black.opacity(0.18))
                        .overlay(Rectangle().stroke(Color.white, lineWidth: 3))
                        .overlay(Image(systemName:"arrow.up.and.down.and.arrow.left.and.right").foregroundStyle(.white))
                        .frame(width:size.width*region.width,height:size.height*region.height)
                        .offset(x:size.width*region.x,y:size.height*region.y)
                        .gesture(DragGesture().onChanged { value in
                            let start = moveStart ?? region; moveStart = start
                            region.x = min(1-start.width,max(0,start.x+value.translation.width/size.width))
                            region.y = min(1-start.height,max(0,start.y+value.translation.height/size.height))
                        }.onEnded { _ in moveStart = nil })
                    Image(systemName:"arrow.up.left.and.arrow.down.right")
                        .font(.headline).foregroundStyle(.black)
                        .frame(width:44,height:44).background(.white,in:Circle())
                        .position(x: min(size.width-22,max(22,size.width*(region.x+region.width))),
                                  y: min(size.height-22,max(22,size.height*(region.y+region.height))))
                        .gesture(DragGesture().onChanged { value in
                            let start = resizeStart ?? region; resizeStart = start
                            region.width = min(1-start.x,max(0.06,start.width+value.translation.width/size.width))
                            region.height = min(1-start.y,max(0.06,start.height+value.translation.height/size.height))
                        }.onEnded { _ in resizeStart = nil })
                }.clipped().accessibilityElement(children: .ignore)
                    .accessibilityLabel("Selected video area")
                    .accessibilityHint("Use Precise adjustment below to change the edges and size.")
            }.aspectRatio(ratio,contentMode:.fit).frame(maxHeight:360)
        }
    }
}

private struct CropSlider: View {
    let title: String
    @Binding var value: Double
    let range: ClosedRange<Double>
    // SwiftUI's stepped slider traps for a zero-length range or a range
    // shorter than its step. The real crop bounds can legitimately be either.
    private var span: Double { range.upperBound-range.lowerBound }
    private var normalizedValue: Binding<Double> {
        Binding(get: {
            guard span.isFinite, span > 0, value.isFinite else { return 0 }
            return min(1,max(0,(value-range.lowerBound)/span))
        }, set: { position in
            guard span.isFinite, span > 0, position.isFinite else { return }
            value = min(range.upperBound,max(range.lowerBound,range.lowerBound+position*span))
        })
    }
    var body: some View {
        VStack(alignment: .leading) {
            HStack { Text(LocalizedStringKey(title)); Spacer(); Text(value, format: .percent.precision(.fractionLength(0))) }.font(.subheadline)
            Slider(value: normalizedValue, in: 0...1)
                .disabled(!span.isFinite || span <= 0)
                .accessibilityLabel(LocalizedStringKey(title)).accessibilityValue(Text(value, format: .percent.precision(.fractionLength(0))))
                .frame(minHeight: 44)
        }
    }
}

private struct CalibrationPreview: View {
    let image: UIImage
    let region: CaptureRegion
    var body: some View {
        Image(uiImage: image).resizable().scaledToFit()
            .overlay {
                GeometryReader { proxy in
                    Rectangle().stroke(SkyCompanionTheme.accent, style: StrokeStyle(lineWidth: 3, dash: [6, 4]))
                        .frame(width: proxy.size.width * region.width, height: proxy.size.height * region.height)
                        .offset(x: proxy.size.width * region.x, y: proxy.size.height * region.y)
                }.clipped()
            }
            .clipShape(RoundedRectangle(cornerRadius: 16))
            .accessibilityLabel("Saved DJI calibration image with selected camera crop")
            .accessibilityHint("Use the edge and size sliders to adjust the selected rectangle.")
    }
}

private struct SessionScreen: View {
    @ObservedObject var model: LocalSessionModel
    var body: some View {
        List {
            Section("Assistance") {
                SessionStatusCard(model: model)
                LabeledContent("Source") { Text(LocalizedStringKey(model.source.rawValue)) }
                if model.broadcastPrepared { Text(model.recordingStatus).font(.footnote) }
                LabeledContent("Alerts") { Text(model.voice.muted ? LocalizedStringKey("Muted") : LocalizedStringKey("Enabled")) }
                LabeledContent("Microphone") { Text(model.voice.listening ? LocalizedStringKey("Listening") : LocalizedStringKey("Off")) }
            }
            Section("Current observation") {
                if let assessment = model.assessment {
                    Label(String.localizedStringWithFormat(String(localized: "R%lld · %@"), assessment.level.rawValue, riskTitle(assessment.level)), systemImage: "exclamationmark.bubble")
                    Text(assessment.text)
                    if assessment.lifecycle == .occludedUnresolved {
                        Text("The earlier object is no longer visible. Its absence does not prove that the conflict has ended.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                } else { Text("No current observation.").foregroundStyle(.secondary) }
                Button("Describe camera view") { model.handle(.describe) }.frame(minHeight: 44).disabled(model.phase != .running)
                Button("Repeat current alert") { model.handle(.repeatAlert) }.frame(minHeight: 44).disabled(model.assessment == nil)
                Button("Why did SkyCompanion alert?") { model.handle(.explain) }.frame(minHeight: 44).disabled(model.assessment == nil)
                Button("Report an incorrect alert") { model.reportFalseAlert() }.frame(minHeight: 44).disabled(!model.canReportAlert && model.frame == nil)
            }
            Section("Controls") {
                Button(LocalizedStringKey(model.voice.muted ? "Enable alerts" : "Mute alerts")) { model.voice.setMuted(!model.voice.muted) }.frame(minHeight: 56)
                DisclosureGroup("What these controls do") {
                    Text("Mute: silence spoken alerts. Pause: stop analysis. End: stop analysis and microphone.")
                    Text("Rear-following instructions need a selected user and confirmed path. Other views use camera directions.")
                }.font(.subheadline)
                Button("Pause analysis") { model.pause() }.frame(minHeight: 44).disabled(model.phase == .idle || model.phase == .paused)
                if model.source == .video {
                    Button("Resume video analysis") { model.playVideo() }.frame(minHeight: 44).disabled(model.player == nil || model.phase == .running)
                } else {
                    Button("Resume and switch to DJI Fly") { model.armDrone() }.frame(minHeight: 44)
                        .disabled(!model.connected || !model.regionConfirmed || !model.voice.listening)
                }
                Button(model.broadcastPrepared ? "Stop recording and end assistance" : "Stop listening and end assistance", role: .destructive) {
                    Task { await model.stopRecordingAndEnd() }
                }.frame(minHeight: 44).disabled(model.savingRecording)
            }
            Section {
                NavigationLink("Walking navigation") { NavigationScreen(model: model, navigation: model.navigation) }.frame(minHeight: 44)
                NavigationLink("Assistant and trip history") { CompanionScreen(model: model, companion: model.photon) }.frame(minHeight: 44)
                NavigationLink("Select followed user") { PathSetupScreen(model: model) }.frame(minHeight: 44)
                NavigationLink("Depth and path testing") { ExperimentalToolsScreen(model: model) }.frame(minHeight: 44)
                NavigationLink("Diagnostics") { DiagnosticsScreen(model: model) }.frame(minHeight: 44)
            } footer: { Text("Camera-relative observations do not establish user-relative direction, distance or a safe route.") }
        }.scrollContentBackground(.hidden).background(SkyCompanionTheme.background)
        .navigationTitle("Session").navigationBarTitleDisplayMode(.inline)
    }
    private func riskTitle(_ level: MobileRiskLevel) -> String {
        switch level {
        case .none: return String(localized: "No confirmed image conflict")
        case .attention: return String(localized: "Attention")
        case .action: return String(localized: "Confirmed image-region conflict")
        case .urgent: return String(localized: "Urgent · validated evidence required")
        }
    }
}

private struct LocalVideoScreen: View {
    @ObservedObject var model: LocalSessionModel
    @State private var showImporter = false
    @State private var importError: String?
    var body: some View {
        List {
            Section {
                Text("Test without a drone").font(.title2.weight(.semibold))
                Text("Choose a video from Files to test analysis and voice interaction. Recording includes the video’s original sound.")
                Button { showImporter = true } label: {
                    Label("Choose a video", systemImage: "folder").frame(minHeight: 56)
                }.disabled(model.phase == .preparing || model.savingRecording)
                if let importError { Text(importError).foregroundStyle(.red) }
            }
            if model.source == .video, let player = model.player {
                Section("Playback") {
                    VideoPlayer(player: player)
                        .frame(height: 240)
                        .clipShape(RoundedRectangle(cornerRadius: 16))
                        .accessibilityLabel("Local test video player")
                    Button { model.playVideo() } label: {
                        Label(LocalizedStringKey(model.phase == .paused ? "Play or resume analysis" : "Start analysis"), systemImage: "play.circle")
                            .frame(minHeight: 56)
                    }.disabled(!model.modelAvailable || model.phase == .running || model.phase == .armed || model.phase == .starting)
                    Button("Pause video and analysis") { model.pause() }.frame(minHeight: 44)
                        .disabled(model.phase != .running && model.phase != .armed && model.phase != .starting)
                    NavigationLink("Select followed user") { PathSetupScreen(model: model) }.frame(minHeight: 44)
                    Text(model.wearerConfigured
                        ? "Followed user selected. Uncertain tracking pauses direction alerts."
                        : "Following someone from behind? Start analysis, then select that person to exclude them from obstacle alerts.")
                        .font(.footnote).foregroundStyle(.secondary)
                    if let seconds = model.stabilityTestSeconds {
                        Text(String.localizedStringWithFormat(String(localized: "Stability test: %lld / 1800 seconds"), seconds))
                            .font(.subheadline).monospacedDigit()
                    } else {
                        Button("Run a 30-minute loop test") { model.startStabilityTest() }.frame(minHeight: 44)
                    }
                    Text("The loop test keeps this screen awake and repeats the video. Pause stops the test. It records performance numbers, not video.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Text("Use SkyCompanion’s play and pause controls to keep playback and analysis together. Seeking clears observations and user selection; select the followed user again.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("Record this test") {
                    if !model.broadcastPrepared {
                        Button { Task { await model.prepareVideoRecording() } } label: {
                            Label("Enable test recording", systemImage: "record.circle").frame(minHeight: 44)
                        }.disabled(model.voice.starting || model.savingRecording)
                    } else if !model.connected && !model.savingRecording {
                        HStack(spacing: 16) {
                            LocalBroadcastPicker().frame(width: 64, height: 64)
                                .accessibilityLabel("Start or stop SkyCompanion screen broadcast")
                            Text("Tap to broadcast. Choose SkyCompanion.")
                        }
                    }
                    Text("Saves this screen, the original video sound, your voice and SkyCompanion responses to Photos.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Text(model.recordingStatus).font(.footnote)
                    if model.connected || model.savingRecording {
                        Button("Stop recording and save", role: .destructive) {
                            Task { await model.stopRecordingAndEnd() }
                        }.frame(minHeight: 44).disabled(model.savingRecording)
                    }
                }
                Section("Voice commands") {
                    Button { Task { _ = await model.voice.startListening() } } label: {
                        Label(LocalizedStringKey(model.voice.listening ? "Listening for commands" : "Enable voice commands"), systemImage: "mic")
                            .frame(minHeight: 44)
                    }.disabled(model.voice.listening || model.voice.starting)
                    Text(model.voice.status).font(.footnote).foregroundStyle(.secondary)
                }
                Section("Analysis") {
                    NavigationLink("Depth and path testing") { ExperimentalToolsScreen(model: model) }.frame(minHeight:44)
                    SessionStatusCard(model: model)
                    if let assessment = model.assessment {
                        Text(String.localizedStringWithFormat(String(localized: "Current risk level: R%lld"), assessment.level.rawValue)).font(.headline)
                        Text(assessment.text)
                    }
                    if let summary = model.summary { Text(summary.text) }
                    if let frame = model.frame {
                        Text(String.localizedStringWithFormat(String(localized: "%lld detections in the latest analyzed frame"), frame.detections.count)).font(.subheadline)
                        ForEach(Array(frame.detections.prefix(12).enumerated()), id: \.offset) { index, detection in
                            LabeledContent(model.wearerObservation?.matchedIndex(in: frame) == index ? String(localized: "Followed user · excluded") : detection.label, value: String.localizedStringWithFormat(String(localized: "%lld%% model score"), Int(detection.confidence * 100)))
                        }
                        Text("Detector labels are diagnostic predictions. Their scores are not risk probabilities.").font(.footnote).foregroundStyle(.secondary)
                    }
                    Button("Describe this camera view") { model.handle(.describe) }.frame(minHeight: 44).disabled(model.phase != .running)
                    NavigationLink("Session controls") { SessionScreen(model: model) }.frame(minHeight: 44)
                }
            }
        }
        .scrollContentBackground(.hidden).background(SkyCompanionTheme.background)
        .navigationTitle("Local video").navigationBarTitleDisplayMode(.inline)
        .fileImporter(isPresented: $showImporter, allowedContentTypes: [.movie], allowsMultipleSelection: false) { result in
            switch result {
            case .success(let urls):
                guard let url = urls.first else { return }
                importError = nil
                Task { await model.importVideo(url) }
            case .failure(let error): importError = error.localizedDescription
            }
        }
    }
}

private struct LocalSettingsScreen: View {
    @AppStorage("sky.appearance") private var appearance = "dark"
    @ObservedObject var model: LocalSessionModel
    @Environment(\.openURL) private var openURL
    var body: some View {
        Form {
            Section("Appearance") {
                Picker("Theme", selection: $appearance) {
                    Text("Night sky").tag("dark")
                    Text("Light").tag("light")
                    Text("Follow iPhone").tag("system")
                }
            }

            Section("Voice") {
                Picker("English voice", selection: Binding(get: { model.voice.voiceID }, set: { model.voice.voiceID = $0 })) {
                    Text("English · automatic voice").tag("")
                    ForEach(model.voice.installedVoices, id: \.identifier) { voice in
                        Text(model.voice.voiceLabel(voice)).tag(voice.identifier)
                    }
                }
                .disabled(model.voice.listening || model.voice.starting)
                Text(model.voice.statusCommandHint).font(.footnote).foregroundStyle(.secondary)
                if model.voice.listening { Text("End assistance before changing the voice.").font(.footnote).foregroundStyle(.secondary) }
                Text(model.voice.voiceDescription).font(.footnote).foregroundStyle(.secondary)
                if model.voice.usingBasicVoice {
                    Text(model.voice.voiceDownloadHelp)
                        .font(.footnote).foregroundStyle(.secondary)
                }
                VStack(alignment: .leading) {
                    Text("Speaking rate").font(.subheadline)
                    Slider(value: Binding(get: { model.voice.rate }, set: { model.voice.rate = $0 }), in: 0.35...0.6, step: 0.01)
                        .accessibilityLabel("Speaking rate").accessibilityValue(String(format: "%.2f", model.voice.rate)).frame(minHeight: 44)
                }
                Button("Play sound check") { model.voice.soundCheck() }.frame(minHeight: 44)
                Button("I heard the sound") { model.voice.confirmSoundHeard() }.frame(minHeight: 44)
                Text(LocalizedStringKey(model.voice.soundChecked ? "You confirmed hearing the sample." : "Output has not been confirmed by you this session."))
                    .font(.footnote).foregroundStyle(.secondary)
            }
            Section("Reminders") {
                Text("Unchanged obstacles stay quiet. Ordinary new alerts use your assistant preferences; higher-risk warnings remain enabled. Directions refer to the camera view.")
                    .font(.footnote).foregroundStyle(.secondary)
                Toggle("Vibrate for new alerts", isOn: $model.vibrationEnabled).frame(minHeight: 44)
                Button("Test vibration") { model.testVibration() }.frame(minHeight: 44)
                Text("While you speak a command or hear its reply, ordinary new obstacles use vibration without interrupting. Vibration follows the same repeat limits. Background delivery still needs testing.")
                    .font(.footnote).foregroundStyle(.secondary)
                Toggle("Quieter alerts", isOn: $model.quieter).frame(minHeight: 44)
                Text("Reduces attention-level interruptions. Higher image-conflict alerts remain enabled unless you mute alerts.")
                    .font(.footnote).foregroundStyle(.secondary)
                Toggle("Mute spoken alerts", isOn: Binding(get: { model.voice.muted }, set: { model.voice.setMuted($0) })).frame(minHeight: 44)
                Text("Muting speech keeps the microphone and enabled vibration on.").font(.footnote).foregroundStyle(.secondary)
            }
            Section("On-device speech") {
                Label(LocalizedStringKey(model.voice.speechAvailable ? "Selected command language available offline" : "Selected command language unavailable offline"),
                      systemImage: model.voice.speechAvailable ? "iphone" : "exclamationmark.triangle")
                Text("Permissions, locally installed speech resources and the active audio route are checked when listening starts. There is no cloud fallback.")
                    .font(.footnote).foregroundStyle(.secondary)
                Button("Open iPhone Settings") { if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) } }.frame(minHeight: 44)
            }
            Section("Local data") {
                Toggle("Include image in reports", isOn: $model.saveEvidence).frame(minHeight: 44)
                Text("When available, a still image from the same analyzed frame is saved with an incorrect-alert report. No image is saved unless you report it. This does not record continuous video or audio.")
                    .font(.footnote).foregroundStyle(.secondary)
                Button("Delete saved cases and diagnostics", role: .destructive) { model.deleteLocalData() }.frame(minHeight: 44)
                Text("Images and diagnostics stay on this phone. When Photon sync is enabled, structured reminder records and correction notes are uploaded separately.").font(.footnote).foregroundStyle(.secondary)
            }
            Section {
                NavigationLink("Assistant and Photon settings") { CompanionScreen(model: model, companion: model.photon) }.frame(minHeight: 44)
                NavigationLink("Select followed user") { PathSetupScreen(model: model) }.frame(minHeight: 44)
                NavigationLink("Depth and path testing") { ExperimentalToolsScreen(model: model) }.frame(minHeight: 44)
                NavigationLink("Diagnostics") { DiagnosticsScreen(model: model) }.frame(minHeight: 44)
            }
        }.scrollContentBackground(.hidden).background(SkyCompanionTheme.background)
        .navigationTitle("Settings").navigationBarTitleDisplayMode(.inline)
    }
}

private struct DiagnosticsScreen: View {
    @ObservedObject var model: LocalSessionModel
    var body: some View {
        List {
            Section("Build and verification") {
                Text(model.modelDescription)
                Label("Field performance not yet verified", systemImage: "exclamationmark.triangle")
                Text("A successful build or local video run does not verify DJI Fly capture, sustained device performance, acoustic latency or walking safety.")
                    .font(.footnote).foregroundStyle(.secondary)
                LabeledContent("iOS", value: UIDevice.current.systemVersion)
            }
            Section("Current measurements") {
                LabeledContent("Analyzed frames", value: String(format: String(localized: "%.1f fps"), model.fps))
                LabeledContent("Observation age", value: model.frame == nil ? String(localized: "No frame") : String(format: String(localized: "%.0f ms"), model.frameAgeMS))
                LabeledContent("Model processing", value: model.frame.map { String(format: String(localized: "%.0f ms"), $0.inferenceMS) } ?? String(localized: "Not measured"))
                LabeledContent("Vision process memory", value: model.memoryMB > 0 ? String(format: String(localized: "%.1f MB"), model.memoryMB) : String(localized: "Not measured"))
                Text("Frame age starts when SkyCompanion receives a frame. Speech logs record the system callback, not measured sound reaching your ear.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            Section("Recent local events") {
                if model.log.isEmpty { Text("No diagnostic events recorded.").foregroundStyle(.secondary) }
                ForEach(Array(model.log.reversed().enumerated()), id: \.offset) { _, line in
                    Text(line).font(.footnote).textSelection(.enabled)
                }
            }
        }.scrollContentBackground(.hidden).background(SkyCompanionTheme.background)
        .navigationTitle("Diagnostics").navigationBarTitleDisplayMode(.inline)
    }
}

private struct LocalBroadcastPicker: UIViewRepresentable {
    func makeUIView(context: Context) -> RPSystemBroadcastPickerView {
        let picker = RPSystemBroadcastPickerView(frame: CGRect(x: 0, y: 0, width: 64, height: 64))
        picker.preferredExtension = Bundle.main.object(forInfoDictionaryKey: "SkyCompanionBroadcastExtensionIdentifier") as? String
        picker.showsMicrophoneButton = true
        picker.tintColor = UIColor(SkyCompanionTheme.accent)
        return picker
    }
    func updateUIView(_ uiView: RPSystemBroadcastPickerView, context: Context) {}
    func sizeThatFits(_ proposal: ProposedViewSize, uiView: RPSystemBroadcastPickerView, context: Context) -> CGSize? {
        CGSize(width: 64, height: 64)
    }
}
