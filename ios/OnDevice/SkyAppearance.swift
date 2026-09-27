import SwiftUI

/// One brand opening per process. The session model stays mounted underneath it.
struct SkyCompanionRootView: View {
    @State private var showingOpening = true
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.accessibilityVoiceOverEnabled) private var voiceOver
    @Environment(\.scenePhase) private var scenePhase
    @AppStorage("sky.appearance") private var appearance = "dark"

    var body: some View {
        ZStack {
            LocalContentView(openingVisible: showingOpening)
                .accessibilityHidden(showingOpening)
                .allowsHitTesting(!showingOpening)
            if showingOpening {
                SkyOpeningView(action: finishOpening)
                    .transition(.opacity)
                    .zIndex(1)
            }
        }
        .preferredColorScheme(appearance == "system" ? nil : appearance == "light" ? .light : .dark)
        .task {
            // VoiceOver users enter the actual controls immediately.
            if voiceOver { finishOpening(); return }
            #if DEBUG && targetEnvironment(simulator)
            if ProcessInfo.processInfo.environment["SKYCOMPANION_PREVIEW_ROUTE"] == "opening" { return }
            #endif
            do { try await Task.sleep(for: .seconds(reduceMotion ? 0.7 : 1.6)) }
            catch { return }
            finishOpening()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .background { finishOpening() }
        }
        .onChange(of: voiceOver) { _, enabled in
            if enabled { finishOpening() }
        }
    }

    private func finishOpening() {
        guard showingOpening else { return }
        withAnimation(reduceMotion || voiceOver ? nil : .easeOut(duration: 0.3)) {
            showingOpening = false
        }
    }
}

private struct SkyOpeningView: View {
    let action: () -> Void
    var body: some View {
        GeometryReader { geometry in
            Button(action: action) {
                ZStack {
                    Color(red: 0.005, green: 0.024, blue: 0.075)
                    Image("MoonFlight")
                        .resizable().scaledToFit()
                        .frame(width: min(geometry.size.width, geometry.size.height * 0.94))
                        .mask(LinearGradient(stops: [.init(color: .clear, location: 0), .init(color: .black, location: 0.12)], startPoint: .top, endPoint: .bottom))
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
                    VStack(spacing: 12) {
                        Text("SkyCompanion").font(.largeTitle.weight(.semibold))
                        Text("Fly me to the moon.").font(.subheadline).foregroundStyle(.white.opacity(0.8))
                    }
                    .foregroundStyle(.white)
                    .padding(.horizontal, 24)
                    .padding(.top, max(geometry.safeAreaInsets.top + 32, geometry.size.height * 0.13))
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Enter SkyCompanion")
            .accessibilityHint("Skip the opening image.")
        }
        .ignoresSafeArea()
        .statusBarHidden()
    }
}

enum SkyCompanionTheme {
    static let accent = adaptive(light: 0x215B9E, dark: 0xABD0FF)
    static let background = adaptive(light: 0xF0F3F8, dark: 0x0C121D)
    static let surface = adaptive(light: 0xFFFFFF, dark: 0x192230)
    static let border = adaptive(light: 0xCED8E5, dark: 0x3D4F66)
    static let action = adaptive(light: 0xDCEBFF, dark: 0xD5E6FF)
    static let actionText = Color(red: 0.04, green: 0.10, blue: 0.18)

    private static func adaptive(light: UInt32, dark: UInt32) -> Color {
        Color(uiColor: UIColor { traits in
            let hex = traits.userInterfaceStyle == .dark ? dark : light
            return UIColor(red: CGFloat((hex >> 16) & 255) / 255,
                           green: CGFloat((hex >> 8) & 255) / 255,
                           blue: CGFloat(hex & 255) / 255, alpha: 1)
        })
    }
}

struct SkyCard: ViewModifier {
    @Environment(\.colorSchemeContrast) private var contrast
    func body(content: Content) -> some View {
        content
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(SkyCompanionTheme.surface, in: RoundedRectangle(cornerRadius: 24))
            .overlay { RoundedRectangle(cornerRadius: 24).strokeBorder(SkyCompanionTheme.border.opacity(contrast == .increased ? 1 : 0.55), lineWidth: contrast == .increased ? 2 : 1) }
    }
}

/// The photograph is decorative; the source and action are real native labels.
struct SkyDroneCard: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    var body: some View {
        VStack(spacing: 0) {
            if !dynamicTypeSize.isAccessibilitySize {
                Color(red: 0.005, green: 0.024, blue: 0.075)
                .frame(height: 210)
                .overlay {
                    Image("MoonFlight").resizable().scaledToFill()
                        .accessibilityHidden(true)
                }
                .clipped()
            }
            HStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Connect drone").font(.title3.weight(.semibold))
                    if !dynamicTypeSize.isAccessibilitySize { Text("Use the DJI Fly camera view").font(.subheadline) }
                }
                Spacer(minLength: 0)
                if !dynamicTypeSize.isAccessibilitySize { Image(systemName: "arrow.up.right").font(.title3.weight(.semibold)) }
            }
            .foregroundStyle(SkyCompanionTheme.actionText)
            .padding(20)
            .frame(maxWidth: .infinity, minHeight: 80, alignment: .leading)
            .background(SkyCompanionTheme.action)
        }
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Connect drone")
        .accessibilityHint("Opens voice assistance, screen sharing and camera setup.")
    }
}

struct SkyActionRow: View {
    let title: LocalizedStringKey
    let subtitle: LocalizedStringKey?
    let symbol: String
    init(_ title: LocalizedStringKey, subtitle: LocalizedStringKey? = nil, symbol: String) {
        self.title = title; self.subtitle = subtitle; self.symbol = symbol
    }
    var body: some View {
        HStack(spacing: 16) {
            Image(systemName: symbol).font(.title2).foregroundStyle(SkyCompanionTheme.accent)
                .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
                .frame(width: 32).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.headline).foregroundStyle(.primary)
                if let subtitle { Text(subtitle).font(.subheadline).foregroundStyle(.secondary) }
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right").font(.footnote.weight(.semibold))
                .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
                .foregroundStyle(.secondary).accessibilityHidden(true)
        }
        .frame(minHeight: 40)
    }
}
