// CLI harness for the same owned-child supervisor used by the app. Output is private.
import Foundation
import Darwin

@main struct WorkerHarness {
    static func main() throws {
        let arguments = Array(CommandLine.arguments.dropFirst())
        guard arguments.count >= 3 else { fatalError("Usage: harness Resources private-job-folder operation [arguments]") }
        let resources = URL(fileURLWithPath: arguments[0])
        let base = URL(fileURLWithPath: arguments[1])
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let env = ["PATH": "/usr/bin:/bin", "HOME": base.path, "CFFIXED_USER_HOME": base.path,
                   "TMPDIR": base.path + "/", "XDG_CACHE_HOME": base.path, "MPLCONFIGDIR": base.path,
                   "TORCH_HOME": base.path, "TORCH_DEVICE_BACKEND_AUTOLOAD": "0", "LANG": "en_US.UTF-8",
                   "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4",
                   "PIANO_HAND_POSE_HELPER": resources.appendingPathComponent("native/hand-pose").path,
                   "IMAGEIO_FFMPEG_EXE": resources.appendingPathComponent("runtime/lib/python3.11/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v9.0").path]
        let runner = JobRunner(); let done = DispatchSemaphore(value: 0)
        var result: JobResult?
        runner.run(executable: resources.appendingPathComponent("runtime/bin/python3.11"),
                   arguments: ["-I", "-B", resources.appendingPathComponent("worker.py").path] + Array(arguments.dropFirst(2)),
                   environment: env, logURL: base.appendingPathComponent("engine.log"), timeout: 1800,
                   progress: { value in
            let data = try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
            FileHandle.standardOutput.write(data + Data([10]))
        }, completion: { value in result = value; done.signal() })
        if let raw = ProcessInfo.processInfo.environment["STUDIO_TEST_CANCEL_AFTER"], let seconds = Double(raw) {
            DispatchQueue.global().asyncAfter(deadline: .now() + seconds) { runner.cancel() }
        }
        guard done.wait(timeout: .now() + 1820) == .success, let r = result else { exit(10) }
        let value: [String: Any] = ["exitCode": r.exitCode, "cancelled": r.cancelled,
            "cleanupConfirmed": r.cleanupConfirmed, "messages": r.messages, "supervisorError": r.error ?? NSNull()]
        FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) + Data([10]))
        exit(r.cleanupConfirmed ? 0 : 11)
    }
}
