import Foundation
import Darwin

let python = CommandLine.arguments[1]
let root = FileManager.default.temporaryDirectory.appendingPathComponent("studio-supervisor-\(UUID().uuidString)")
try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
defer { try? FileManager.default.removeItem(at: root) }
func check(_ name: String, _ code: String, cancel: Double? = nil, timeout: Double = 5, success: Bool = true, executable: String? = nil) {
    let job = JobRunner(); let done = DispatchSemaphore(value: 0)
    var result: JobResult?
    job.run(executable: URL(fileURLWithPath: executable ?? python), arguments: ["-I", "-c", code],
            environment: ["PATH": "/usr/bin:/bin"], logURL: root.appendingPathComponent(name + ".log"), timeout: timeout,
            progress: { _ in }, completion: { result = $0; done.signal() })
    if let delay = cancel { DispatchQueue.global().asyncAfter(deadline: .now() + delay) { job.cancel() } }
    precondition(done.wait(timeout: .now() + 15) == .success, "\(name): supervisor hung")
    let r = result!
    precondition(r.cleanupConfirmed, "\(name): descendants or ownership remain")
    if success { precondition(r.exitCode == 0 && r.error == nil, "\(name): \(r.error ?? String(r.exitCode))") }
    if cancel != nil { precondition(r.cancelled, "\(name): cancellation lost") }
    print("PASS \(name)")
}
check("normal", "print('{\"protocol\":1,\"type\":\"result\",\"data\":{}}')")
check("pre-start-cancel", "import time; time.sleep(5)", cancel: 0, success: false)
check("ignore-term-and-descendant", """
import os, signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
if os.fork() == 0:
    while True: time.sleep(.1)
while True: time.sleep(.1)
""", cancel: 0.2, success: false)
check("normal-exit-descendant-holds-pipes", """
import os, signal, time
if os.fork() == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True: time.sleep(.1)
""")
check("saturated-pipes", "import os\nwhile True: os.write(1,b'x'*65536); os.write(2,b'y'*65536)", cancel: 0.15, success: false)
check("timeout", "import time; time.sleep(10)", timeout: 0.1, success: false)
check("bad-spawn", "", success: false, executable: "/no-such-studio-test-executable")
print("All supervisor ownership and cancellation checks passed.")
