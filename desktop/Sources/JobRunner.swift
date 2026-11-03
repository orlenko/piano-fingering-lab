import Foundation
import Darwin

struct JobResult {
    var messages: [[String: Any]]
    var exitCode: Int32
    var cancelled: Bool
    var cleanupConfirmed: Bool
    var logURL: URL
    var error: String?
}

// Sole owner and reaper of each child. Never signal a PID recovered from disk.
final class JobRunner {
    private let lock = NSLock()
    private var stopped = false
    func cancel() { lock.lock(); stopped = true; lock.unlock() }
    private var cancelled: Bool { lock.lock(); defer { lock.unlock() }; return stopped }

    func run(executable: URL, arguments: [String], environment: [String: String],
             logURL: URL, timeout: TimeInterval,
             progress: @escaping ([String: Any]) -> Void,
             completion: @escaping (JobResult) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            var out: [Int32] = [0, 0], err: [Int32] = [0, 0]
            var messages = [[String: Any]](), problem: String?
            let logFD = open(logURL.path, O_CREAT | O_WRONLY | O_TRUNC | O_NOFOLLOW, 0o600)
            guard logFD >= 0 else {
                completion(JobResult(messages: [], exitCode: -1, cancelled: self.cancelled,
                                     cleanupConfirmed: true, logURL: logURL, error: "Could not create a private job log.")); return
            }
            guard pipe(&out) == 0 else {
                close(logFD)
                completion(JobResult(messages: [], exitCode: -1, cancelled: self.cancelled,
                                     cleanupConfirmed: true, logURL: logURL, error: "Could not create a job pipe.")); return
            }
            guard pipe(&err) == 0 else {
                close(out[0]); close(out[1])
                if logFD >= 0 { close(logFD) }
                completion(JobResult(messages: [], exitCode: -1, cancelled: self.cancelled,
                                     cleanupConfirmed: true, logURL: logURL, error: "Could not create a private job log or pipe.")); return
            }
            defer { close(logFD); close(out[0]); close(err[0]) }
            var actions: posix_spawn_file_actions_t?
            var attributes: posix_spawnattr_t?
            guard posix_spawn_file_actions_init(&actions) == 0 else {
                close(out[1]); close(err[1])
                completion(JobResult(messages: [], exitCode: -1, cancelled: self.cancelled,
                                     cleanupConfirmed: true, logURL: logURL, error: "Could not initialize child file actions.")); return
            }
            guard posix_spawnattr_init(&attributes) == 0 else {
                posix_spawn_file_actions_destroy(&actions); close(out[1]); close(err[1])
                completion(JobResult(messages: [], exitCode: -1, cancelled: self.cancelled,
                                     cleanupConfirmed: true, logURL: logURL, error: "Could not initialize child ownership.")); return
            }
            defer { posix_spawn_file_actions_destroy(&actions); posix_spawnattr_destroy(&attributes) }
            var setup = [posix_spawn_file_actions_adddup2(&actions, out[1], STDOUT_FILENO),
                         posix_spawn_file_actions_adddup2(&actions, err[1], STDERR_FILENO),
                         posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0)]
            for fd in out + err { setup.append(posix_spawn_file_actions_addclose(&actions, fd)) }
            setup.append(posix_spawnattr_setpgroup(&attributes, 0))
            setup.append(posix_spawnattr_setflags(&attributes, Int16(POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_CLOEXEC_DEFAULT)))
            guard setup.allSatisfy({ $0 == 0 }),
                  fcntl(out[0], F_SETFL, O_NONBLOCK) == 0, fcntl(err[0], F_SETFL, O_NONBLOCK) == 0 else {
                close(out[1]); close(err[1])
                completion(JobResult(messages: [], exitCode: -1, cancelled: self.cancelled,
                                     cleanupConfirmed: true, logURL: logURL, error: "Child ownership or nonblocking pipes could not be configured.")); return
            }
            let argv = ([executable.path] + arguments).map { strdup($0) } + [nil]
            let envp = environment.sorted { $0.key < $1.key }.map { strdup("\($0.key)=\($0.value)") } + [nil]
            defer { for p in argv { if let p = p { free(p) } }; for p in envp { if let p = p { free(p) } } }
            var pid: pid_t = 0
            let spawnError = argv.withUnsafeBufferPointer { av in envp.withUnsafeBufferPointer { ev in
                posix_spawn(&pid, executable.path, &actions, &attributes, av.baseAddress!, ev.baseAddress!)
            } }
            close(out[1]); close(err[1])
            guard spawnError == 0 else {
                completion(JobResult(messages: [], exitCode: spawnError, cancelled: self.cancelled,
                                     cleanupConfirmed: true, logURL: logURL, error: "The bundled analysis engine could not start.")); return
            }
            let start = Date()
            var pending = Data(), total = 0, logBytes = 0, leaderExited = false
            var stoppingAt: Date?, killed = false, status: Int32 = 0
            func drain(_ fd: Int32, isOutput: Bool) {
                var bytes = [UInt8](repeating: 0, count: 16384)
                // Bounded work per loop: a noisy child must not starve cancellation.
                for _ in 0..<32 {
                    let count = read(fd, &bytes, bytes.count)
                    if count <= 0 { break }
                    let data = Data(bytes.prefix(count))
                    if !isOutput {
                        let remaining = max(0, 2 * 1024 * 1024 - logBytes)
                        if remaining > 0 { let part = data.prefix(remaining); part.withUnsafeBytes { _ = write(logFD, $0.baseAddress, part.count) }; logBytes += part.count }
                        continue
                    }
                    total += count
                    if total > 16 * 1024 * 1024 { problem = "The engine exceeded the response limit."; continue }
                    pending.append(data)
                    while let end = pending.firstIndex(of: 10) {
                        let line = pending.prefix(upTo: end); pending.removeSubrange(...end)
                        if line.count > 4 * 1024 * 1024 { problem = "The engine returned an oversized response."; continue }
                        if let value = try? JSONSerialization.jsonObject(with: line) as? [String: Any], value["protocol"] as? Int == 1 {
                            if value["type"] as? String == "progress" { progress(value) }
                            else if messages.count < 16 { messages.append(value) }
                            else { problem = "The engine returned too many responses." }
                        } else if !line.isEmpty { problem = "The engine returned an invalid response." }
                    }
                    if pending.count > 4 * 1024 * 1024 { pending.removeAll(); problem = "The engine returned an oversized response." }
                }
            }
            while true {
                drain(out[0], isOutput: true); drain(err[0], isOutput: false)
                var info = siginfo_t()
                let waited = waitid(P_PID, id_t(pid), &info, WEXITED | WNOHANG | WNOWAIT)
                if waited == 0 && info.si_pid == pid { leaderExited = true }
                if waited != 0 && errno != EINTR { problem = "Child ownership could not be verified."; break }
                let timedOut = Date().timeIntervalSince(start) > timeout
                if timedOut { problem = "This operation reached its time limit. Previous results were kept." }
                if (self.cancelled || problem != nil || leaderExited) && stoppingAt == nil {
                    stoppingAt = Date(); _ = killpg(pid, SIGTERM)
                }
                if let stop = stoppingAt, Date().timeIntervalSince(stop) > 0.4 && !killed {
                    // Leader is still unreaped, so the process-group identity cannot be reused.
                    _ = killpg(pid, SIGKILL); killed = true
                }
                if leaderExited && killed { break }
                if let stop = stoppingAt, Date().timeIntervalSince(stop) > 4 {
                    problem = "Child cleanup could not be confirmed within the safety deadline."
                    break
                }
                Thread.sleep(forTimeInterval: 0.02)
            }
            var reaped = false
            if leaderExited {
                while true {
                    let r = waitpid(pid, &status, 0)
                    if r == pid { reaped = true; break }
                    if r < 0 && errno == EINTR { continue }; break
                }
            } else {
                // Preserve a sole owner/reaper if an uninterruptible child has not exited.
                // It sends no more signals and never makes project writes.
                let ownedPID = pid
                DispatchQueue.global(qos: .utility).async {
                    var eventualStatus: Int32 = 0
                    while waitpid(ownedPID, &eventualStatus, 0) < 0 && errno == EINTR {}
                }
            }
            // No signals after reaping. Observe disappearance, including inherited pipes.
            let deadline = Date().addingTimeInterval(2)
            var gone = false
            while Date() < deadline {
                drain(out[0], isOutput: true); drain(err[0], isOutput: false)
                if killpg(pid, 0) != 0 && errno == ESRCH { gone = true; break }
                Thread.sleep(forTimeInterval: 0.02)
            }
            if !pending.isEmpty { problem = "The engine response ended unexpectedly." }
            let code: Int32 = status & 0x7f == 0 ? (status >> 8) & 0xff : 128 + (status & 0x7f)
            completion(JobResult(messages: messages, exitCode: code, cancelled: self.cancelled,
                                 cleanupConfirmed: reaped && gone, logURL: logURL, error: problem))
        }
    }
}
