import SwiftUI
import CaptureCore

struct ExperimentalToolsScreen: View {
    @ObservedObject var model: LocalSessionModel
    var body: some View {
        Form {
            Section("Depth experiment") {
                Toggle("Low-frequency depth estimation", isOn: $model.depthEnabled).frame(minHeight: 44)
                Text("Runs an additional on-device model at most once every two seconds. Compare the same local video with this switch off and on. Performance and memory are recorded locally.")
                Text("Camera-to-obstacle distance unknown. No measured-distance validation has been completed. Raw depth below is diagnostic only and is never spoken as a distance.")
                    .font(.footnote).foregroundStyle(.secondary)
                LabeledContent("YOLO rate", value: String(format: "%.1f fps", model.fps))
                if let depth = model.depthResult {
                    Text(depth.status)
                    LabeledContent("Depth processing", value: String(format: "%.0f ms",depth.inferenceMS))
                    Text("Raw optical-axis depth — not a distance range, confidence interval or distance from the user.").font(.headline)
                    ForEach(Array(depth.samples.enumerated()),id:\.offset) { _,sample in
                        LabeledContent(sample.label,value:sample.rawMedianMeters.map { String(format:"%.2f m · unvalidated",$0) } ?? "Unknown")
                    }
                    Text("Saved depth sample frame \(depth.frameID). It may be older than the current video.").font(.footnote)
                }
            }
            Section("Path monitoring experiment") {
                NavigationLink("Select followed user and path") { PathSetupScreen(model:model) }.frame(minHeight:56)
                Text("A helper selects the visible user and the whole sidewalk or crosswalk corridor. Registration follows small camera changes. Person loss, overlap or uncertain registration stops path judgments until selection is repeated.")
                Button("Speak current path status") { model.handle(.path) }.frame(minHeight:44)
                Text("Say “SkyCompanion path” to request the current path observation.").font(.footnote)
                Text("Rear-following instructions use the person and confirmed corridor. Body heading is assumed from the setup, not automatically measured. This does not authorize crossing.")
                    .font(.footnote).foregroundStyle(.secondary)
                LabeledContent("Configuration",value:model.pathConfigured ? "Confirmed region selected" : "Not configured")
                if let path = model.pathObservation {
                    LabeledContent("Observed path state",value:path.state.rawValue)
                    Text(path.reason).font(.footnote)
                }
                if let walking = model.walkingObservation {
                    Text(walking.speech.isEmpty ? "No current walking instruction." : walking.speech).font(.headline)
                    Text(walking.reason).font(.footnote)
                }
                if model.pathConfigured { Button("Disable path monitoring") { model.disablePath() }.frame(minHeight:44) }
            }
        }.scrollContentBackground(.hidden).background(SkyCompanionTheme.background)
        .navigationTitle("Depth and path testing").navigationBarTitleDisplayMode(.inline)
    }
}

struct PathSetupScreen: View {
    @ObservedObject var model: LocalSessionModel
    @State private var snapshot: LocalPacket?
    @State private var personIndex = -1
    @State private var corner = 0
    @State private var kind = "sidewalk"
    @State private var rearFollowing = true
    @State private var boundary = [MobilePoint(x:0.25,y:0.15),MobilePoint(x:0.75,y:0.15),MobilePoint(x:0.9,y:0.95),MobilePoint(x:0.1,y:0.95)]
    var body: some View {
        Form {
            Section("1 · Freeze an analyzed view") {
                Text("Start analysis first. For DJI Fly, return here after analysis starts. This setup uses a saved view of the person and road, not the phone screen crop. A sighted helper is needed to confirm the region in this experimental version.")
                Button("Use latest analyzed view and pause") {
                    snapshot = model.inspection; personIndex = -1; model.pause()
                }.frame(minHeight:56).disabled(model.inspection?.preview == nil)
            }
            if let snapshot, let data = snapshot.preview, let image = UIImage(data:data), let frame = snapshot.frame {
                Section("2 · Select the user") {
                    Image(uiImage:image).resizable().scaledToFit().overlay {
                        GeometryReader { geometry in
                            Path { path in
                                let size=geometry.size
                                path.move(to:CGPoint(x:boundary[0].x*size.width,y:boundary[0].y*size.height))
                                for point in boundary.dropFirst() { path.addLine(to:CGPoint(x:point.x*size.width,y:point.y*size.height)) }
                                path.closeSubpath()
                            }.stroke(.orange,lineWidth:3)
                            ForEach(Array(frame.detections.enumerated()).filter { $0.element.label == "person" },id:\.offset) { index,p in
                                Rectangle().stroke(index == personIndex ? Color.green : Color.white,lineWidth:3)
                                    .frame(width:p.width*geometry.size.width,height:p.height*geometry.size.height)
                                    .overlay(alignment:.topLeading) { Text("\(index+1)").font(.headline).foregroundStyle(.black).background(.white) }
                                    .position(x:(p.x+p.width/2)*geometry.size.width,y:(p.y+p.height/2)*geometry.size.height)
                            }
                        }.allowsHitTesting(false)
                    }.accessibilityLabel("Saved view with numbered people and an orange path boundary")
                    Picker("Person in the saved view",selection:$personIndex) {
                        Text("Select a person").tag(-1)
                        ForEach(Array(frame.detections.enumerated()).filter { $0.element.label == "person" },id:\.offset) { index,p in
                            Text("Person \(index+1), camera \(p.direction.rawValue)").tag(index)
                        }
                    }
                    Text("Select the user explicitly. Another nearby person must not become the user automatically.").font(.footnote)
                    Button("Confirm followed user") { model.confirmWearer(snapshot:snapshot,personIndex:personIndex) }
                        .frame(minHeight:56).disabled(personIndex < 0)
                    Text("This person will be excluded from descriptions, obstacle alerts and depth samples while tracking is reliable. Other people stay included.").font(.footnote)
                    if model.wearerConfigured {
                        Text(model.message)
                        Button(model.source == .video ? "Resume video analysis" : "Arm and switch to DJI Fly") {
                            if model.source == .video { model.playVideo() } else { model.armDrone() }
                        }.frame(minHeight:56)
                    }

                }
                Section("3 · Optional: confirm a walking corridor") {
                    Picker("Region type",selection:$kind) {
                        Text("Sidewalk").tag("sidewalk"); Text("Crosswalk").tag("crosswalk")
                    }
                    Text("Place four corners clockwise around the usable region. For a crosswalk, include the gaps between stripes. Exclude adjacent traffic lanes. Keep all corners in the image.")
                    Picker("Corner",selection:$corner) {
                        ForEach(0..<4) { i in Text("Corner \(i+1)").tag(i) }
                    }
                    LabeledContent("Horizontal",value:String(format:"%.0f%%",boundary[corner].x*100))
                    Slider(value:Binding(get:{boundary[corner].x},set:{boundary[corner].x=$0}),in:0...1,step:0.01).accessibilityLabel("Corner horizontal position")
                    LabeledContent("Vertical",value:String(format:"%.0f%%",boundary[corner].y*100))
                    Slider(value:Binding(get:{boundary[corner].y},set:{boundary[corner].y=$0}),in:0...1,step:0.01).accessibilityLabel("Corner vertical position")
                    if !MobilePathMonitor.validBoundary(boundary) { Text("The corners must form a non-crossing convex region.").foregroundStyle(.red) }
                    Toggle("Drone follows behind, facing my walking direction", isOn: $rearFollowing).frame(minHeight:44)
                    Text("Use an unmirrored rear view. Reconfirm after a turn, a side view or a change of camera direction. This experimental mode checks image corridors, not measured physical clearance.").font(.footnote)
                    Button("Confirm person and path") {
                        model.confirmPath(snapshot:snapshot,personIndex:personIndex,boundary:boundary,kind:kind,rearFollowing:rearFollowing)
                    }.frame(minHeight:56).disabled(personIndex < 0 || !MobilePathMonitor.validBoundary(boundary))
                    Text(model.message)
                    if model.pathConfigured {
                        Button(model.source == .video ? "Resume video analysis" : "Arm and switch to DJI Fly") {
                            if model.source == .video { model.playVideo() } else { model.armDrone() }
                        }.frame(minHeight:56)
                    }
                }
            }
        }.scrollContentBackground(.hidden).background(SkyCompanionTheme.background)
        .navigationTitle("Person and path").navigationBarTitleDisplayMode(.inline)
    }
}
