import Foundation
import SwiftUI
import UIKit
import WebKit

struct WorkspaceView: UIViewRepresentable {
    let server: PairedServer
    let token: String
    let routePath: String
    @ObservedObject var model: AppModel
    func makeCoordinator() -> Coordinator { Coordinator(server: server, model: model) }
    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = model.webStore(for: server)
        let controller = WKUserContentController()
        controller.add(context.coordinator, name: "octopMobile")
        let tokenLiteral = String(data: try! JSONSerialization.data(withJSONObject: token, options: [.fragmentsAllowed]), encoding: .utf8)!
        let script = """
        (()=>{
          localStorage.removeItem('auth_token');sessionStorage.setItem('auth_token',\(tokenLiteral));
          const send=value=>window.webkit.messageHandlers.octopMobile.postMessage(value);
          window.addEventListener('octop:unauthorized',()=>send({kind:'unauthorized'}));
          const Base=window.WebSocket;
          window.WebSocket=class extends Base{
            constructor(...args){super(...args);this.addEventListener('message',event=>{
              try{const p=JSON.parse(event.data);if(['turn.started','turn.resumed','turn.ended','approval.required','hitl','error','task.updated'].includes(p.type))send({kind:'status',type:p.type,thread_id:p.thread_id||'',agent_id:p.agent_id||'',failed:!!p.failed,status:p.status||'',task_id:p.task_id||'',task_attempt:p.task_attempt});}catch{}
            });}
          };
        })();
        """
        controller.addUserScript(WKUserScript(source: script, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        configuration.userContentController = controller
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        view.uiDelegate = context.coordinator
        view.isInspectable = false
        view.allowsBackForwardNavigationGestures = true
        context.coordinator.routePath = routePath
        view.load(URLRequest(url: URL(string: routePath, relativeTo: server.baseURL)!.absoluteURL))
        return view
    }
    func updateUIView(_ uiView: WKWebView, context: Context) {
        guard context.coordinator.routePath != routePath else { return }
        context.coordinator.routePath = routePath
        let literal = String(data: try! JSONSerialization.data(withJSONObject: routePath, options: [.fragmentsAllowed]), encoding: .utf8)!
        uiView.evaluateJavaScript("history.pushState(null,'',\(literal));window.dispatchEvent(new PopStateEvent('popstate'))")
    }
    static func dismantleUIView(_ uiView: WKWebView, coordinator: Coordinator) {
        uiView.stopLoading(); uiView.configuration.userContentController.removeScriptMessageHandler(forName: "octopMobile")
    }
    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, WKDownloadDelegate {
        let server: PairedServer
        let model: AppModel
        var routePath = "/"
        private var downloaded: [ObjectIdentifier: URL] = [:]
        init(server: PairedServer, model: AppModel) { self.server = server; self.model = model }
        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.frameInfo.isMainFrame, message.frameInfo.securityOrigin.host == server.baseURL.host,
                  message.frameInfo.securityOrigin.protocol == server.baseURL.scheme,
                  let value = message.body as? [String: Any] else { return }
            if value["kind"] as? String == "unauthorized" { model.expired(server) }
            if value["kind"] as? String == "status" { model.handleStatus(value, source: server) }
        }
        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            if navigationAction.shouldPerformDownload { decisionHandler(.download); return }
            guard navigationAction.targetFrame?.isMainFrame != false else { decisionHandler(.allow); return }
            guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
            if url.scheme == server.baseURL.scheme && url.host == server.baseURL.host && url.port == server.baseURL.port {
                decisionHandler(.allow)
            } else {
                decisionHandler(.cancel)
                if navigationAction.navigationType == .linkActivated && ["https", "http"].contains(url.scheme ?? "") {
                    UIApplication.shared.open(url)
                }
            }
        }
        func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse,
                     decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
            decisionHandler(navigationResponse.canShowMIMEType ? .allow : .download)
        }
        func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
        func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }
        func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String,
                      completionHandler: @escaping (URL?) -> Void) {
            let filename = URL(fileURLWithPath: suggestedFilename).lastPathComponent
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            do {
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                let target = folder.appendingPathComponent(filename.isEmpty ? "attachment" : filename)
                downloaded[ObjectIdentifier(download)] = target
                completionHandler(target)
            } catch { completionHandler(nil) }
        }
        func downloadDidFinish(_ download: WKDownload) {
            guard let url = downloaded.removeValue(forKey: ObjectIdentifier(download)),
                  let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
                  var presenter = scene.windows.first(where: \.isKeyWindow)?.rootViewController else { return }
            while let presented = presenter.presentedViewController { presenter = presented }
            let share = UIActivityViewController(activityItems: [url], applicationActivities: nil)
            share.popoverPresentationController?.sourceView = presenter.view
            share.popoverPresentationController?.sourceRect = CGRect(x: presenter.view.bounds.midX, y: presenter.view.bounds.midY, width: 1, height: 1)
            presenter.present(share, animated: true)
        }
    }
}

struct NotificationReader {
    static func listen(server: PairedServer, token: String, model: AppModel) async {
        guard server.allows("notifications") else { return }
        await model.reportForeground(true, server: server)
        while !Task.isCancelled {
            guard var components = URLComponents(url: server.baseURL, resolvingAgainstBaseURL: false) else { return }
            components.scheme = server.baseURL.scheme == "https" ? "wss" : "ws"
            components.path = "/api/notifications/ws"
            guard let url = components.url else { return }
            var request = URLRequest(url: url)
            request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
            let session = URLSession(configuration: .ephemeral)
            let socket = session.webSocketTask(with: request)
            socket.resume()
            let heartbeat = Task {
                while !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(20))
                    try? await socket.send(.string("{\"type\":\"ping\"}"))
                    await model.reportForeground(true, server: server)
                }
            }
            do {
                try await withTaskCancellationHandler {
                    while !Task.isCancelled {
                        let message = try await socket.receive()
                        let data: Data
                        switch message { case .string(let value): data = Data(value.utf8); case .data(let value): data = value; @unknown default: continue }
                        if let frame = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                            await model.handleStatus(frame, source: server)
                        }
                    }
                } onCancel: { socket.cancel(with: .goingAway, reason: nil) }
            } catch {
                if [4001, 4401].contains(socket.closeCode.rawValue) {
                    await model.expired(server)
                    heartbeat.cancel(); session.invalidateAndCancel(); return
                }
            }
            heartbeat.cancel(); socket.cancel(with: .goingAway, reason: nil); session.invalidateAndCancel()
            if Task.isCancelled { await Task.detached { await model.reportForeground(false, server: server) }.value }
            if socket.closeCode.rawValue == 4403 { return }
            if !Task.isCancelled { try? await Task.sleep(for: .seconds(3)) }
        }
    }
}
