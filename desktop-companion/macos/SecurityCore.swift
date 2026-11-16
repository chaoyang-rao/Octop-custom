import Foundation

enum CompanionError: LocalizedError {
    case invalidOrigin, invalidPath, signedOut, unavailable(String)
    var errorDescription: String? {
        switch self {
        case .invalidOrigin: return "请输入本机 Octop 地址，例如 http://127.0.0.1:8088。"
        case .invalidPath: return "这个链接不属于本机 Octop。"
        case .signedOut: return "请先使用企业飞书登录桌宠。"
        case .unavailable(let message): return message
        }
    }
}

enum EndpointPolicy {
    static func origin(_ value: String) throws -> URL {
        guard let parts = URLComponents(string: value.trimmingCharacters(in: .whitespacesAndNewlines)),
              ["http", "https"].contains(parts.scheme?.lowercased() ?? ""),
              let host = parts.host?.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "[]")),
              ["localhost", "127.0.0.1", "::1"].contains(host),
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/",
              parts.port == nil || (1...65535).contains(parts.port!),
              let result = parts.url else { throw CompanionError.invalidOrigin }
        return URL(string: result.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")))!
    }
    static func sameOrigin(_ first: URL, _ second: URL) -> Bool {
        func scheme(_ url: URL) -> String { url.scheme == "ws" ? "http" : url.scheme == "wss" ? "https" : url.scheme ?? "" }
        func port(_ url: URL) -> Int { url.port ?? (scheme(url) == "https" ? 443 : 80) }
        return scheme(first) == scheme(second) && first.host?.lowercased() == second.host?.lowercased() && port(first) == port(second)
    }
    static func api(_ path: String, origin: URL) throws -> URL {
        var decoded = path
        for _ in 0..<3 { decoded = decoded.removingPercentEncoding ?? decoded }
        guard decoded.hasPrefix("/api/"), !decoded.contains("\\"), !decoded.contains("\0"), !decoded.contains("//"),
              !decoded.components(separatedBy: "?")[0].split(separator: "/").contains(".."),
              let result = URL(string: path, relativeTo: origin)?.absoluteURL,
              sameOrigin(result, origin), result.path.hasPrefix("/api/") else { throw CompanionError.invalidPath }
        return result
    }
    static func segment(_ value: String) throws -> String {
        guard !value.isEmpty, value.count <= 160,
              value.range(of: "^[A-Za-z0-9_-]+$", options: .regularExpression) != nil else { throw CompanionError.invalidPath }
        return value
    }
}

final class CredentialStore {
    // Local preview builds are ad-hoc signed. Rebuilding changes their identity
    // and prompts for access to old Keychain items. Keep only this process's
    // normally authenticated sessions; never touch or delete those old items.
    private let lock = NSLock()
    private var sessions: [String: String] = [:]
    func read(origin: URL) -> String? {
        lock.lock(); defer { lock.unlock() }
        return sessions[origin.absoluteString]
    }
    func save(_ token: String, origin: URL) throws {
        guard !token.isEmpty else { throw CompanionError.signedOut }
        lock.lock(); defer { lock.unlock() }
        sessions[origin.absoluteString] = token
    }
    func clear(origin: URL) {
        lock.lock(); defer { lock.unlock() }
        sessions.removeValue(forKey: origin.absoluteString)
    }
}

enum CompanionLaunchAction: String {
    case open, size

    init?(url: URL) {
        guard url.scheme?.lowercased() == "octop-companion", url.user == nil,
              url.password == nil, url.port == nil, url.query == nil,
              url.fragment == nil, url.path.isEmpty || url.path == "/",
              let host = url.host, let action = Self(rawValue: host) else { return nil }
        self = action
    }
}
