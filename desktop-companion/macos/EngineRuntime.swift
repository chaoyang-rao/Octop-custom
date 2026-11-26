import AppKit
import CryptoKit
import Darwin
import Foundation

private struct EngineArchive: Decodable { let file: String; let sha256: String; let root: String }
private struct EngineManifest: Decodable { let architectures: [String: EngineArchive]; let authority: String }

/// Owns only this application's child engine and private Application Support data.
@MainActor
final class EngineRuntime {
    private var process: Process?
    private var parentPipe: Pipe?
    private var starting: Task<URL, Error>?
    private(set) var origin: URL?
    private var logHandle: FileHandle?
    var pendingUpdateID: String?
    var onSpawn: ((Int32) throws -> Void)?
    var processIdentifier: Int32? { process?.processIdentifier }
    private let dataName: String
    init(dataName: String = "Data") { precondition(["Data", "Acceptance"].contains(dataName)); self.dataName = dataName }

    static var home: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("OctopCompanion", isDirectory: true)
    }
    func start() async throws -> URL {
        if let origin, process?.isRunning == true { return origin }
        if let starting { return try await starting.value }
        let task = Task { try await launch() }; starting = task
        do { let result = try await task.value; starting = nil; return result }
        catch { stop(); starting = nil; throw error }
    }
    private func launch() async throws -> URL {
        let fm = FileManager.default
        let resources = Bundle.main.resourceURL!
        let archiveRoot = resources.appendingPathComponent("Engine")
        let manifest = try JSONDecoder().decode(EngineManifest.self, from: Data(contentsOf: archiveRoot.appendingPathComponent("manifest.json")))
        #if arch(arm64)
        let architecture = "arm64"
        #else
        let architecture = "x86_64"
        #endif
        guard let info = manifest.architectures[architecture], info.file == (info.file as NSString).lastPathComponent,
              info.root == (info.root as NSString).lastPathComponent,
              info.sha256.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else {
            throw CompanionError.unavailable("安装包缺少当前芯片对应的问答引擎，请重新安装桌宠。")
        }
        let support = Self.home
        try fm.createDirectory(at: support, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let cache = support.appendingPathComponent("Engines/\(info.sha256.prefix(16))-\(architecture)", isDirectory: true)
        let runtime = cache.appendingPathComponent(info.root, isDirectory: true)
        let python = runtime.appendingPathComponent("runtime/bin/python3")
        let marker = cache.appendingPathComponent("verified.sha256")
        if (try? String(contentsOf: marker, encoding: .utf8)) != info.sha256 || !fm.isExecutableFile(atPath: python.path) {
            let archive = archiveRoot.appendingPathComponent(info.file)
            let data = try Data(contentsOf: archive, options: .mappedIfSafe)
            let actual = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
            guard actual == info.sha256 else { throw CompanionError.unavailable("问答引擎安装文件校验失败，请重新下载桌宠安装包。") }
            let staging = support.appendingPathComponent("Engines/install-\(UUID().uuidString)", isDirectory: true)
            try fm.createDirectory(at: staging, withIntermediateDirectories: true)
            do {
                let unpack = Process(); unpack.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
                unpack.arguments = ["-x", "-k", archive.path, staging.path]
                try await run(unpack)
                guard fm.isExecutableFile(atPath: staging.appendingPathComponent(info.root + "/runtime/bin/python3").path) else { throw CompanionError.unavailable("问答引擎解压未完成。") }
                // A content-addressed cache is app-owned code, never the data directory.
                if fm.fileExists(atPath: cache.path) { try fm.removeItem(at: cache) }
                try fm.moveItem(at: staging, to: cache)
                try info.sha256.write(to: marker, atomically: true, encoding: .utf8)
            } catch { try? fm.removeItem(at: staging); throw error }
        }
        let dataHome = support.appendingPathComponent(dataName, isDirectory: true)
        try fm.createDirectory(at: dataHome, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let logs = support.appendingPathComponent("Logs", isDirectory: true)
        try fm.createDirectory(at: logs, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let log = logs.appendingPathComponent("engine.log")
        if !fm.fileExists(atPath: log.path) { fm.createFile(atPath: log.path, contents: nil, attributes: [.posixPermissions: 0o600]) }
        logHandle = try FileHandle(forWritingTo: log); try logHandle?.seekToEnd()
        let port = try await freePort(preferred: UserDefaults.standard.integer(forKey: "enginePort-" + dataName))
        let instance = UUID().uuidString
        let child = Process()
        child.executableURL = python
        child.arguments = [resources.appendingPathComponent("engine_entry.py").path, runtime.path, "run", "--host", "127.0.0.1", "--port", String(port)]
        child.currentDirectoryURL = dataHome
        var env = ProcessInfo.processInfo.environment.filter { key, _ in
            !key.hasPrefix("OCTOP_") && !key.hasPrefix("PYTHON") && !key.hasPrefix("DYLD_") && key != "VIRTUAL_ENV"
        }
        env["OCTOP_HOME"] = dataHome.path
        env["OCTOP_GREEN_PACKAGES"] = runtime.appendingPathComponent("packages").path
        env["OCTOP_CUSTOM_BUILD"] = "1"; env["OCTOP_COMPANION_MODE"] = "1"
        env["OCTOP_COMPANION_INSTANCE"] = instance
        env["OCTOP_ENTERPRISE_AUTHORITY_URL"] = manifest.authority
        if let build = try? JSONSerialization.jsonObject(with: Data(contentsOf: resources.appendingPathComponent("client-update-build.json"))) as? [String: Any],
           build["product"] as? String == "octop-companion", build["protocol"] as? Int == 1,
           build["authority"] as? String == manifest.authority, let version = build["version"] as? String {
            env["OCTOP_DESKTOP_CLIENT_PRODUCT"] = "octop-companion"; env["OCTOP_DESKTOP_CLIENT_VERSION"] = version
            env["OCTOP_DESKTOP_UPDATER_PROTOCOL"] = "1"; env["OCTOP_DESKTOP_PROGRAM_ROOT"] = Bundle.main.bundleURL.resolvingSymlinksInPath().path
            if let pendingUpdateID { env["OCTOP_CLIENT_UPDATE_PENDING"] = pendingUpdateID }
        }
        env["PYTHONNOUSERSITE"] = "1"; env["PYTHONDONTWRITEBYTECODE"] = "1"
        child.environment = env; child.standardOutput = logHandle; child.standardError = logHandle
        let pipe = Pipe(); parentPipe = pipe; child.standardInput = pipe
        try child.run(); process = child
        try onSpawn?(child.processIdentifier)
        let candidate = URL(string: "http://127.0.0.1:\(port)")!
        let checker = BackendClient(origin: candidate)
        for _ in 0..<150 {
            guard child.isRunning else { throw CompanionError.unavailable("问答引擎启动失败，请在桌宠菜单查看运行日志。") }
            if let result = try? await checker.request("/api/health/companion", authenticated: false), result.1.statusCode == 200,
               let identity = try? JSONSerialization.jsonObject(with: result.0) as? [String: Any], identity["instance"] as? String == instance, identity["companion"] as? Bool == true {
                origin = candidate; UserDefaults.standard.set(port, forKey: "enginePort-" + dataName); return candidate
            }
            try await Task.sleep(nanoseconds: 400_000_000)
        }
        throw CompanionError.unavailable("问答引擎启动超时，请查看桌宠运行日志后重试。")
    }
    private func run(_ child: Process) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            child.terminationHandler = { process in
                if process.terminationStatus == 0 { continuation.resume() }
                else { continuation.resume(throwing: CompanionError.unavailable("问答引擎文件解压失败。")) }
            }
            do { try child.run() } catch { child.terminationHandler = nil; continuation.resume(throwing: error) }
        }
    }
    private func freePort(preferred: Int) async throws -> Int {
        let saved = (1025...65535).contains(preferred) ? preferred : 18588
        for attempt in 0..<12 {
            let port = attempt < 10 ? saved : 0
            let socketFD = socket(AF_INET, SOCK_STREAM, 0)
            guard socketFD >= 0 else { continue }
            defer { Darwin.close(socketFD) }
            var reuse: Int32 = 1
            _ = setsockopt(socketFD, SOL_SOCKET, SO_REUSEADDR, &reuse, socklen_t(MemoryLayout<Int32>.size))
            var address = sockaddr_in(); address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
            address.sin_family = sa_family_t(AF_INET); address.sin_port = UInt16(port).bigEndian
            address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))
            let bound = withUnsafePointer(to: &address) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.bind(socketFD, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) } }
            if bound == 0 {
                var length = socklen_t(MemoryLayout<sockaddr_in>.size)
                _ = withUnsafeMutablePointer(to: &address) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(socketFD, $0, &length) } }
                return Int(UInt16(bigEndian: address.sin_port))
            }
            // A prior app-owned child may still be completing shutdown. Keep
            // the origin stable so its normal WebKit login session survives.
            try await Task.sleep(nanoseconds: 150_000_000)
        }
        throw CompanionError.unavailable("无法为桌宠启动本机问答端口。")
    }
    func stop() {
        parentPipe?.fileHandleForWriting.closeFile(); parentPipe = nil
        if let process, process.isRunning { process.terminate() }
        self.process = nil; origin = nil
        try? logHandle?.close(); logHandle = nil
    }
}
