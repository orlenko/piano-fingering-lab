import SwiftUI
import AppKit
import AVKit
import PDFKit
import UniformTypeIdentifiers

private let ink = Color(red: 0.16, green: 0.21, blue: 0.18)
private let paper = Color(red: 0.97, green: 0.96, blue: 0.93)
private let accent = Color(red: 0.22, green: 0.39, blue: 0.29)

final class StudioDelegate: NSObject, NSApplicationDelegate {
    weak var model: StudioModel?
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply { model?.requestQuit() ?? .terminateNow }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
struct StudioApp: App {
    @NSApplicationDelegateAdaptor(StudioDelegate.self) var delegate
    @StateObject private var model = StudioModel()
    var body: some Scene {
        WindowGroup("Fingering Studio") {
            StudioView(model: model).frame(minWidth: 1100, minHeight: 740)
                .preferredColorScheme(.light)
                .onAppear {
                    delegate.model = model
                    if let i = CommandLine.arguments.firstIndex(of: "--snapshot"), CommandLine.arguments.count > i + 1 { model.snapshotPath = CommandLine.arguments[i + 1] }
                    if let i = CommandLine.arguments.firstIndex(of: "--ui-check"), CommandLine.arguments.count > i + 1 { model.uiCheckPath = CommandLine.arguments[i + 1] }
                    if let i = CommandLine.arguments.firstIndex(of: "--ui-state"), CommandLine.arguments.count > i + 1 { model.uiState = CommandLine.arguments[i + 1] }
                    if !model.ready && !model.busy { model.boot() }
                }
                .onOpenURL { model.accept($0) }
        }
        .defaultSize(width: 1280, height: 840)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("New Project") { model.newProject() }.keyboardShortcut("n").disabled(model.busy)
                Button("Open Project…") { model.chooseProject() }.keyboardShortcut("o").disabled(model.busy)
            }
        }
    }
}

struct StudioView: View {
    @ObservedObject var model: StudioModel
    var body: some View {
        HStack(spacing: 0) {
            sidebar.frame(width: 208)
            Divider()
            VStack(alignment: .leading, spacing: 0) {
                header
                if let error = model.error {
                    HStack(alignment: .top) {
                        Image(systemName: "info.circle").padding(.top, 2)
                        Text(error).font(.system(size: 12)).textSelection(.enabled)
                        Spacer()
                        if let log = model.lastLog { Button("Reveal log") { NSWorkspace.shared.activateFileViewerSelecting([log]) }.buttonStyle(.link) }
                        Button { model.error = nil } label: { Image(systemName: "xmark") }.buttonStyle(.plain)
                    }.padding(14).background(Color.orange.opacity(0.10))
                }
                if model.busy { processing }
                else if model.hasResults { review }
                else if model.project != nil { savedProject }
                else { inputs }
                footer
            }.background(paper)
        }.foregroundStyle(ink).tint(accent)
        .onDrop(of: [.fileURL], isTargeted: nil) { providers in
            guard !model.busy else { return false }
            for provider in providers.prefix(3) {
                _ = provider.loadObject(ofClass: URL.self) { url, _ in
                    if let url = url { DispatchQueue.main.async { model.accept(url) } }
                }
            }
            return true
        }
    }
    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 24) {
            HStack(spacing: 9) {
                Image(systemName: "pianokeys").font(.system(size: 25))
                Text("Fingering\nStudio").font(.system(size: 18, weight: .semibold, design: .serif))
            }.padding(.top, 12)
            VStack(alignment: .leading, spacing: 12) {
                Button { model.newProject() } label: { Label("New project", systemImage: "plus") }
                Button { model.chooseProject() } label: { Label("Open project…", systemImage: "folder") }
            }.buttonStyle(.plain).disabled(model.busy)
            Divider()
            Text("RECENT PROJECTS").font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 14) {
                if model.recents.isEmpty { Text("Your practice sessions\nwill appear here.").font(.system(size: 12)).foregroundStyle(.secondary) }
                ForEach(model.recents, id: \.self) { path in
                    Button { model.open(URL(fileURLWithPath: path)) } label: {
                        Label(URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent, systemImage: "doc.richtext").lineLimit(2).multilineTextAlignment(.leading)
                    }.buttonStyle(.plain).font(.system(size: 12)).disabled(model.busy)
                }
            }
            Spacer()
            VStack(alignment: .leading, spacing: 8) {
                Label("Made for a closer listen", systemImage: "ear").font(.system(size: 11))
                Text("Experimental · 0.1\nYour recordings stay on this Mac.").font(.system(size: 10)).foregroundStyle(.secondary).lineSpacing(4)
            }
        }.padding(22).frame(maxHeight: .infinity).background(Color.white.opacity(0.68))
    }
    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 5) {
                Text(model.project == nil ? "A practice session, made visible." : model.projectName)
                    .font(.system(size: 24, weight: .medium, design: .serif))
                Text(model.project == nil ? "Bring a recording and its score. Take a closer look at the hands behind the music." : model.status)
                    .font(.system(size: 12)).foregroundStyle(.secondary)
            }
            Spacer(minLength: 20)
            if model.hasResults && !model.busy {
                if model.dirty { Button("Update video & score") { model.update() }.buttonStyle(.borderedProminent).disabled(model.leased) }
                Button("Export…") { model.export() }.buttonStyle(.borderedProminent).disabled(model.dirty || model.leased)
            }
        }.padding(28)
    }
    private var inputs: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 26) {
                HStack(spacing: 18) {
                    dropCard(title: "Your performance", subtitle: "MOV or MP4 · piano audio included", symbol: "video", url: model.video) { model.choose(true) }
                    dropCard(title: "The score", subtitle: "A supported, digitally typeset PDF", symbol: "music.note.list", url: model.score) { model.choose(false) }
                }
                VStack(alignment: .leading, spacing: 12) {
                    Text("A little preparation goes a long way.").font(.system(size: 18, weight: .medium, design: .serif))
                    Label("Use a short excerpt: up to 30 seconds, 1080p, and 1,000 frames.", systemImage: "clock")
                    Label("Film from behind the music desk, keeping both hands and the bass end visible.", systemImage: "hand.raised.fingers.spread")
                    Label("PDF support is limited to certain Doremi-font editions. Scans are not supported yet.", systemImage: "doc.text.magnifyingglass")
                }.font(.system(size: 12)).foregroundStyle(.secondary).padding(22).frame(maxWidth: .infinity, alignment: .leading).background(.white.opacity(0.7), in: RoundedRectangle(cornerRadius: 12))
                HStack(alignment: .bottom, spacing: 18) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("PROJECT NAME").font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
                        TextField("My practice session", text: $model.projectName).textFieldStyle(.roundedBorder).frame(maxWidth: 340)
                    }
                    Spacer()
                    Button("Create project & analyze") { model.create() }.controlSize(.large).buttonStyle(.borderedProminent)
                        .disabled(!model.ready || model.video == nil || model.score == nil)
                }
                Text("The project keeps copies of your originals, analysis, and corrections together. You choose where it lives.")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
            }.padding(28).padding(.top, 10)
        }
    }
    private func dropCard(title: String, subtitle: String, symbol: String, url: URL?, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 15) {
                HStack { Image(systemName: url == nil ? symbol : "checkmark.circle.fill").font(.system(size: 27)).foregroundStyle(accent); Spacer(); Text(url == nil ? "01 / INPUT" : "SELECTED").font(.system(size: 9, weight: .medium)).foregroundStyle(.secondary) }
                Spacer(minLength: 12)
                Text(title).font(.system(size: 21, weight: .medium, design: .serif))
                Text(url?.lastPathComponent ?? "Drop a file here, or click to choose").lineLimit(2).font(.system(size: 12, weight: url == nil ? .regular : .medium))
                Text(subtitle).font(.system(size: 11)).foregroundStyle(.secondary)
            }.padding(24).frame(maxWidth: .infinity, minHeight: 205, alignment: .leading)
                .background(Color.white, in: RoundedRectangle(cornerRadius: 14))
                .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(accent.opacity(url == nil ? 0.18 : 0.65), style: StrokeStyle(lineWidth: 1, dash: url == nil ? [5, 5] : [])))
        }.buttonStyle(.plain)
    }
    private var processing: some View {
        VStack(spacing: 24) {
            Spacer()
            ProgressView().controlSize(.large)
            Text(model.stopping ? "Finishing safely…" : "A closer look, one step at a time.").font(.system(size: 28, weight: .medium, design: .serif))
            Text(model.status).font(.system(size: 15)).foregroundStyle(.secondary)
            TimelineView(.periodic(from: .now, by: 1)) { context in
                Text("Elapsed " + Duration.seconds(max(0, context.date.timeIntervalSince(model.startedAt))).formatted(.time(pattern: .minuteSecond)))
                    .font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
            }
            VStack(alignment: .leading, spacing: 14) {
                ForEach(Array(["Listen to the recording", "Read the score", "Find the passage", "Follow the hands", "Locate the keyboard", "Estimate fingerings", "Prepare video & score"].enumerated()), id: \.offset) { index, label in
                    HStack(spacing: 12) {
                        Image(systemName: model.stage > index + 1 ? "checkmark.circle.fill" : (model.stage == index + 1 ? "circle.inset.filled" : "circle"))
                            .foregroundStyle(model.stage >= index + 1 ? accent : Color.gray.opacity(0.4))
                        Text(label).foregroundStyle(model.stage == index + 1 ? ink : .secondary)
                    }
                }
            }.font(.system(size: 12)).padding(22).frame(width: 300, alignment: .leading).background(.white, in: RoundedRectangle(cornerRadius: 12))
            Button(model.stopping ? "Stopping…" : "Stop") { model.stop() }.disabled(model.stopping)
            Text("Processing stays on this Mac. It may take several minutes.\nYou can stop without losing your originals or previous result.").font(.system(size: 11)).foregroundStyle(.secondary).multilineTextAlignment(.center)
            Spacer()
        }.frame(maxWidth: .infinity)
    }
    private var savedProject: some View {
        VStack(spacing: 20) {
            Spacer(); Image(systemName: "folder.badge.checkmark").font(.system(size: 42)).foregroundStyle(accent)
            Text(model.leased ? "This session needs recovery." : "Your session is saved.").font(.system(size: 27, design: .serif))
            Text(model.leased ? "Make a copy after the previous app window has stopped.\nThe original project will be preserved." : "The app will analyze the audio, score, keyboard, and hands locally.").font(.system(size: 13)).foregroundStyle(.secondary).multilineTextAlignment(.center)
            if model.leased { Button("Make recovery copy…") { model.recover() }.buttonStyle(.borderedProminent) }
            else { Button("Analyze performance") { model.analyze() }.buttonStyle(.borderedProminent).disabled(!model.ready) }
            Spacer()
        }.frame(maxWidth: .infinity)
    }
    private var review: some View {
        HStack(alignment: .top, spacing: 0) {
            VStack(alignment: .leading, spacing: 16) {
                if model.leased { Button("Make recovery copy…") { model.recover() }.buttonStyle(.borderedProminent) }
                if model.dirty {
                    Label("Corrections saved. Update the video and score before exporting.", systemImage: "pencil.circle.fill")
                        .font(.system(size: 12)).padding(12).frame(maxWidth: .infinity, alignment: .leading).background(accent.opacity(0.09), in: RoundedRectangle(cornerRadius: 8))
                }
                Picker("Preview", selection: $model.tab) { Text("Video").tag("Video"); Text("Score").tag("Score") }.pickerStyle(.segmented).frame(width: 240)
                GeometryReader { geometry in
                    Group {
                        if model.tab == "Video", let player = model.player { PerformancePreview(player: player).background(.black).clipShape(RoundedRectangle(cornerRadius: 10)) }
                        else if let url = model.scoreResult { ScorePreview(url: url, note: model.selectedNote) { failedURL in
                            if model.scoreResult == failedURL { model.error = "This saved score could not be opened. Reanalyze to create a fresh result; your originals are preserved." }
                        }.clipShape(RoundedRectangle(cornerRadius: 10)) }
                    }.frame(width: geometry.size.width, height: geometry.size.height)
                }.frame(minHeight: 180)
                HStack(spacing: 15) {
                    legend("Likely", .blue); legend("Uncertain", .orange); legend("Unknown", .gray); legend("Your correction", accent)
                }.font(.system(size: 10))
                Text("Automatic tiers reflect a heuristic, not measured correctness. Confirm fingerings by watching the hands. Select a note to seek the video or locate it in the score.").font(.system(size: 11)).foregroundStyle(.secondary)
                HStack {
                    Text("\(model.notes.count) note events · \(model.notes.filter { ["low", "unknown"].contains($0.tier) }.count) need a look").font(.system(size: 11)).foregroundStyle(.secondary)
                    Spacer()
                    Button("Reveal project") { if let p = model.project { NSWorkspace.shared.activateFileViewerSelecting([p]) } }.buttonStyle(.link)
                    Button("Analyze again") { model.analyze() }.disabled(model.leased || model.dirty).help("Creates a new automatic result. Pending corrections must be updated first.")
                }
            }.padding(24)
            Divider()
            VStack(alignment: .leading, spacing: 0) {
                HStack { Text("THE NOTES").font(.system(size: 10, weight: .semibold)); Spacer(); Image(systemName: "list.bullet") }.padding(18)
                Picker("Filter notes", selection: $model.filter) { Text("All notes").tag("All notes"); Text("Needs a look").tag("Needs a look"); Text("Corrected").tag("Corrected") }.labelsHidden().padding(.horizontal, 16).padding(.bottom, 10)
                List(selection: Binding(get: { model.selected }, set: { model.select($0) })) {
                    ForEach(model.visibleNotes) { note in
                        HStack(spacing: 9) {
                            VStack(alignment: .leading, spacing: 5) { Text(note.pitch).font(.system(size: 14, weight: .medium)); Text(note.measure.map { "Measure \($0)" } ?? "Unmatched note").font(.system(size: 10)).foregroundStyle(.secondary) }
                            Spacer()
                            VStack(alignment: .trailing, spacing: 5) { Text(note.label).font(.system(size: 14, weight: .semibold, design: .monospaced)); Text(note.tierLabel).font(.system(size: 9)).foregroundStyle(note.tier == "low" ? .orange : .secondary) }
                        }.padding(.vertical, 5).tag(note.id)
                    }
                }.listStyle(.inset).frame(minHeight: 150)
                if let note = model.selectedNote { inspector(note) }
            }.frame(width: 280).background(.white.opacity(0.65))
        }
    }
    private func legend(_ title: String, _ color: Color) -> some View { HStack(spacing: 4) { Circle().fill(color).frame(width: 6, height: 6); Text(title) } }
    private func inspector(_ note: NoteRow) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Divider()
            HStack { Text("\(note.pitch) · \(note.label)").font(.system(size: 18, design: .serif)); Spacer(); if let t = note.time { Text(String(format: "%.2fs", t)).font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary) } }
            Text(note.reason).font(.system(size: 11)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            Text("Original estimate: \(note.autoHand == "unknown" ? "?" : note.autoHand + note.autoFinger) · \(["high": "Likely", "low": "Uncertain", "unknown": "Unknown"][note.autoTier] ?? "Unknown")")
                .font(.system(size: 10)).foregroundStyle(.secondary)
            HStack {
                Picker("Hand", selection: $model.correctionHand) { Text("Hand…").tag(""); Text("Left").tag("L"); Text("Right").tag("R") }.labelsHidden()
                Picker("Finger", selection: $model.correctionFinger) { Text("Finger…").tag(""); ForEach(1...5, id: \.self) { Text(String($0)).tag(String($0)) } }.labelsHidden()
            }
            Button("Save correction") { model.correct("set") }.disabled(model.correctionHand.isEmpty || model.correctionFinger.isEmpty).buttonStyle(.borderedProminent).frame(maxWidth: .infinity)
            HStack { Button("Mark unknown") { model.correct("unknown") }; Spacer(); Button("Reset") { model.correct("reset") }.disabled(!note.corrected) }.buttonStyle(.link).font(.system(size: 11))
        }.padding(18).disabled(model.leased)
    }
    private var footer: some View {
        HStack {
            Label(model.ready ? "Local engine ready" : "Checking local engine", systemImage: model.ready ? "checkmark.shield" : "circle.dotted")
            Spacer(); Text("Apple Silicon · macOS 14+ · Experimental")
        }.font(.system(size: 10)).foregroundStyle(.secondary).padding(.horizontal, 26).padding(.vertical, 12).background(Color.white.opacity(0.45))
    }
}

struct ScorePreview: NSViewRepresentable {
    let url: URL
    let note: NoteRow?
    var onFailure: (URL) -> Void
    final class Coordinator { var url: URL?; var noteID: String?; var marker: PDFAnnotation?; weak var page: PDFPage? }
    func makeCoordinator() -> Coordinator { Coordinator() }
    func makeNSView(context: Context) -> PDFView {
        let v = PDFView(); v.autoScales = true; v.displayMode = .singlePageContinuous; v.backgroundColor = .windowBackgroundColor; return v
    }
    func updateNSView(_ view: PDFView, context: Context) {
        let c = context.coordinator
        if c.url != url {
            view.document = PDFDocument(url: url); c.url = url; c.noteID = nil
            if view.document == nil { DispatchQueue.main.async { onFailure(url) } }
        }
        guard c.noteID != note?.id else { return }
        if let old = c.marker { c.page?.removeAnnotation(old) }; c.marker = nil; c.noteID = note?.id
        if let n = note, let p = n.page, let page = view.document?.page(at: p), let x = n.x, let y = n.y {
            let bounds = page.bounds(for: .mediaBox)
            let rect = NSRect(x: x - 10, y: bounds.height - y - 10, width: 20, height: 20)
            let marker = PDFAnnotation(bounds: rect, forType: .circle, withProperties: nil)
            marker.color = .systemGreen; marker.border = PDFBorder(); marker.border?.lineWidth = 2
            page.addAnnotation(marker); c.marker = marker; c.page = page
            view.go(to: rect.insetBy(dx: -60, dy: -60), on: page)
        }
    }
}


struct PerformancePreview: NSViewRepresentable {
    let player: AVPlayer
    func makeNSView(context: Context) -> AVPlayerView {
        let view = AVPlayerView(); view.controlsStyle = .inline; view.player = player
        view.showsFullScreenToggleButton = true; return view
    }
    func updateNSView(_ view: AVPlayerView, context: Context) {
        if view.player !== player { view.player = player }
    }
}
