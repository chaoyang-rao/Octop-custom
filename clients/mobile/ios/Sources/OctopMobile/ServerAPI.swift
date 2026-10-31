import Foundation

struct PairedServer: Codable, Identifiable, Equatable {
    var id: String { fingerprint + ":" + deviceID }
    let baseURL: URL
    let deviceID: String
    let fingerprint: String
    let expiresAt: Int
    var scopes: [String]? = nil
    var locale: String? = nil
    var accountLabel: String? = nil
    func allows(_ scope: String) -> Bool { scopes?.contains(scope) ?? true }
}

struct PairingChallenge: Decodable {
    let pairingSecret: String
    let userCode: String
    let expiresAt: Int
    let hostFingerprint: String
    let interval: Int
    enum CodingKeys: String, CodingKey {
        case pairingSecret = "pairing_secret", userCode = "user_code", expiresAt = "expires_at"
        case hostFingerprint = "host_fingerprint", interval
    }
}

struct PairingResult: Decodable {
    let status: String
    let scopes: [String]?
    let accessToken: String?
    let deviceID: String?
    let hostFingerprint: String?
    let expiresAt: Int
    enum CodingKeys: String, CodingKey {
        case status, scopes, accessToken = "access_token", deviceID = "device_id"
        case hostFingerprint = "host_fingerprint", expiresAt = "expires_at"
    }
}

struct MobileClientError: LocalizedError {
    let message: String
    var statusCode: Int? = nil
    var errorDescription: String? { message }
}

final class ServerAPI: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    static let shared = ServerAPI()
    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.urlCache = nil
        config.timeoutIntervalForRequest = 20
        config.timeoutIntervalForResource = 30
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()

    static func validatedURL(_ text: String) throws -> URL {
        guard let parts = URLComponents(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              let host = parts.host, parts.user == nil, parts.password == nil,
              parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/",
              parts.scheme == "https" || (parts.scheme == "http" && ["localhost", "127.0.0.1", "::1", "[::1]"].contains(host)),
              let url = parts.url else {
            throw MobileClientError(message: L("native_enter_the_server_https_address"))
        }
        return url
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        // Credentials must never follow a server redirect to another origin.
        completionHandler(nil)
    }

    func request(base: URL, path: String, method: String = "POST", body: [String: Any]? = nil,
                 token: String? = nil) async throws -> Data {
        guard let url = URL(string: path, relativeTo: base)?.absoluteURL,
              url.scheme == base.scheme, url.host == base.host, url.port == base.port else {
            throw MobileClientError(message: L("native_invalid_server_path"))
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(NativeStrings.language, forHTTPHeaderField: "Accept-Language")
        if let token { request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization") }
        if let body { request.httpBody = try JSONSerialization.data(withJSONObject: body) }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            throw MobileClientError(message: code == 401 ? L("native_device_authorization_expired") : L("native_server_request_failed_0" , code), statusCode: code)
        }
        return data
    }

    func begin(base: URL, name: String) async throws -> PairingChallenge {
        let data = try await request(base: base, path: "/api/mobile-access/pairings/request", body: ["name": name, "platform": "ios"])
        return try JSONDecoder().decode(PairingChallenge.self, from: data)
    }

    func exchange(base: URL, challenge: PairingChallenge) async throws -> PairingResult {
        let data = try await request(base: base, path: "/api/mobile-access/pairings/exchange", body: ["pairing_secret": challenge.pairingSecret])
        return try JSONDecoder().decode(PairingResult.self, from: data)
    }
}


struct DeviceNotificationPreferences: Codable {
    var level = "all"
    var mutedUntil: Int? = nil
    var sound = true
    var preview = false
    var mutedAgentIDs: [String] = []
    var foreground = false
    enum CodingKeys: String, CodingKey {
        case level, mutedUntil = "muted_until", sound, preview
        case mutedAgentIDs = "muted_agent_ids", foreground
    }
    var body: [String: Any] {
        ["level": level, "muted_until": mutedUntil.map { $0 as Any } ?? NSNull(), "sound": sound,
         "preview": preview, "muted_agent_ids": mutedAgentIDs]
    }
}

struct DevicePreferenceEnvelope: Decodable {
    var notificationPreferences: DeviceNotificationPreferences
    enum CodingKeys: String, CodingKey { case notificationPreferences = "notification_preferences" }
}

struct MobileAgentLabel: Decodable, Identifiable {
    var agentID: String
    var name: String
    var id: String { agentID }
    enum CodingKeys: String, CodingKey { case agentID = "agent_id", name }
}

extension ServerAPI {
    func upload(base: URL, agentID: String, file: SharedFile, token: String) async throws -> [String: String] {
        guard agentID.range(of: "^[A-Za-z0-9_:-]+$", options: .regularExpression) != nil else { throw ShareStore.Failure.invalid }
        let boundary = "Octop-" + UUID().uuidString
        var request = URLRequest(url: URL(string: "/api/agents/\(agentID)/upload", relativeTo: base)!.absoluteURL)
        request.httpMethod = "POST"; request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        request.setValue("multipart/form-data; boundary=" + boundary, forHTTPHeaderField: "Content-Type")
        let safeName = file.filename.replacingOccurrences(of: "\"", with: "_").replacingOccurrences(of: "\r", with: "_").replacingOccurrences(of: "\n", with: "_")
        let mime = file.mime.range(of: "^[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+$", options: .regularExpression) != nil ? file.mime : "application/octet-stream"
        var body = Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(safeName)\"\r\nContent-Type: \(mime)\r\n\r\n".utf8)
        body.append(file.data); body.append(Data("\r\n--\(boundary)--\r\n".utf8)); request.httpBody = body
        let (response, status) = try await session.data(for: request)
        guard let http = status as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw MobileClientError(message: L("native_upload_failed_draft_retained")) }
        guard let value = try JSONSerialization.jsonObject(with: response) as? [String: Any] else { throw ShareStore.Failure.invalid }
        return value.compactMapValues { $0 as? String }
    }
}
