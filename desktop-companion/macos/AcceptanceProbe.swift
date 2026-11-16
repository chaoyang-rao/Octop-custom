import Foundation

enum AcceptanceProbe {
    static func inspectTestThread(_ threadId: String, origin: URL) async throws -> [String: Any] {
        let client = BackendClient(origin: origin)
        let user = try await client.user()
        guard let userId = user["id"] as? Int else { throw CompanionError.signedOut }
        let directory = try await client.json("/api/agents")
        let owned = rows(directory["data"] as Any).filter { ($0["user_id"] as? Int) == userId }
        guard let agentId = (owned.first(where: { ($0["name"] as? String) == "小通" }) ?? owned.first)?["agent_id"] as? String else { throw CompanionError.signedOut }
        let agent = try EndpointPolicy.segment(agentId), thread = try EndpointPolicy.segment(threadId)
        let result = try await client.json("/api/agents/\(agent)/threads/\(thread)/history?limit=30")
        guard result["status"] as? Int == 200, let history = (result["data"] as? [String: Any])?["messages"] as? [[String: Any]] else { throw CompanionError.unavailable("无法读取这个验收会话。") }
        func text(_ row: [String: Any]) -> String {
            if let plain = row["content"] as? String { return plain }
            return (row["content"] as? [[String: Any]] ?? []).compactMap { $0["type"] as? String == "text" ? $0["text"] as? String : nil }.joined(separator: "\n")
        }
        let fixture = history.contains { row in
            ["user", "human"].contains(row["role"] as? String ?? row["type"] as? String ?? "") && text(row).contains("验收消息") && text(row).contains("不是业务任务")
        }
        guard fixture else { throw CompanionError.unavailable("此诊断只读取本客户端创建的验收对话。") }
        var excerpt = String(history.filter { ["assistant", "ai"].contains($0["role"] as? String ?? $0["type"] as? String ?? "") }.map(text).joined(separator: "\n").suffix(1200))
        for pattern in ["(?i)Bearer\\s+[A-Za-z0-9._-]+", "(?:sk-|gh[pousr]_)[A-Za-z0-9_-]{16,}", "eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+"] {
            if let regex = try? NSRegularExpression(pattern: pattern) { excerpt = regex.stringByReplacingMatches(in: excerpt, range: NSRange(excerpt.startIndex..., in: excerpt), withTemplate: "***REDACTED***") }
        }
        return ["fixture_verified": true, "thread_id": threadId, "assistant_excerpt": excerpt]
    }
    static func preflight(origin: URL) async throws -> [String: Any] {
        let client = BackendClient(origin: origin)
        let (data, response) = try await client.request("/api/health", authenticated: false)
        let health = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        let (identityData, _) = try await client.request("/api/health/companion", authenticated: false)
        let identity = (try? JSONSerialization.jsonObject(with: identityData)) as? [String: Any]
        return ["backend_reachable": response.statusCode == 200, "backend_release": health?["custom_release"] ?? NSNull(), "transport": "loopback_direct", "token_required": false, "standalone": identity?["companion"] as? Bool == true, "backend_origin": origin.absoluteString, "external_octop_required": false]
    }
    private static func rows(_ value: Any) -> [[String: Any]] {
        if let array = value as? [[String: Any]] { return array }
        if let object = value as? [String: Any] {
            for key in ["agents", "items", "knowledge_bases"] { if let array = object[key] as? [[String: Any]] { return array } }
        }
        return []
    }
    static func run(imagePath: String?, origin: URL) async throws -> [String: Any] {
        let client = BackendClient(origin: origin)
        let user = try await client.user()
        guard let userId = user["id"] as? Int else { throw CompanionError.signedOut }
        let agentsResult = try await client.json("/api/agents")
        let agents = rows(agentsResult["data"] as Any).filter { ($0["user_id"] as? Int) == userId }
        guard let agent = agents.first(where: { ($0["name"] as? String) == "小通" }) ?? agents.first,
              let agentId = agent["agent_id"] as? String else { throw CompanionError.unavailable("当前账号没有可用于验收的本机专家。") }
        let connectors = try await client.json("/api/connector-instances")
        let knowledge = try await client.json("/api/knowledge-bases")
        let media = try? await client.json("/api/admin/media-generation")
        var report: [String: Any] = ["authenticated_user_id": userId, "owned_experts": agents.count,
            "visible_connections": rows(connectors["data"] as Any).count,
            "knowledge_list_http": knowledge["status"] ?? 0,
            "knowledge_bases": rows(knowledge["data"] as Any).count,
            "image_generation_http_status": media?["status"] ?? NSNull()]
        if media?["status"] as? Int == 200, let configured = (media?["data"] as? [String: Any])?["configured"] as? Bool { report["image_generation_configured"] = configured }
        else { report["image_generation_configured"] = NSNull() }
        let textResult = try await chat(client: client, agent: agentId, userId: userId,
            content: [["type": "text", "text": "这是一条独立桌宠连接验收消息，不是业务任务，请不要调用工具或记忆，也不要保存新记忆。仅回复：桌宠连接成功。"]], suffix: "text")
        report["text_reply_passed"] = textResult.text.contains("桌宠连接成功")
        report["text_thread_id"] = textResult.thread
        if let imagePath {
            let data = try Data(contentsOf: URL(fileURLWithPath: imagePath))
            let image = try await client.upload(agentId: agentId, filename: "companion-vision-check.png", mime: "image/png", bytes: data)
            guard let path = image["path"] as? String else { throw CompanionError.unavailable("图片上传没有返回工作区路径。") }
            let result = try await chat(client: client, agent: agentId, userId: userId, content: [
                ["type": "text", "text": "这是一条图片输入验收消息，不是业务任务，不要调用工具或记忆，不要保存新记忆。请只说出图片里主角的名字。"],
                ["type": "image_url", "image_url": ["url": path], "workspace_path": path, "filename": "companion-vision-check.png", "mime_type": "image/png"]], suffix: "image")
            report["image_uploaded"] = true
            report["image_reply_passed"] = result.text.contains("哆啦") || result.text.contains("机器猫") || result.text.lowercased().contains("doraemon")
            report["image_thread_id"] = result.thread
            if let preview = image["url"] as? String, preview.hasPrefix("/api/") {
                let downloaded = try await client.image(preview)
                report["authenticated_image_preview_passed"] = downloaded.0 == data
            }
        }
        return report
    }
    private static func chat(client: BackendClient, agent: String, userId: Int, content: [[String: Any]], suffix: String) async throws -> (text: String, thread: String) {
        let socket = try client.webSocket(agentId: agent)
        socket.resume()
        defer { socket.cancel(with: .normalClosure, reason: nil) }
        let frame: [String: Any] = ["type": "user_turn", "session_key": "\(agent):dashboard:\(userId):companion-acceptance-\(suffix)-\(UUID().uuidString)",
            "messages": [["role": "user", "content": content]], "mcp_servers": [String](), "knowledge_base_ids": [String](), "skills": [String](), "conversation_mode": "ask"]
        let encoded = try JSONSerialization.data(withJSONObject: frame)
        try await socket.send(.string(String(data: encoded, encoding: .utf8)!))
        return try await withThrowingTaskGroup(of: (String, String).self) { group in
            group.addTask {
                var text = "", thread = ""
                while !Task.isCancelled {
                    let message = try await socket.receive()
                    let data: Data
                    switch message { case .data(let bytes): data = bytes; case .string(let value): data = Data(value.utf8); @unknown default: continue }
                    guard let chunk = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
                    if let id = chunk["thread_id"] as? String { thread = id }
                    if chunk["type"] as? String == "token", let value = chunk["content"] as? String { text += value }
                    if chunk["type"] as? String == "error" { throw CompanionError.unavailable("模型验收请求未完成；请在桌宠或 Octop 查看模型配置。") }
                    if chunk["type"] as? String == "done" { return (text, thread) }
                }
                throw CancellationError()
            }
            group.addTask { try await Task.sleep(nanoseconds: 180_000_000_000); throw CompanionError.unavailable("专家验收响应超时。") }
            do {
                let value = try await group.next()!
                socket.cancel(with: .normalClosure, reason: nil); group.cancelAll(); return value
            } catch { socket.cancel(with: .goingAway, reason: nil); group.cancelAll(); throw error }
        }
    }
}
