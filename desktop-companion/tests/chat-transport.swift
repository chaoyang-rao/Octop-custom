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
  var legacy=args;legacy["frame"]=["type":"user_turn","mcp_servers":["another-experts-mcp"]]
  let inherited=try CompanionChatCommand(legacy);precondition(inherited.frame["mcp_servers"] == nil, "Legacy frames must not replace the expert's MCP binding")
  var decoder=CompanionSSEDecoder()
  _=try decoder.feed("event: chunk");_=try decoder.feed("data: {\"type\":\"token\",\"content\":\"中文\"}")
  let decoded=try decoder.feed("");precondition(decoded?["content"] as? String == "中文")
  var byteDecoder=CompanionSSEDecoder(),byteFrames:[[String:Any]]=[]
  for byte in Data("event: chunk\r\ndata: {\"type\":\"token\",\"content\":\"中文跨字节\"}\r\n\r\n".utf8) {if let frame=try byteDecoder.feed(byte:byte){byteFrames.append(frame)}}
  precondition(byteFrames.count == 1 && byteFrames[0]["content"] as? String == "中文跨字节")
  guard CommandLine.arguments.count > 1 else {print("chat_identity_and_sse_decoder=passed");return}
  let client=BackendClient(origin:try EndpointPolicy.origin(CommandLine.arguments[1]))
  try client.credentials.save("fixture-only-token",origin:client.origin)
  let originalBinding=try await client.expertMCPs("owned");precondition(originalBinding == ["fixture-owned"])
  _=try await client.request("/api/fixture/binding",method:"PATCH",body:Data("{\"mcp_servers\":[\"fixture-updated\"]}".utf8),contentType:"application/json")
  let updatedBinding=try await client.expertMCPs("owned");precondition(updatedBinding == ["fixture-updated"], "Expert MCP changes must apply without client-side configuration")
  do {_=try await client.expertMCPs("foreign");throw CompanionError.invalidPath} catch CompanionError.unavailable {}
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
  let team=try await client.saveTeam(name:"测试团队",members:["member"],hostId:"owned",teamId:nil);precondition(team["primary_agent_id"] as? String == "owned")
  try await client.validateTeam("team-created")
  _=try await client.saveTeam(name:"修改成员",members:["member"],hostId:"owned",teamId:"team-created")
  do {_=try await client.saveTeam(name:"bad",members:["member"],hostId:"other-host",teamId:nil);throw CompanionError.invalidPath} catch CompanionError.unavailable {}
  do {_=try await client.saveTeam(name:"bad",members:["foreign"],hostId:"owned",teamId:nil);throw CompanionError.invalidPath} catch CompanionError.unavailable {}
  print("native_cancel_sse_approval_and_document_upload=passed")
 }
}
