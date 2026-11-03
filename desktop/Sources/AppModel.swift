import SwiftUI
import AppKit
import AVKit
import PDFKit

struct NoteRow: Identifiable {
    let id: String, pitch: String, hand: String, finger: String, tier: String
    let autoHand: String, autoFinger: String, autoTier: String, reason: String
    let measure: Int?, time: Double?, page: Int?, x: Double?, y: Double?
    let corrected: Bool
    init?(_ d: [String: Any]) {
        guard let id = d["id"] as? String, let pitch = d["pitch"] as? String,
              let hand = d["hand"] as? String, let finger = d["finger"] as? String,
              let tier = d["tier"] as? String else { return nil }
        self.id = id; self.pitch = pitch; self.hand = hand; self.finger = finger; self.tier = tier
        autoHand = d["autoHand"] as? String ?? "unknown"; autoFinger = d["autoFinger"] as? String ?? "unknown"
        autoTier = d["autoTier"] as? String ?? "unknown"; reason = d["reason"] as? String ?? ""
        measure = d["measure"] as? Int; time = d["time"] as? Double; page = d["page"] as? Int
        x = d["x"] as? Double; y = d["y"] as? Double; corrected = d["corrected"] as? Bool ?? false
    }
    var label: String { hand == "unknown" || finger == "unknown" ? "?" : "\(hand)\(finger)" }
    var tierLabel: String { ["high": "Likely", "low": "Uncertain", "unknown": "Unknown", "manual": "Your correction"][tier] ?? "Unknown" }
}

final class StudioModel: ObservableObject {
    @Published var video: URL?
    @Published var score: URL?
    @Published var project: URL?
    @Published var projectName = "My practice session"
    @Published var busy = false
    @Published var ready = false
    @Published var stopping = false
    @Published var hasResults = false
    @Published var dirty = false
    @Published var leased = false
    @Published var stage = 0
    @Published var status = "Checking the local engine…"
    @Published var error: String?
    @Published var notes = [NoteRow]()
    @Published var selected: String?
    @Published var filter = "All notes"
    @Published var tab = "Video"
    @Published var player: AVPlayer?
    @Published var scoreResult: URL?
    @Published var revision = 0
    @Published var runID: String?
    @Published var lastLog: URL?
    @Published var lastExport: URL?
    @Published var recents = [String]()
    @Published var correctionHand = ""
    @Published var correctionFinger = ""
    @Published var startedAt = Date()
    private var playerObservation: NSKeyValueObservation?
    private var pendingOpen: URL?
    private var runner: JobRunner?, generation = UUID()
    private var quitAfter = false
    var snapshotPath: String?
    var uiCheckPath: String?
    var uiState: String?
    private var capturePending = false
    var selectedNote: NoteRow? { notes.first { $0.id == selected } }
    var visibleNotes: [NoteRow] {
        notes.filter { filter == "All notes" || (filter == "Needs a look" ? ["low", "unknown"].contains($0.tier) : $0.corrected) }
    }
    init() { recents = UserDefaults.standard.stringArray(forKey: "recentProjects") ?? [] }
    func boot() {
        invoke("health") { data in
            self.ready = data["ready"] as? Bool ?? false
            self.status = self.ready ? "Everything runs on this Mac." : "The local engine is incomplete."
            if let pending = self.pendingOpen { self.pendingOpen = nil; self.accept(pending) }
            else if let i = CommandLine.arguments.firstIndex(of: "--project"), CommandLine.arguments.count > i + 1 {
                self.open(URL(fileURLWithPath: CommandLine.arguments[i + 1]))
            } else { self.snapshot() }
        }
    }
    func invoke(_ operation: String, _ args: [String] = [], timeout: TimeInterval = 120,
                finished: @escaping ([String: Any]) -> Void = { _ in }) {
        guard !busy else { return }
        busy = true; stopping = false; error = nil; startedAt = Date()
        launch(operation, args, timeout: timeout) { result in
            self.busy = false; self.stopping = false
            if let value = self.resultData(result) { finished(value) }
            self.snapshot(); self.maybeQuit()
        }
    }
    private func launch(_ operation: String, _ args: [String], timeout: TimeInterval,
                        completion: @escaping (JobResult) -> Void) {
        let token = UUID(); generation = token
        let job = JobRunner(); runner = job
        guard let resources = Bundle.main.resourceURL else { busy = false; error = "App resources are missing."; return }
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("Fingering Studio/Jobs/\(token.uuidString)")
        do { try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700]) }
        catch { busy = false; self.error = "The private job folder could not be created."; return }
        let log = base.appendingPathComponent("engine.log"); lastLog = log
        let env = ["PATH": "/usr/bin:/bin", "HOME": base.path, "CFFIXED_USER_HOME": base.path,
                   "TMPDIR": base.path + "/", "XDG_CACHE_HOME": base.path, "MPLCONFIGDIR": base.path,
                   "TORCH_HOME": base.path, "TORCH_DEVICE_BACKEND_AUTOLOAD": "0", "PYTHONNOUSERSITE": "1",
                   "LANG": "en_US.UTF-8", "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4",
                   "PIANO_HAND_POSE_HELPER": resources.appendingPathComponent("native/hand-pose").path,
                   "IMAGEIO_FFMPEG_EXE": resources.appendingPathComponent("runtime/lib/python3.11/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v9.0").path]
        job.run(executable: resources.appendingPathComponent("runtime/bin/python3.11"),
                arguments: ["-I", "-B", resources.appendingPathComponent("worker.py").path, operation] + args,
                environment: env, logURL: log, timeout: timeout, progress: { value in
            DispatchQueue.main.async {
                guard self.generation == token else { return }
                self.stage = value["stage"] as? Int ?? 0; self.status = value["label"] as? String ?? "Working locally…"
            }
        }, completion: { result in
            DispatchQueue.main.async {
                guard self.generation == token else { return }
                self.runner = nil; completion(result)
            }
        })
    }
    private func resultData(_ result: JobResult) -> [String: Any]? {
        guard result.cleanupConfirmed else {
            error = "Job cleanup could not be confirmed. Quit this window and make a recovery copy after the old job exits. Further project changes are blocked."
            leased = true; return nil
        }
        if result.cancelled { status = "Stopped. Your originals and previous result were kept."; return nil }
        if let problem = result.error { error = problem; return nil }
        if let e = result.messages.last(where: { $0["type"] as? String == "error" }) {
            error = e["message"] as? String ?? "This operation could not finish."; return nil
        }
        guard result.exitCode == 0, let d = result.messages.last(where: { $0["type"] as? String == "result" })?["data"] as? [String: Any] else {
            error = "The engine could not finish. Your originals and previous result were kept. You can reveal the private log for diagnosis."; return nil
        }
        return d
    }
    func choose(_ isVideo: Bool) {
        let p = NSOpenPanel(); p.canChooseDirectories = false; p.allowsMultipleSelection = false
        p.allowedContentTypes = isVideo ? [.movie] : [.pdf]
        p.message = isVideo ? "Choose a short recording with piano audio." : "Choose a supported, digitally typeset score."
        if p.runModal() == .OK, let u = p.url { accept(u) }
    }
    func accept(_ url: URL) {
        if !ready { pendingOpen = url; return }
        guard !busy else { return }
        if url.pathExtension == "fingeringproject" { open(url); return }
        if url.pathExtension.lowercased() == "pdf" { score = url }
        else if ["mov", "mp4", "m4v"].contains(url.pathExtension.lowercased()) { video = url }
        else { error = "Drop a MOV, MP4, PDF, or Fingering Studio project." }
    }
    func folder(_ message: String) -> URL? {
        let p = NSOpenPanel(); p.canChooseDirectories = true; p.canChooseFiles = false
        p.canCreateDirectories = true; p.message = message
        return p.runModal() == .OK ? p.url : nil
    }
    func create() {
        guard let v = video, let s = score, let parent = folder("Choose where to save your portable project. The app copies both originals into it.") else { return }
        status = "Checking the recording and score…"; stage = 0
        invoke("create", ["--video", v.path, "--score", s.path, "--destination", parent.path, "--name", projectName]) { data in
            self.apply(data); self.analyze()
        }
    }
    func chooseProject() {
        let p = NSOpenPanel(); p.canChooseFiles = true; p.canChooseDirectories = true; p.treatsFilePackagesAsDirectories = false
        p.message = "Open a .fingeringproject package."
        if p.runModal() == .OK, let u = p.url { open(u) }
    }
    func open(_ url: URL) {
        guard !busy else { return }; status = "Opening your project…"
        invoke("open", ["--project", url.path]) { self.apply($0); self.snapshot() }
    }
    func apply(_ d: [String: Any]) {
        if let path = d["project"] as? String {
            project = URL(fileURLWithPath: path); recents.removeAll { $0 == path }; recents.insert(path, at: 0)
            recents = Array(recents.prefix(8)); UserDefaults.standard.set(recents, forKey: "recentProjects")
        }
        projectName = d["name"] as? String ?? projectName
        hasResults = d["hasResults"] as? Bool ?? false; dirty = d["dirty"] as? Bool ?? false
        leased = d["busy"] as? Bool ?? false; revision = d["revision"] as? Int ?? 0; runID = d["runID"] as? String
        notes = (d["notes"] as? [[String: Any]] ?? []).compactMap(NoteRow.init)
        if let path = d["video"] as? String, player?.currentItem?.asset as? AVURLAsset == nil || (player?.currentItem?.asset as? AVURLAsset)?.url.path != path {
            player?.pause(); player = AVPlayer(url: URL(fileURLWithPath: path))
            playerObservation = player?.currentItem?.observe(\.status, options: [.new]) { item, _ in
                if item.status == .failed { DispatchQueue.main.async { guard self.player?.currentItem === item else { return }; self.error = "This saved video could not be played. Reanalyze to create a fresh result; your originals are preserved." } }
            }
        }
        scoreResult = (d["score"] as? String).map { URL(fileURLWithPath: $0) }
        if selected == nil || !notes.contains(where: { $0.id == selected }) { selected = notes.first?.id }
        select(selected)
        status = hasResults ? "Ready to review. Automatic fingerings are estimates." : "Your project is saved. Ready to analyze."
        if leased { error = "An earlier job has not been finalized. If its window is no longer running, make a recovery copy; this project will stay unchanged." }
        else if let message = d["lastError"] as? String { error = message }
    }
    func longJob(_ op: String, extra: [String] = []) {
        guard let p = project, !busy, !leased else { return }
        busy = true; stopping = false; error = nil; player?.pause(); stage = 0; startedAt = Date()
        status = op == "export" ? "Copying your finished files…" : "Preparing local analysis…"
        let jobID = UUID().uuidString.lowercased()
        launch(op, ["--project", p.path, "--job-id", jobID, "--expected-run", runID ?? "none", "--expected-revision", String(revision)] + extra, timeout: op == "analyze" ? 1800 : 600) { result in
            let originalData = self.resultData(result); let originalError = self.error
            guard result.cleanupConfirmed else { self.busy = false; self.maybeQuit(); return }
            let outcome = result.cancelled ? "cancelled" : (originalData == nil ? "failed" : "success")
            self.status = "Finishing safely…"
            self.launch("finalize", ["--project", p.path, "--job-id", jobID, "--outcome", outcome], timeout: 30) { finalized in
                self.busy = false; self.stopping = false
                if let data = self.resultData(finalized) { self.apply(data) }
                else { self.leased = true }
                if let originalError = originalError { self.error = originalError }
                if let exported = originalData?["exported"] as? String {
                    self.lastExport = URL(fileURLWithPath: exported); self.status = "Exported to \(URL(fileURLWithPath: exported).lastPathComponent)."
                    NSWorkspace.shared.activateFileViewerSelecting([self.lastExport!])
                }
                self.snapshot(); self.maybeQuit()
            }
        }
    }
    func analyze() { longJob("analyze") }
    func update() { longJob("render") }
    func stop() { stopping = true; status = "Stopping and cleaning up…"; runner?.cancel() }
    func select(_ id: String?) {
        selected = id
        if let note = selectedNote {
            if let time = note.time { player?.seek(to: CMTime(seconds: time, preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero) }
            correctionHand = ["L", "R"].contains(note.hand) ? note.hand : ""
            correctionFinger = ["1", "2", "3", "4", "5"].contains(note.finger) ? note.finger : ""
        }
    }
    func correct(_ mode: String) {
        guard let p = project, let r = runID, let n = selectedNote else { return }
        var args = ["--project", p.path, "--event", n.id, "--expected-run", r, "--expected-revision", String(revision)]
        if mode != "reset" { args += ["--hand", mode == "unknown" ? "unknown" : correctionHand, "--finger", mode == "unknown" ? "unknown" : correctionFinger] }
        invoke("correct", args) { self.apply($0) }
    }
    func export() {
        guard let parent = folder("Choose a folder. A new, dated export folder will be created inside it.") else { return }
        let formatter = DateFormatter(); formatter.dateFormat = "yyyy-MM-dd HH-mm-ss"
        longJob("export", extra: ["--destination", parent.path, "--name", projectName + " Export " + formatter.string(from: Date()), "--kinds", "video", "score", "excerpt", "notes"])
    }
    func recover() {
        guard let p = project, let parent = folder("Choose where to save a recovery copy. The original project stays untouched.") else { return }
        invoke("recover", ["--project", p.path, "--destination", parent.path, "--name", projectName + " recovered"]) { self.apply($0) }
    }
    func newProject() {
        guard !busy else { return }; player?.pause(); player = nil; project = nil; notes = []; selected = nil
        video = nil; score = nil; hasResults = false; dirty = false; leased = false; error = nil; status = "Everything runs on this Mac."
    }
    func requestQuit() -> NSApplication.TerminateReply {
        if busy { quitAfter = true; stop(); return .terminateLater }; return .terminateNow
    }
    private func maybeQuit() { if quitAfter && !busy { NSApp.reply(toApplicationShouldTerminate: true) } }
    func snapshot() {
        guard !busy, !capturePending, snapshotPath != nil || uiCheckPath != nil else { return }
        capturePending = true
        if uiState == "score" { tab = "Score" }
        if uiState == "unknown" { select(notes.first(where: { $0.tier == "unknown" })?.id) }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
            defer { self.capturePending = false }
            if let path = self.uiCheckPath {
                let state: [String: Any] = ["ready": self.ready, "busy": self.busy,
                    "hasResults": self.hasResults, "notes": self.notes.count,
                    "videoReady": self.player?.currentItem?.status == .readyToPlay,
                    "scoreReady": self.scoreResult.flatMap { PDFDocument(url: $0) } != nil,
                    "unknownIsUnset": self.selectedNote?.tier != "unknown" || (self.correctionHand.isEmpty && self.correctionFinger.isEmpty),
                    "error": self.error ?? NSNull()]
                if let data = try? JSONSerialization.data(withJSONObject: state, options: [.sortedKeys]) { try? data.write(to: URL(fileURLWithPath: path)) }
            }
            if let path = self.snapshotPath,
               let view = NSApp.windows.first(where: { $0.isVisible && $0.contentView != nil })?.contentView,
                  let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) {
            view.cacheDisplay(in: view.bounds, to: rep)
            if let data = rep.representation(using: .png, properties: [:]) { try? data.write(to: URL(fileURLWithPath: path)) }
            }
            if self.uiCheckPath != nil { NSApp.terminate(nil) }
        }
    }
}
