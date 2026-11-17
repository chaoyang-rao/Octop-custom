import Foundation

enum CompanionUploadPolicy {
    static let extensions = ["png","jpg","jpeg","webp","gif","pdf","csv","xls","xlsx"]
    static let mimeTypes = ["image/png","image/jpeg","image/webp","image/gif","application/pdf","text/csv","application/vnd.ms-excel","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]
}

struct CompanionChatCommand {
    static func threadID(_ value:String) throws -> String {
        guard !value.isEmpty, value.count <= 512, value.range(of:"^[A-Za-z0-9_~-]+$",options:.regularExpression) != nil else {throw CompanionError.invalidPath}
        return value
    }
    let board: String
    let agent: String
    let context: String
    var frame: [String: Any]
    init(_ args: [String: Any]) throws {
        guard let board = args["board"] as? String, ["aftersales","workbench","profit","knowledge","team"].contains(board),
              let agent = args["agentId"] as? String, let context = args["contextKey"] as? String,
              var frame = args["frame"] as? [String:Any], let type = frame["type"] as? String,
              ["user_turn","subscribe","cancel","ping","steer_remove"].contains(type) else { throw CompanionError.invalidPath }
        self.board = board; self.agent = try EndpointPolicy.segment(agent); self.context = try EndpointPolicy.segment(context)
        if let thread = frame["thread_id"] as? String { _ = try Self.threadID(thread) }
        if ["subscribe","cancel","steer_remove"].contains(type), frame["thread_id"] as? String == nil { throw CompanionError.invalidPath }
        frame.removeValue(forKey:"hitl_policy")
        self.frame = frame
    }
}

struct CompanionSSEDecoder {
    private var buffer = Data()
    private var lines: [String] = []
    private var size = 0
    mutating func feed(byte: UInt8) throws -> [String:Any]? {
        if byte == 10 {
            var line=String(decoding:buffer,as:UTF8.self);buffer.removeAll(keepingCapacity:true)
            if line.hasSuffix("\r") {line.removeLast()}
            return try feed(line)
        }
        guard buffer.count < 16*1024*1024 else {throw CompanionError.invalidPath}
        buffer.append(byte);return nil
    }
    mutating func feed(_ line: String) throws -> [String:Any]? {
        if line.isEmpty {
            defer { lines=[]; size=0 }
            if lines.isEmpty { return nil }
            let joined=lines.joined(separator:"\n")
            if joined == "[DONE]" { return nil }
            guard let data=joined.data(using:.utf8), let frame=try JSONSerialization.jsonObject(with:data) as? [String:Any] else { throw CompanionError.invalidPath }
            return frame
        }
        if line.hasPrefix("data:") {
            var data=String(line.dropFirst(5)); if data.hasPrefix(" ") {data.removeFirst()}
            size += data.utf8.count
            guard size <= 16*1024*1024 else {throw CompanionError.invalidPath}
            lines.append(data)
        }
        return nil
    }
}
