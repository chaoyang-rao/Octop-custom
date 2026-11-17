import Foundation
import CFNetwork

final class BackendClient: NSObject, URLSessionTaskDelegate {
    var origin: URL
    let credentials = CredentialStore()
    var onExpired: ((URL) -> Void)?
    private var transport: URLSession!
    init(origin: URL) {
        self.origin = origin
        super.init()
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 55
        config.httpShouldSetCookies = false
        config.urlCache = nil
        // This session serves loopback origins only. Never send a local bearer
        // through a machine-wide VPN/HTTP/SOCKS proxy.
        config.connectionProxyDictionary = [
            kCFNetworkProxiesHTTPEnable as String: false,
            kCFNetworkProxiesHTTPSEnable as String: false,
            kCFNetworkProxiesSOCKSEnable as String: false,
            kCFNetworkProxiesProxyAutoConfigEnable as String: false,
            kCFNetworkProxiesProxyAutoDiscoveryEnable as String: false,
        ]
        transport = URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        guard let target = request.url, EndpointPolicy.sameOrigin(target, origin) else { completionHandler(nil); return }
        completionHandler(request)
    }
    func request(_ path: String, method: String = "GET", body: Data? = nil, contentType: String? = nil, token override: String? = nil, authenticated: Bool = true) async throws -> (Data, HTTPURLResponse) {
        let requestOrigin = origin
        var request = URLRequest(url: try EndpointPolicy.api(path, origin: requestOrigin))
        var sentToken: String?
        request.httpMethod = method; request.httpBody = body
        if let contentType { request.setValue(contentType, forHTTPHeaderField: "Content-Type") }
        if authenticated {
            guard let token = override ?? credentials.read(origin: requestOrigin) else { throw CompanionError.signedOut }
            sentToken = token
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await transport.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw CompanionError.unavailable("Octop 返回了无法识别的响应。") }
        guard EndpointPolicy.sameOrigin(response.url ?? requestOrigin, requestOrigin) else { throw CompanionError.invalidPath }
        // A delayed response from the previous account must not clear or renew
        // the token of an account that has since signed in on this origin.
        if authenticated && override == nil && requestOrigin == origin && credentials.read(origin: requestOrigin) == sentToken {
            if response.statusCode == 401 {
                credentials.clear(origin: requestOrigin)
                DispatchQueue.main.async {
                    guard self.origin == requestOrigin, self.credentials.read(origin: requestOrigin) == nil else { return }
                    self.onExpired?(requestOrigin)
                }
            }
            if (200..<300).contains(response.statusCode), let renewed = response.value(forHTTPHeaderField: "X-Octop-Access-Token") { try credentials.save(renewed, origin: requestOrigin) }
        }
        return (data, response)
    }
    func user(token: String? = nil) async throws -> [String: Any] {
        let (data, response) = try await request("/api/auth/me", token: token)
        guard response.statusCode == 200, let result = try JSONSerialization.jsonObject(with: data) as? [String: Any], result["id"] != nil else { throw CompanionError.signedOut }
        // Never forward credential-shaped fields to the mini client.
        return result.filter { ["id", "username", "display_name", "role", "locale"].contains($0.key) }
    }
    func json(_ path: String) async throws -> [String: Any] {
        let (data, response) = try await request(path)
        let value = (try? JSONSerialization.jsonObject(with: data, options: [.fragmentsAllowed])) ?? ["detail": "Octop 暂时没有返回可用内容。"]
        return ["status": response.statusCode, "data": value]
    }
    private func teamData(_ path:String) async throws -> [String:Any] {
        let value=try await json(path)
        guard value["status"] as? Int == 200, let data=value["data"] as? [String:Any] else {throw CompanionError.unavailable("团队信息暂不可用，请刷新核对。")}
        return data
    }
    private func companionIDs() async throws -> Set<String> {
        let value=try await json("/api/companion/agents")
        guard value["status"] as? Int == 200, let rows=value["data"] as? [[String:Any]] else {throw CompanionError.unavailable("当前专家授权无法确认，请重新登录或刷新。")}
        return Set(rows.compactMap {$0["agent_id"] as? String})
    }
    func validateTeam(_ teamId:String) async throws {
        let id=try EndpointPolicy.segment(teamId), record=try await teamData("/api/teams/\(id)"), allowed=try await companionIDs()
        guard let primary=record["primary_agent_id"] as? String, record["primary_agent_name"] as? String == "小通",
              let members=record["member_ids"] as? [String], Set(members).count >= 2, members.contains(primary),
              allowed.contains(id), members.allSatisfy({allowed.contains($0)}) else {throw CompanionError.unavailable("团队须由已开放的小通主持，所有成员也须当前可用。请刷新核对。")}
        let host=try await teamData("/api/agents/\(try EndpointPolicy.segment(primary))")
        guard host["name"] as? String == "小通", host["is_team_primary"] as? Bool == true else {throw CompanionError.unavailable("小通主持配置已变化，请先核对主专家。")}
    }
    func saveTeam(name:String,members:[String],hostId:String,teamId:String?) async throws -> [String:Any] {
        let host=try EndpointPolicy.segment(hostId), available=try await companionIDs()
        let primary=try await teamData("/api/agents/\(host)")
        guard available.contains(host), primary["name"] as? String == "小通", primary["is_team_primary"] as? Bool == true else {throw CompanionError.unavailable("请先恢复本人已开放的小通主专家，再创建或编辑团队。")}
        var seen:Set<String>=[]
        let ids=try members.map {try EndpointPolicy.segment($0)}.filter {$0 != host && seen.insert($0).inserted}
        guard !name.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty, !ids.isEmpty, ids.allSatisfy({available.contains($0)}) else {throw CompanionError.unavailable("请填写团队名称，并至少选择一位当前可用专家。")}
        let path=try teamId.map {"/api/teams/\(try EndpointPolicy.segment($0))"} ?? "/api/teams"
        if let teamId {
            let record=try await teamData("/api/teams/\(try EndpointPolicy.segment(teamId))")
            guard record["primary_agent_id"] as? String == host, record["primary_agent_name"] as? String == "小通" else {throw CompanionError.unavailable("这个团队的主持人不是当前小通，无法在桌宠里修改。")}
        }
        let body=try JSONSerialization.data(withJSONObject:["name":name.trimmingCharacters(in:.whitespacesAndNewlines),"member_ids":ids])
        let (data,response)=try await request(path,method:teamId == nil ? "POST" : "PATCH",body:body,contentType:"application/json")
        let result=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any] ?? [:]
        guard (200..<300).contains(response.statusCode) else {
            let error=(result["error"] as? [String:Any])?["message"] as? String ?? result["detail"] as? String ?? "团队未保存，请刷新后重试。"
            throw CompanionError.unavailable(error)
        }
        return result
    }
    func webSocket(agentId: String) throws -> URLSessionWebSocketTask {
        let id = try EndpointPolicy.segment(agentId)
        guard let token = credentials.read(origin: origin) else { throw CompanionError.signedOut }
        var components = URLComponents(url: try EndpointPolicy.api("/api/agents/\(id)/chat/ws", origin: origin), resolvingAgainstBaseURL: false)!
        components.scheme = origin.scheme == "https" ? "wss" : "ws"
        var request = URLRequest(url: components.url!)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let task = transport.webSocketTask(with: request)
        task.maximumMessageSize = 16 * 1024 * 1024
        return task
    }
    func upload(agentId: String, filename: String, mime: String, bytes: Data) async throws -> [String: Any] {
        guard bytes.count <= 12 * 1024 * 1024, CompanionUploadPolicy.mimeTypes.contains(mime) else { throw CompanionError.unavailable("请选择不超过 12 MB 的图片、Excel、CSV 或 PDF。") }
        let id = try EndpointPolicy.segment(agentId)
        let safeName = (filename as NSString).lastPathComponent.replacingOccurrences(of: "\"", with: "").replacingOccurrences(of: "\r", with: "").replacingOccurrences(of: "\n", with: "")
        let boundary = "OctopCompanion-\(UUID().uuidString)"
        var body = Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(safeName)\"\r\nContent-Type: \(mime)\r\n\r\n".utf8)
        body.append(bytes); body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        let (data, response) = try await request("/api/agents/\(id)/upload", method: "POST", body: body, contentType: "multipart/form-data; boundary=\(boundary)")
        guard (200..<300).contains(response.statusCode), let result = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw CompanionError.unavailable("附件上传未完成，请检查专家是否已启动及文件大小限制。") }
        return result
    }
    func approvalStream(agentId:String, threadId:String, pendingId:String, decisions:[[String:Any]]) async throws -> URLSession.AsyncBytes {
        let id=try EndpointPolicy.segment(agentId); _ = try CompanionChatCommand.threadID(threadId); _ = try EndpointPolicy.segment(pendingId)
        guard (1...16).contains(decisions.count), decisions.allSatisfy({d in
            guard let type=d["type"] as? String, ["approve","reject","respond"].contains(type) else {return false}
            if let text=d["message"] as? String, text.count > 8000 {return false}
            return type != "respond" || !(d["message"] as? String ?? "").trimmingCharacters(in:.whitespacesAndNewlines).isEmpty
        }) else {throw CompanionError.invalidPath}
        let startOrigin=origin
        guard let token=credentials.read(origin:startOrigin) else {throw CompanionError.signedOut}
        var request=URLRequest(url:try EndpointPolicy.api("/api/agents/\(id)/chat/hitl/resume",origin:startOrigin))
        request.httpMethod="POST"; request.timeoutInterval=3600
        request.setValue("Bearer \(token)",forHTTPHeaderField:"Authorization")
        request.setValue("application/json",forHTTPHeaderField:"Content-Type")
        request.setValue("text/event-stream",forHTTPHeaderField:"Accept")
        request.httpBody=try JSONSerialization.data(withJSONObject:["thread_id":threadId,"pending_id":pendingId,"decisions":decisions])
        let (bytes,response)=try await transport.bytes(for:request)
        guard let http=response as? HTTPURLResponse, EndpointPolicy.sameOrigin(http.url ?? startOrigin,startOrigin) else {throw CompanionError.invalidPath}
        if http.statusCode == 401 && origin == startOrigin && credentials.read(origin:startOrigin) == token {
            credentials.clear(origin:startOrigin); DispatchQueue.main.async {self.onExpired?(startOrigin)}
        }
        guard http.statusCode == 200, http.mimeType == "text/event-stream" else {throw CompanionError.unavailable("确认未提交（HTTP \(http.statusCode)），请核对登录及任务状态。")}
        return bytes
    }
    func image(_ path: String) async throws -> (Data, String) {
        let (data, response) = try await request(path)
        let mime = response.mimeType ?? ""
        guard response.statusCode == 200, mime.hasPrefix("image/"), data.count <= 32 * 1024 * 1024 else { throw CompanionError.unavailable("图片暂时无法读取，请在 Octop 中查看。") }
        return (data, mime)
    }
}
