import AppKit
import Darwin
import Foundation

@MainActor
final class ManagedUpdater {
    private let dataHome = EngineRuntime.home.appendingPathComponent("Data", isDirectory: true)
    private let appRoot = Bundle.main.bundleURL.resolvingSymlinksInPath()
    private var helper: URL { appRoot.appendingPathComponent("Contents/Helpers/client-updater") }
    private(set) var installing = false
    func resumeAfterFailure() { installing = false }
    private let terminal: Set<String> = ["accepted", "rolled_back", "cancelled", "failed"]

    static func validID(_ id: String) -> Bool { id.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil }
    private func directory(_ id: String) throws -> URL {
        guard Self.validID(id) else { throw CompanionError.invalidPath }
        return dataHome.appendingPathComponent("client-updates/jobs/\(id)", isDirectory: true)
    }
    private func read(_ id: String) throws -> [String: Any] {
        let folder = try directory(id)
        for url in [folder, folder.deletingLastPathComponent(), folder.deletingLastPathComponent().deletingLastPathComponent()] {
            guard try url.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink != true else { throw CompanionError.invalidPath }
        }
        let file = folder.appendingPathComponent("job.json")
        let info = try file.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey, .isSymbolicLinkKey])
        guard info.isRegularFile == true, info.isSymbolicLink != true, (info.fileSize ?? Int.max) <= 1_000_000,
              let job = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any],
              job["id"] as? String == id, job["product"] as? String == "octop-companion",
              job["app_root"] as? String == appRoot.path, job["data_root"] as? String == dataHome.path else { throw CompanionError.invalidPath }
        return job
    }
    private func write(_ job: [String: Any]) throws {
        guard let id = job["id"] as? String else { throw CompanionError.invalidPath }
        try JSONSerialization.data(withJSONObject: job).write(to: directory(id).appendingPathComponent("job.json"), options: .atomic)
    }
    private func arguments(_ id: String) -> [String] { ["--home", dataHome.path, "--job", id, "--product", "octop-companion"] }
    private func validate(_ id: String, mode: String) async throws {
        let process = Process(); process.executableURL = helper; process.arguments = arguments(id) + [mode]
        process.standardOutput = FileHandle.nullDevice; process.standardError = FileHandle.nullDevice
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            process.terminationHandler = { child in
                if child.terminationStatus == 0 { continuation.resume() }
                else { continuation.resume(throwing: CompanionError.unavailable("桌宠更新签名或安装信息校验失败。")) }
            }
            do { try process.run() } catch { continuation.resume(throwing: error) }
        }
    }
    func start(id: String, backendPID: Int32) async throws {
        guard !installing else { throw CompanionError.unavailable("哆啦正在更新。") }
        var job = try read(id)
        try await validate(id, mode: "--validate")
        job["old_pid"] = ProcessInfo.processInfo.processIdentifier; job["old_backend_pid"] = backendPID
        try write(job)
        let copied = try directory(id).appendingPathComponent("Dora-updater")
        try? FileManager.default.removeItem(at: copied)
        try FileManager.default.copyItem(at: helper, to: copied)
        let child = Process(); child.executableURL = copied; child.arguments = arguments(id)
        child.standardOutput = FileHandle.nullDevice; child.standardError = FileHandle.nullDevice
        try child.run()
        let active: [String: Any] = ["job_id": id, "helper_pid": child.processIdentifier]
        do { try JSONSerialization.data(withJSONObject: active).write(to: dataHome.appendingPathComponent("client-updates/active.json"), options: .atomic) }
        catch { child.terminate(); throw error }
        installing = true
    }
    func monitor(id: String, progress: (String) -> Void) async throws -> String {
        while true {
            let job = try read(id), phase = job["phase"] as? String ?? "failed"
            progress(phase)
            if phase == "ready_to_swap" || terminal.contains(phase) { return phase }
            try await Task.sleep(nanoseconds: 250_000_000)
        }
    }
    func initialize(engine: EngineRuntime) async throws -> Bool {
        let args = ProcessInfo.processInfo.arguments
        if let index = args.firstIndex(of: "--managed-client-update") {
            guard index + 1 < args.count else { throw CompanionError.invalidPath }
            let id = args[index + 1]
            var job = try read(id)
            if ["accepted", "rolled_back", "cancelled"].contains(job["phase"] as? String ?? "") { return true }
            try await validate(id, mode: "--candidate")
            job["candidate_pid"] = ProcessInfo.processInfo.processIdentifier; try write(job)
            engine.pendingUpdateID = id
            engine.onSpawn = { [weak self] pid in job["backend_pid"] = pid; try self?.write(job) }
            let origin = try await engine.start()
            job["candidate_base"] = origin.absoluteString; job["phase"] = "candidate_ready"; try write(job)
            for _ in 0..<960 {
                let current = try read(id), phase = current["phase"] as? String ?? "failed"
                if phase == "accepted" { engine.pendingUpdateID = nil; engine.onSpawn = nil; return true }
                if ["failed", "rolling_back", "rolled_back"].contains(phase) { throw CompanionError.unavailable("桌宠更新未通过启动验证。") }
                try await Task.sleep(nanoseconds: 250_000_000)
            }
            throw CompanionError.unavailable("桌宠更新验证超时。")
        }
        let activeURL = dataHome.appendingPathComponent("client-updates/active.json")
        guard FileManager.default.fileExists(atPath: activeURL.path) else { return true }
        guard let active = try JSONSerialization.jsonObject(with: Data(contentsOf: activeURL)) as? [String: Any], let id = active["job_id"] as? String else { throw CompanionError.invalidPath }
        let job = try read(id), phase = job["phase"] as? String ?? "failed"
        if terminal.contains(phase) && job["error_code"] as? String != "CLIENT_UPDATE_RECOVERY_REQUIRED" { return true }
        if let pid = active["helper_pid"] as? Int32, pid > 0, kill(pid, 0) == 0 { return false }
        guard job["backup_ready"] as? Bool == true else { return true }
        let child = Process(); child.executableURL = helper
        child.arguments = arguments(id) + ["--recover", "--wait-pid", String(ProcessInfo.processInfo.processIdentifier)]
        try child.run(); return false
    }
}
