import Foundation

@main struct ChatTransportCheck {
 static func main() async throws {
  let args:[String:Any] = ["board":"profit","agentId":"owned","contextKey":"context-1","frame":["type":"cancel","thread_id":"thread-1"]]
  let command=try CompanionChatCommand(args);precondition(command.context == "context-1")
  precondition(["pdf","csv","xls","xlsx"].allSatisfy {CompanionUploadPolicy.extensions.contains($0)})
  _=try CompanionChatCommand.threadID("thread-1~team-member")
  var missing=args;missing.removeValue(forKey:"contextKey")
  do {_ = try CompanionChatCommand(missing);throw CompanionError.unavailable("Missing context was accepted")}catch CompanionError.invalidPath {}
  var bypass=args;bypass["frame"]=["type":"user_turn","hitl_policy":["mode":"allow_all"]]
  let sanitized=try CompanionChatCommand(bypass);precondition(sanitized.frame["hitl_policy"] == nil)
  var decoder=CompanionSSEDecoder()
  _=try decoder.feed("event: chunk");_=try decoder.feed("data: {\"type\":\"token\",\"content\":\"中文\"}")
  let decoded=try decoder.feed("");precondition(decoded?["content"] as? String == "中文")
  var byteDecoder=CompanionSSEDecoder(),byteFrames:[[String:Any]]=[]
  for byte in Data("event: chunk\r\ndata: {\"type\":\"token\",\"content\":\"中文跨字节\"}\r\n\r\n".utf8) {if let frame=try byteDecoder.feed(byte:byte){byteFrames.append(frame)}}
  precondition(byteFrames.count == 1 && byteFrames[0]["content"] as? String == "中文跨字节")
  guard CommandLine.arguments.count > 1 else {print("chat_identity_and_sse_decoder=passed");return}
  let client=BackendClient(origin:try EndpointPolicy.origin(CommandLine.arguments[1]))
  try client.credentials.save("fixture-only-token",origin:client.origin)
  let socket=try client.webSocket(agentId:"owned");socket.resume()
  try await socket.send(.string(String(data:try JSONSerialization.data(withJSONObject:command.frame),encoding:.utf8)!))
  let received=try await socket.receive()
  if case .string(let text)=received {precondition(text.contains("cancel_received"))} else {throw CompanionError.invalidPath}
  socket.cancel(with:.normalClosure,reason:nil)
  let bytes=try await client.approvalStream(agentId:"owned",threadId:"thread-1",pendingId:"pending-1",decisions:[["type":"respond","message":"只看本周"]])
  var streamed=CompanionSSEDecoder(),types:[String]=[], text=""
  for try await byte in bytes {if let frame=try streamed.feed(byte:byte) {types.append(frame["type"] as? String ?? "");text += frame["content"] as? String ?? ""}}
  precondition(types == ["turn.resumed","token","done"] && text == "已确认中文回答", "SSE must stream complete events")
  for (name,mime) in [("data.csv","text/csv"),("report.pdf","application/pdf"),("sheet.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")] {
   let result=try await client.upload(agentId:"owned",filename:name,mime:mime,bytes:Data("fixture".utf8));precondition(result["filename"] as? String == name)
  }
  print("native_cancel_sse_approval_and_document_upload=passed")
 }
}
