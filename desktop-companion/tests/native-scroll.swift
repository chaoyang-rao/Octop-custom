import AppKit
import WebKit
final class NativeScrollCheck:NSObject,WKNavigationDelegate,WKScriptMessageHandler{
 var web:WKWebView!;var window:NSWindow!;let script:String
 init(script:String){self.script=script;super.init()}
 func start(index:URL,bridge:String,width:Double,height:Double){
  let c=WKWebViewConfiguration();c.websiteDataStore = .nonPersistent();c.userContentController.add(self,name:"companion");c.userContentController.add(self,name:"fixtureControl");c.userContentController.addUserScript(WKUserScript(source:bridge,injectionTime:.atDocumentStart,forMainFrameOnly:true))
  web=WKWebView(frame:NSRect(x:0,y:0,width:width,height:height),configuration:c);web.navigationDelegate=self
  window=NSWindow(contentRect:NSRect(x:80,y:80,width:width,height:height),styleMask:[.titled],backing:.buffered,defer:false);window.title="Octop 滚动隔离验收";window.contentView=web;window.orderFront(nil)
  web.loadFileURL(index,allowingReadAccessTo:index.deletingLastPathComponent())
 }
 func userContentController(_ userContentController:WKUserContentController,didReceive message:WKScriptMessage){
  if message.name == "fixtureControl", let size=message.body as? [String:Double],let width=size["width"],let height=size["height"] {
   window.setContentSize(NSSize(width:width,height:height));web.frame=window.contentView!.bounds
   web.evaluateJavaScript("window.__nativeResizeDone()",completionHandler:nil);return
  }
  guard let data=try? JSONSerialization.data(withJSONObject:message.body),let text=String(data:data,encoding:.utf8)else{return}
  web.evaluateJavaScript("window.__fixturePostMessage(\(text))",completionHandler:nil)
 }
 func webView(_ webView:WKWebView,didFinish navigation:WKNavigation!){
  web.callAsyncJavaScript(script,arguments:[:],in:nil,in:.page){result in
   switch result{case .success(let value):print(value as? String ?? "null");exit(0);case .failure(let error):print("native_fixture_error=\(error)");exit(1)}
  }
 }
}
let a=NSApplication.shared;a.setActivationPolicy(.accessory)
let bridge=try String(contentsOfFile:CommandLine.arguments[2],encoding:.utf8)
let script=try String(contentsOfFile:CommandLine.arguments[3],encoding:.utf8)
let check=NativeScrollCheck(script:script)
let width=CommandLine.arguments.count>4 ? Double(CommandLine.arguments[4])! : 456
let height=CommandLine.arguments.count>5 ? Double(CommandLine.arguments[5])! : 510
check.start(index:URL(fileURLWithPath:CommandLine.arguments[1]),bridge:bridge,width:width,height:height)
DispatchQueue.main.asyncAfter(deadline:.now()+20){print("native_fixture_timeout");exit(1)}
a.run()
