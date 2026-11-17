import AppKit
import AVFoundation
import Carbon
import UniformTypeIdentifiers
import WebKit

@MainActor
final class CompanionApp: NSObject, NSApplicationDelegate, NSWindowDelegate, WKScriptMessageHandler, WKNavigationDelegate, WKUIDelegate {
    private let defaults = UserDefaults.standard
    private let engine = EngineRuntime()
    private lazy var client = BackendClient(origin: URL(string: "http://127.0.0.1:1")!)
    private let speech = SpeechController()
    private var petWindow: PetPanel!
    private var pet: PetView!
    private var chatWindow: NSWindow!
    private var chatView: WKWebView!
    private var hasPlacedChat = false
    private var authWindow: NSWindow?
    private var authView: WKWebView?
    private var loginMode = false
    private var statusItem: NSStatusItem!
    private var currentUser: [String: Any]?
    private var loginRevision = 0
    private var sockets: [String: (agent: String, context: String, task: URLSessionWebSocketTask)] = [:]
    private var receiveLoops: [String: Task<Void, Never>] = [:]
    private var approvalStreams: [String: (id: UUID, task: Task<Void,Never>)] = [:]
    private var approvalEpoch: [String:Int] = [:]
    private var approvalHeaders: [String:(id:UUID,task:Task<URLSession.AsyncBytes,Error>)] = [:]
    private var pingTimer: Timer?
    private var hotKey: EventHotKeyRef?
    private var hotKeyHandler: EventHandlerRef?
    private var capturesRemaining = 0
    private var sizingWindow: NSPanel?
    private var sizeSlider: NSSlider?
    private var sizeValue: NSTextField?
    private var pendingLaunchAction: CompanionLaunchAction?

    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            let resources = Bundle.main.resourceURL!
            pet = try PetView(root: resources.appendingPathComponent("Pet"))
            makeApplicationMenu()
            makeWindows(resources: resources)
            makeMenuBar()
            registerShortcut()
            client.onExpired = { [weak self] origin in Task { @MainActor in
                guard let self, self.client.origin == origin, self.client.credentials.read(origin: origin) == nil else { return }
                self.loginRevision += 1; self.currentUser = nil; self.closeSockets(); self.speech.stopRecognition(); self.speech.stopSpeaking(); self.event(["type": "authExpired"])
            } }
            speech.onEvent = { [weak self] value in
                    self?.event(value)
                    if value["type"] as? String == "speech" { self?.pet.setState(value["data"] as? String == "started" ? "speaking" : "idle") }
                    if value["type"] as? String == "voice" { self?.pet.setState(value["data"] as? String == "stopped" || value["error"] != nil ? "idle" : "listening") }
            }
            petWindow.orderFrontRegardless()
            pingTimer = Timer.scheduledTimer(withTimeInterval: 25, repeats: true) { [weak self] _ in
                Task { @MainActor in
                    guard let self else { return }
                    for item in self.sockets.values { item.task.sendPing { _ in } }
                }
            }
            if ProcessInfo.processInfo.arguments.contains("--show-chat") { showChat() }
            if ProcessInfo.processInfo.arguments.contains("--show-size") { showSizeControls() }
            if ProcessInfo.processInfo.arguments.contains("--login") { Task { do { try await ensureEngine(); showFullOctop(path: "/login", login: true) } catch { event(["type": "error", "error": error.localizedDescription]) } } }
            if let action = pendingLaunchAction { pendingLaunchAction = nil; performLaunchAction(action) }
        } catch {
            let alert = NSAlert(); alert.messageText = "哆啦暂时无法启动"; alert.informativeText = error.localizedDescription; alert.runModal(); NSApp.terminate(nil)
        }
    }

    private func makeApplicationMenu() {
        // WKWebView's standard editing actions use AppKit's responder chain.
        // An accessory app still needs these key equivalents for Cmd-V and
        // Unicode input helpers, even though it does not show a normal menu bar.
        let main = NSMenu()
        let applicationItem = NSMenuItem()
        let applicationMenu = NSMenu(title: "哆啦")
        let quit = NSMenuItem(title: "退出哆啦", action: #selector(quitCompanion), keyEquivalent: "q")
        quit.target = self
        applicationMenu.addItem(quit)
        applicationItem.submenu = applicationMenu
        main.addItem(applicationItem)
        let editItem = NSMenuItem()
        let edit = NSMenu(title: "编辑")
        for (title, action, key, modifiers) in [
            ("撤销", "undo:", "z", NSEvent.ModifierFlags.command),
            ("重做", "redo:", "z", [.command, .shift]),
            ("剪切", "cut:", "x", .command),
            ("复制", "copy:", "c", .command),
            ("粘贴", "paste:", "v", .command),
            ("全选", "selectAll:", "a", .command),
        ] {
            let item = NSMenuItem(title: title, action: Selector(action), keyEquivalent: key)
            item.keyEquivalentModifierMask = modifiers
            edit.addItem(item)
        }
        editItem.submenu = edit
        main.addItem(editItem)
        NSApp.mainMenu = main
    }

    private func makeWindows(resources: URL) {
        let side = PetSizing.restoredSide(defaults.double(forKey: "petSize"))
        let area = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let x = defaults.object(forKey: "petX") == nil ? area.maxX - side - 30 : defaults.double(forKey: "petX")
        let y = defaults.object(forKey: "petY") == nil ? area.minY + 35 : defaults.double(forKey: "petY")
        petWindow = PetPanel(contentRect: NSRect(x: x, y: y, width: side, height: side), styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        petWindow.isOpaque = false; petWindow.backgroundColor = .clear; petWindow.hasShadow = false
        petWindow.level = CompanionWindowLevels.pet; petWindow.hidesOnDeactivate = false; petWindow.isMovableByWindowBackground = false
        petWindow.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        petWindow.contentView = pet; pet.clampToScreen()
        pet.edgeHiding = defaults.object(forKey: "petEdgeHiding") == nil || defaults.bool(forKey: "petEdgeHiding")
        pet.onOpen = { [weak self] in self?.toggleChatFromPet() }
        pet.onMenu = { [weak self] event in guard let self else { return }; NSMenu.popUpContextMenu(self.contextMenu(), with: event, for: self.pet) }
        pet.onMoved = { [weak self] in self?.savePosition() }
        pet.onScale = { [weak self] multiplier in
            guard let self else { return }
            self.applyPetScale(Double(self.pet.placementFrame.width) / PetSizing.defaultSide * multiplier)
        }
        chatWindow = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 456, height: 684), styleMask: [.titled, .fullSizeContentView, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
        chatWindow.title = "哆啦"; chatWindow.titleVisibility = .hidden; chatWindow.titlebarAppearsTransparent = true
        chatWindow.titlebarSeparatorStyle = .none
        chatWindow.minSize = NSSize(width: 350, height: 510); chatWindow.level = CompanionWindowLevels.chat; chatWindow.isReleasedWhenClosed = false; chatWindow.delegate = self
        chatWindow.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        let config = WKWebViewConfiguration()
        config.userContentController.add(self, name: "companion")
        chatWindow.isOpaque = false; chatWindow.backgroundColor = .clear; chatWindow.hasShadow = true
        chatView = GlassChatWebView(frame:NSRect(x:0,y:0,width:456,height:706), configuration:config)
        chatView.setValue(false,forKey:"drawsBackground")
        chatView.underPageBackgroundColor = .clear; chatView.autoresizingMask = [.width,.height]
        chatView.navigationDelegate = self; chatView.uiDelegate = self
        chatWindow.contentView = chatMaterial(content:chatView)
        let web = resources.appendingPathComponent("web")
        chatView.loadFileURL(web.appendingPathComponent("index.html"), allowingReadAccessTo: web)
        NotificationCenter.default.addObserver(self, selector: #selector(screensChanged), name: NSApplication.didChangeScreenParametersNotification, object: nil)
    }

    private func chatMaterial(content: NSView) -> NSView {
        let surface = ChatWindowContentView(content:content)
        #if compiler(>=6.2)
        if #available(macOS 26.0, *) {
            let glass = NSGlassEffectView(frame:content.frame)
            glass.style = .regular; glass.cornerRadius = 20; glass.contentView = surface
            return glass
        }
        #endif
        let glass = NSVisualEffectView(frame:content.frame)
        glass.material = .underWindowBackground; glass.blendingMode = .behindWindow; glass.state = .active
        glass.wantsLayer = true; glass.layer?.cornerRadius = 20; glass.layer?.masksToBounds = true
        surface.autoresizingMask = [.width,.height]
        glass.addSubview(surface)
        return glass
    }

    private func makeMenuBar() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.button?.image = NSImage(systemSymbolName: "bubble.left.and.bubble.right.fill", accessibilityDescription: "哆啦")
        statusItem.button?.target = self; statusItem.button?.action = #selector(statusClicked)
        statusItem.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])
        statusItem.button?.toolTip = "哆啦 · 点击呼出对话，右键显示菜单"
    }
    @objc private func statusClicked() {
        if let event = NSApp.currentEvent, event.type == .rightMouseUp, let button = statusItem.button { NSMenu.popUpContextMenu(contextMenu(), with: event, for: button) }
        else { toggleChat() }
    }
    private func contextMenu() -> NSMenu {
        let menu = NSMenu()
        func item(_ name: String, _ action: Selector) { let value = NSMenuItem(title: name, action: action, keyEquivalent: ""); value.target = self; menu.addItem(value) }
        item("打开对话  ⌃⌥空格", #selector(openChat)); item(petWindow.isVisible ? "隐藏桌宠" : "显示桌宠", #selector(togglePet))
        menu.addItem(.separator())
        item("移到右下角", #selector(moveRight)); item("移到左下角", #selector(moveLeft))
        item("宠物大小…", #selector(showSizeControls))
        item(pet.paused ? "恢复动作" : "暂停动作", #selector(toggleAnimation))
        menu.addItem(.separator()); item("资源与模型设置", #selector(startOctop)); item("查看运行日志", #selector(showEngineLogs)); item("素材来源与说明", #selector(showCredits)); item("退出哆啦", #selector(quitCompanion))
        return menu
    }
    @objc private func openChat() { showChat() }
    private func toggleChat() { chatWindow.isVisible && chatWindow.isKeyWindow ? chatWindow.orderOut(nil) : showChat() }
    private func toggleChatFromPet() { chatWindow.isVisible ? chatWindow.orderOut(nil) : showChat() }
    private func showChat() {
        authWindow?.orderOut(nil); sizingWindow?.orderOut(nil)
        if !hasPlacedChat || !NSScreen.screens.contains(where: { $0.visibleFrame.intersects(chatWindow.frame) }) {
            let area = PetSizing.screenArea(for:pet.placementFrame,areas:NSScreen.screens.map(\.visibleFrame)) ?? NSScreen.main!.visibleFrame
            chatWindow.setFrame(CompanionWindowPlacement.chat(size:chatWindow.frame.size,pet:pet.placementFrame,area:area),display:true)
            hasPlacedChat = true
        }
        NSApp.activate(ignoringOtherApps: true); chatWindow.makeKeyAndOrderFront(nil)
    }
    @objc private func togglePet() { if petWindow.isVisible { petWindow.orderOut(nil) } else { petWindow.orderFrontRegardless() } }
    @objc private func toggleAnimation() { pet.paused.toggle() }
    @objc private func moveRight() { movePet(right: true) }
    @objc private func moveLeft() { movePet(right: false) }
    private func movePet(right: Bool) { pet.expandForPlacement(); guard let area = NSScreen.main?.visibleFrame else { return }; petWindow.setFrameOrigin(NSPoint(x: right ? area.maxX - petWindow.frame.width - 28 : area.minX + 28, y: area.minY + 28)); savePosition() }
    @objc private func showSizeControls() {
        chatWindow.orderOut(nil); authWindow?.orderOut(nil)
        if sizingWindow == nil {
            let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 280, height: 128), styleMask: [.titled, .closable, .utilityWindow], backing: .buffered, defer: false)
            panel.title = "宠物大小"; panel.level = .floating; panel.isReleasedWhenClosed = false
            panel.hidesOnDeactivate = false; panel.delegate = self
            panel.collectionBehavior = [.moveToActiveSpace, .fullScreenAuxiliary]
            let content = NSView(frame: NSRect(x: 0, y: 0, width: 280, height: 128))
            func label(_ text: String, _ rect: NSRect, _ size: CGFloat = 11) -> NSTextField {
                let field = NSTextField(labelWithString: text); field.frame = rect; field.font = .systemFont(ofSize: size); content.addSubview(field); return field
            }
            let heading = label("大小", NSRect(x: 18, y: 96, width: 100, height: 18), 12)
            heading.font = .systemFont(ofSize: 12, weight: .medium)
            let value = label("100%", NSRect(x: 202, y: 96, width: 60, height: 18), 12)
            value.alignment = .right; value.font = .monospacedDigitSystemFont(ofSize: 12, weight: .regular)
            sizeValue = value
            let slider = NSSlider(value: 100, minValue: PetSizing.minimumScale * 100, maxValue: PetSizing.maximumScale * 100, target: self, action: #selector(sizeSliderChanged(_:)))
            slider.frame = NSRect(x: 16, y: 60, width: 248, height: 22)
            slider.isContinuous = true; slider.numberOfTickMarks = 0; slider.allowsTickMarkValuesOnly = false
            slider.altIncrementValue = 1
            slider.setAccessibilityLabel("宠物大小，百分比")
            slider.setAccessibilityHelp("拖动时立即调整，也可使用方向键微调。")
            content.addSubview(slider); sizeSlider = slider
            label("50%", NSRect(x: 18, y: 42, width: 55, height: 14), 10).textColor = .secondaryLabelColor
            let upper = label("250%", NSRect(x: 207, y: 42, width: 55, height: 14), 10)
            upper.alignment = .right; upper.textColor = .secondaryLabelColor
            label("宠物上 ⌥+滚动", NSRect(x: 18, y: 15, width: 145, height: 16)).textColor = .secondaryLabelColor
            let reset = NSButton(title: "恢复100%", target: self, action: #selector(resetPetSize))
            reset.bezelStyle = .rounded; reset.controlSize = .small
            reset.frame = NSRect(x: 177, y: 10, width: 88, height: 25)
            reset.setAccessibilityLabel("恢复默认宠物大小")
            content.addSubview(reset); panel.contentView = content; sizingWindow = panel
        }
        updateSizeControls()
        if let panel = sizingWindow, !panel.isVisible,
           let area = PetSizing.screenArea(for: petWindow.frame, areas: NSScreen.screens.map(\.visibleFrame)) {
            let x = max(area.minX + 12, min(area.maxX - panel.frame.width - 12, petWindow.frame.midX - panel.frame.width / 2))
            let y = max(area.minY + 12, min(area.maxY - panel.frame.height - 12, petWindow.frame.maxY + 12))
            panel.setFrameOrigin(NSPoint(x: x, y: y))
        }
        NSApp.activate(ignoringOtherApps: true); sizingWindow?.makeKeyAndOrderFront(nil)
    }
    private func applyPetScale(_ scale: Double) {
        pet.resize(to: scale)
        defaults.set(Double(pet.placementFrame.width), forKey: "petSize")
        savePosition(); updateSizeControls()
    }
    private func updateSizeControls() {
        let percentage = Double(pet.placementFrame.width) / PetSizing.defaultSide * 100
        sizeSlider?.doubleValue = percentage
        let value = String(format: "%.0f%%", percentage)
        sizeValue?.stringValue = value
        sizeSlider?.setAccessibilityValueDescription(value)
    }
    @objc private func sizeSliderChanged(_ slider: NSSlider) { applyPetScale(slider.doubleValue / 100) }
    @objc private func resetPetSize() { applyPetScale(1) }
    @objc private func screensChanged() { pet.clampToScreen(); pet.dockNearEdge(); savePosition() }
    private func savePosition() { defaults.set(pet.placementFrame.minX, forKey: "petX"); defaults.set(pet.placementFrame.minY, forKey: "petY") }
    @objc private func startOctop() { Task { do { try await ensureEngine(); showFullOctop(path: "/companion/manage", login: false) } catch { event(["type": "error", "error": error.localizedDescription]) } } }
    @objc private func showEngineLogs() { NSWorkspace.shared.open(EngineRuntime.home.appendingPathComponent("Logs")) }
    private func ensureEngine() async throws {
        let origin = try await engine.start()
        if client.origin != origin { client.origin = origin }
    }
    @objc private func quitCompanion() { NSApp.terminate(nil) }
    @objc private func showCredits() {
        if let url = Bundle.main.url(forResource:"ASSET-NOTICE",withExtension:"txt") { NSWorkspace.shared.open(url) }
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.orderOut(nil)
        if sender === authWindow || sender === sizingWindow { loginMode = false; showChat() }
        return false
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if let authWindow, authWindow.isVisible {
            NSApp.activate(ignoringOtherApps: true)
            authWindow.makeKeyAndOrderFront(nil)
        } else { showChat() }
        return true
    }
    func application(_ application: NSApplication, open urls: [URL]) {
        guard let action = urls.compactMap({ CompanionLaunchAction(url: $0) }).last else { return }
        guard petWindow != nil else { pendingLaunchAction = action; return }
        performLaunchAction(action)
    }
    private func performLaunchAction(_ action: CompanionLaunchAction) {
        petWindow.orderFrontRegardless()
        switch action {
        case .open: showChat()
        case .size: showSizeControls()
        }
    }
    func applicationWillTerminate(_ notification: Notification) { closeSockets(); speech.stopRecognition(); speech.stopSpeaking(); engine.stop(); if let hotKey { UnregisterEventHotKey(hotKey) }; if let hotKeyHandler { RemoveEventHandler(hotKeyHandler) } }
    private func registerShortcut() {
        var type = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, context in
            guard let context else { return OSStatus(eventNotHandledErr) }
            let app = Unmanaged<CompanionApp>.fromOpaque(context).takeUnretainedValue()
            DispatchQueue.main.async { app.toggleChat() }; return noErr
        }, 1, &type, Unmanaged.passUnretained(self).toOpaque(), &hotKeyHandler)
        RegisterEventHotKey(UInt32(kVK_Space), UInt32(controlKey | optionKey), EventHotKeyID(signature: 0x4F435450, id: 1), GetApplicationEventTarget(), 0, &hotKey)
    }

    private func event(_ value: [String: Any]) { invoke("__companionEvent", value: value) }
    private func reply(_ id: String, result: Any = NSNull(), error: String? = nil) { invoke("__companionReply", value: error == nil ? ["id": id, "result": result] : ["id": id, "error": error!]) }
    private func invoke(_ function: String, value: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.fragmentsAllowed]), let json = String(data: data, encoding: .utf8) else { return }
        chatView?.evaluateJavaScript("window.\(function) && window.\(function)(\(json));", completionHandler: nil)
    }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        if message.name == "authCallback" {
            guard message.webView === authView, message.frameInfo.isMainFrame, let url = message.frameInfo.request.url, EndpointPolicy.sameOrigin(url, client.origin), let token = message.body as? String, !token.isEmpty else { return }
            loginRevision += 1
            let revision = loginRevision
            Task { @MainActor in await acceptLoginToken(token, revision: revision) }; return
        }
        guard message.webView === chatView, message.frameInfo.isMainFrame, message.frameInfo.request.url?.isFileURL == true,
              message.frameInfo.request.url?.standardizedFileURL.path == Bundle.main.resourceURL!.appendingPathComponent("web/index.html").standardizedFileURL.path,
              let body = message.body as? [String: Any], let id = body["id"] as? String, let op = body["op"] as? String else { return }
        let args = body["args"] as? [String: Any] ?? [:]
        Task { @MainActor in
            do { let result = try await handle(op: op, args: args); reply(id, result: result) }
            catch { reply(id, error: error.localizedDescription) }
        }
    }
    private func handle(op: String, args: [String: Any]) async throws -> Any {
        switch op {
        case "petPreferences": return ["edgeHiding": pet.edgeHiding]
        case "setEdgeHiding":
            guard let enabled = args["enabled"] as? Bool else { throw CompanionError.invalidPath }
            pet.edgeHiding = enabled; defaults.set(enabled, forKey: "petEdgeHiding"); savePosition(); return true
        case "petSize": showSizeControls(); return true
        case "help":
            guard let url = Bundle.main.url(forResource: "HELP", withExtension: "html") else { throw CompanionError.invalidPath }
            NSWorkspace.shared.open(url); return true
        case "status":
            try await ensureEngine()
            let revision = loginRevision, origin = client.origin
            let healthy = (try? await client.request("/api/health", authenticated: false))?.1.statusCode == 200
            var user: [String: Any]?
            if healthy { user = try? await client.user() }
            guard revision == loginRevision && origin == client.origin else { throw CancellationError() }
            currentUser = user
            if user == nil { speech.stopRecognition(); speech.stopSpeaking(); closeSockets() }
            var result: [String: Any] = ["authenticated": user != nil, "origin": client.origin.absoluteString, "storageScope": "companion-local-v1", "standalone": true, "backendRunning": healthy]
            if user != nil {
                let access = try? await client.json("/api/companion/access")
                result["companionAllowed"] = access?["status"] as? Int == 200 && (access?["data"] as? [String: Any])?["allowed"] as? Bool == true
                guard revision == loginRevision && origin == client.origin else { throw CancellationError() }
            }
            if let user { result["user"] = user }
            return result
        case "api":
            guard (args["method"] as? String ?? "GET") == "GET", let path = args["path"] as? String else { throw CompanionError.invalidPath }
            return try await client.json(path == "/api/agents" ? "/api/companion/agents" : path)
        case "login": try await ensureEngine(); showFullOctop(path: "/login", login: true); return true
        case "logout":
            loginRevision += 1
            speech.stopRecognition(); speech.stopSpeaking()
            closeSockets(); currentUser = nil; client.credentials.clear(origin: client.origin)
            _ = try? await authView?.evaluateJavaScript("localStorage.removeItem('auth_token');sessionStorage.removeItem('auth_token');")
            authView?.stopLoading(); authView?.configuration.userContentController.removeScriptMessageHandler(forName: "authCallback")
            authWindow?.contentView = nil; authWindow?.delegate = nil; authWindow?.close(); authWindow = nil; authView = nil
            event(["type": "authChanged"]); return true
        case "setOrigin":
            throw CompanionError.unavailable("独立桌宠自动管理本机问答引擎，无需填写 Octop 地址。")
        case "startOctop": startOctop(); return true
        case "openOctop":
            try await ensureEngine()
            let path = args["path"] as? String ?? ""
            let section = path.contains("connector") ? "connectors" : path.contains("knowledge") ? "knowledge" : path.contains("model") ? "models" : "experts"
            showFullOctop(path: "/companion/manage?section=" + section, login: false); return true
        case "openLink":
            guard let source = args["url"] as? String else { throw CompanionError.invalidPath }
            if source.hasPrefix("/") { showFullOctop(path: source, login: false); return true }
            guard let url = URL(string: source), ["https", "http"].contains(url.scheme?.lowercased() ?? ""), url.user == nil, url.password == nil else { throw CompanionError.invalidPath }
            NSWorkspace.shared.open(url); return true
        case "chatSend":
            let command = try CompanionChatCommand(args)
            if command.frame["type"] as? String == "cancel" { approvalEpoch[command.board,default:0] += 1;approvalHeaders.removeValue(forKey:command.board)?.task.cancel();approvalStreams.removeValue(forKey:command.board)?.task.cancel() }
            let socket = try socketFor(board: command.board, agent: command.agent, context: command.context)
            let data = try JSONSerialization.data(withJSONObject: command.frame)
            try await socket.send(.string(String(data: data, encoding: .utf8)!)); return true
        case "resumeApproval":
            guard let thread=args["threadId"] as? String, let pending=args["pendingId"] as? String,
                  let decisions=args["decisions"] as? [[String:Any]] else {throw CompanionError.invalidPath}
            var fields=args;fields["frame"]=["type":"subscribe","thread_id":thread]
            let command=try CompanionChatCommand(fields)
            let revision=loginRevision
            let hadSocket=sockets[command.board]?.context == command.context && sockets[command.board]?.agent == command.agent
            let socket=try socketFor(board:command.board,agent:command.agent,context:command.context)
            let epoch=approvalEpoch[command.board,default:0]
            if !hadSocket {try await socket.send(.string(String(data:try JSONSerialization.data(withJSONObject:command.frame),encoding:.utf8)!))}
            guard loginRevision == revision, approvalEpoch[command.board,default:0] == epoch else {throw CancellationError()}
            approvalHeaders.removeValue(forKey:command.board)?.task.cancel()
            let headerID=UUID(), headerTask=Task {try await client.approvalStream(agentId:command.agent,threadId:thread,pendingId:pending,decisions:decisions)}
            approvalHeaders[command.board]=(headerID,headerTask)
            defer {if approvalHeaders[command.board]?.id == headerID {approvalHeaders.removeValue(forKey:command.board)}}
            let bytes=try await headerTask.value
            guard loginRevision == revision, sockets[command.board]?.context == command.context, approvalEpoch[command.board,default:0] == epoch else {
                bytes.task.cancel()
                if loginRevision == revision, sockets[command.board]?.context == command.context {
                    let data=try JSONSerialization.data(withJSONObject:["type":"cancel","thread_id":thread])
                    try? await socket.send(.string(String(data:data,encoding:.utf8)!))
                }
                throw CancellationError()
            }
            approvalStreams.removeValue(forKey:command.board)?.task.cancel()
            let streamID=UUID()
            let task=Task { @MainActor [weak self] in
                var decoder=CompanionSSEDecoder(), terminal=false
                defer {bytes.task.cancel();if self?.approvalStreams[command.board]?.id == streamID {self?.approvalStreams.removeValue(forKey:command.board)}}
                do {
                    for try await byte in bytes {
                        if var frame=try decoder.feed(byte:byte) {
                            try Task.checkCancellation()
                            guard self?.approvalStreams[command.board]?.id == streamID, self?.loginRevision == revision else {break}
                            frame["thread_id"]=thread
                            if ["done","error","hitl_required"].contains(frame["type"] as? String ?? "") {terminal=true}
                            self?.event(["type":"chat","board":command.board,"contextKey":command.context,"data":frame])
                        }
                    }
                    if !terminal && !Task.isCancelled {throw CompanionError.unavailable("确认后的连接已结束，请刷新核对任务状态。")}
                } catch {
                    if !Task.isCancelled && self?.approvalStreams[command.board]?.id == streamID {
                        self?.event(["type":"resumeError","board":command.board,"contextKey":command.context,"error":error.localizedDescription])
                    }
                }
            }
            approvalStreams[command.board]=(streamID,task)
            return true
        case "chatClose": if let board = args["board"] as? String { closeSocket(board) }; return true
        case "upload":
            guard let agent = args["agentId"] as? String, let filename = args["filename"] as? String, let mime = args["mimeType"] as? String,
                  let base64 = args["base64"] as? String, base64.count <= 17 * 1024 * 1024, let data = Data(base64Encoded: base64) else { throw CompanionError.invalidPath }
            return try await client.upload(agentId: agent, filename: filename, mime: mime, bytes: data)
        case "image":
            guard let path = args["path"] as? String else { throw CompanionError.invalidPath }
            let (data, mime) = try await client.image(path)
            return ["url": "data:\(mime);base64,\(data.base64EncodedString())"]
        case "saveImage":
            guard let source = args["source"] as? String else { throw CompanionError.invalidPath }
            let (data, mime) = try await imageData(source)
            let panel = NSSavePanel(); panel.canCreateDirectories = true
            let ext = mime.contains("jpeg") ? "jpg" : mime.contains("webp") ? "webp" : mime.contains("gif") ? "gif" : mime.contains("svg") ? "svg" : "png"
            panel.nameFieldStringValue = "Octop-\(Int(Date().timeIntervalSince1970)).\(ext)"
            guard panel.runModal() == .OK, let destination = panel.url else { return false }
            try data.write(to: destination, options: .atomic); return true
        case "copy": NSPasteboard.general.clearContents(); NSPasteboard.general.setString(args["text"] as? String ?? "", forType: .string); return true
        case "startListening": guard currentUser != nil else { throw CompanionError.signedOut }; try await speech.start(); return true
        case "stopListening": speech.finish(); return true
        case "speak": guard currentUser != nil else { throw CompanionError.signedOut }; speech.speak(args["text"] as? String ?? ""); return true
        case "stopSpeaking": speech.stopSpeaking(); return true
        case "petState": if let state = args["state"] as? String { pet.setState(speech.isSpeaking ? "speaking" : speech.isListening ? "listening" : state) }; return true
        default: throw CompanionError.unavailable("此操作暂不可用。")
        }
    }

    private func imageData(_ source: String) async throws -> (Data, String) {
        if source.hasPrefix("/api/") { return try await client.image(source) }
        if source.hasPrefix("data:image/"), let comma = source.firstIndex(of: ","), source[..<comma].hasSuffix(";base64"), let data = Data(base64Encoded: String(source[source.index(after: comma)...])), data.count <= 32 * 1024 * 1024 { return (data, String(source.dropFirst(5).prefix(while: { $0 != ";" }))) }
        guard let url = URL(string: source), url.scheme == "https", url.user == nil, url.password == nil else { throw CompanionError.invalidPath }
        // Public image requests deliberately carry no Octop credentials.
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let mime = response.mimeType, mime.hasPrefix("image/"), data.count <= 32 * 1024 * 1024 else { throw CompanionError.unavailable("无法保存这个图片链接。") }
        return (data, mime)
    }
    private func socketFor(board: String, agent: String, context: String) throws -> URLSessionWebSocketTask {
        if let existing = sockets[board], existing.agent == agent, existing.context == context { return existing.task }
        closeSocket(board)
        let socket = try client.webSocket(agentId: agent)
        sockets[board] = (agent, context, socket); socket.resume()
        receiveLoops[board] = Task { @MainActor [weak self, weak socket] in
            guard let socket else { return }
            do {
                while !Task.isCancelled {
                    let value = try await socket.receive()
                    guard !Task.isCancelled, self?.sockets[board]?.task === socket else { return }
                    let data: Data
                    switch value { case .string(let string): data = Data(string.utf8); case .data(let bytes): data = bytes; @unknown default: continue }
                    if let frame = try JSONSerialization.jsonObject(with: data) as? [String: Any] { self?.event(["type": "chat", "board": board, "contextKey": context, "data": frame]) }
                }
            } catch {
                if !Task.isCancelled, self?.sockets[board]?.task === socket {
                    self?.sockets.removeValue(forKey: board)
                    if socket.closeCode.rawValue == 4001 { if let self { self.client.credentials.clear(origin: self.client.origin); self.currentUser = nil; self.event(["type": "authExpired"]) } }
                    else { self?.event(["type": "chatError", "board": board, "contextKey": context, "error": "与专家的连接已断开。已有回答保存在 Octop，重新打开可继续。"] ) }
                }
            }
        }
        return socket
    }
    private func closeSocket(_ board: String) { approvalEpoch[board,default:0] += 1;approvalHeaders.removeValue(forKey:board)?.task.cancel();approvalStreams.removeValue(forKey:board)?.task.cancel(); receiveLoops.removeValue(forKey: board)?.cancel(); sockets.removeValue(forKey: board)?.task.cancel(with: .goingAway, reason: nil) }
    private func closeSockets() { for board in Set(sockets.keys).union(approvalStreams.keys).union(approvalHeaders.keys) { closeSocket(board) } }

    private func showFullOctop(path: String, login: Bool) {
        guard path.hasPrefix("/"), !path.hasPrefix("//"), !path.contains("\\"), let url = URL(string: path, relativeTo: client.origin)?.absoluteURL, EndpointPolicy.sameOrigin(url, client.origin) else { return }
        loginMode = login
        chatWindow.orderOut(nil); sizingWindow?.orderOut(nil)
        if authWindow == nil {
            let config = WKWebViewConfiguration()
            config.userContentController.add(self, name: "authCallback")
            authView = WKWebView(frame: .zero, configuration: config)
            authView!.navigationDelegate = self; authView!.uiDelegate = self
            authWindow = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 950, height: 720), styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
            authWindow!.contentView = authView!; authWindow!.isReleasedWhenClosed = false; authWindow!.delegate = self; authWindow!.level = .floating; authWindow!.center()
        }
        authWindow!.title = login ? "哆啦 · 企业飞书登录" : "哆啦 · 资源与模型设置"
        authView!.configuration.userContentController.removeAllUserScripts()
        let originJSON = jsonString(client.origin.absoluteString)
        let tokenJSON = jsonString(client.credentials.read(origin: client.origin) ?? "")
        let script = """
        if (window.location.origin === \(originJSON)) {
          window.__DORA_CLIENT__ = true;
          const saved = \(tokenJSON);
          if (saved && !localStorage.getItem('auth_token') && !sessionStorage.getItem('auth_token')) localStorage.setItem('auth_token',saved);
          let previous = '';
          setInterval(() => { const token = localStorage.getItem('auth_token') || sessionStorage.getItem('auth_token') || ''; if (token && token !== previous) { previous = token; window.webkit.messageHandlers.authCallback.postMessage(token); } }, 900);
        }
        """
        authView!.configuration.userContentController.addUserScript(WKUserScript(source: script, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        authView!.load(URLRequest(url: url)); NSApp.activate(ignoringOtherApps: true); authWindow!.makeKeyAndOrderFront(nil)
    }
    private func jsonString(_ value: String) -> String { let data = try! JSONSerialization.data(withJSONObject: [value]); return String(data: data, encoding: .utf8)!.dropFirst().dropLast().description }
    private func acceptLoginToken(_ token: String, revision: Int) async {
        let origin = client.origin
        guard let user = try? await client.user(token: token), origin == client.origin, revision == loginRevision else { return }
        let old = currentUser?["id"] as? Int
        do { try client.credentials.save(token, origin: origin) } catch { return }
        currentUser = user
        if loginMode { authWindow?.orderOut(nil); loginMode = false; showChat() }
        if old != user["id"] as? Int { closeSockets(); speech.stopRecognition(); speech.stopSpeaking(); event(["type": "authChanged"]) }
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if webView === chatView {
            if url.isFileURL && url.standardizedFileURL.path == Bundle.main.resourceURL!.appendingPathComponent("web/index.html").standardizedFileURL.path { decisionHandler(.allow) }
            else { decisionHandler(.cancel); if ["http", "https"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) } }
        } else { decisionHandler(["http", "https", "about"].contains(url.scheme ?? "") ? .allow : .cancel) }
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url, ["http", "https"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        return nil
    }
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        if webView === chatView { panel.allowedContentTypes = CompanionUploadPolicy.extensions.compactMap { UTType(filenameExtension:$0) } }
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.begin { response in completionHandler(response == .OK ? panel.urls : nil) }
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard webView === chatView else { return }
        if ProcessInfo.processInfo.arguments.contains("--capture-ui"), capturesRemaining == 0 {
            capturesRemaining = 1
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in self?.captureMiniUI() }
        }
    }
    private func captureMiniUI() {
        guard let index = ProcessInfo.processInfo.arguments.firstIndex(of: "--capture-ui"), index + 1 < ProcessInfo.processInfo.arguments.count else { return }
        let path = ProcessInfo.processInfo.arguments[index + 1]
        chatView.takeSnapshot(with: nil) { image, _ in
            guard let image, let tiff = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff), let png = bitmap.representation(using: .png, properties: [:]) else { return }
            try? png.write(to: URL(fileURLWithPath: path))
        }
    }
}

@main
struct Main {
    @MainActor static func main() {
        if ProcessInfo.processInfo.arguments.contains("--self-test") {
            do {
                for value in ["http://127.0.0.1:8088", "https://localhost:8443", "http://[::1]:8088"] { _ = try EndpointPolicy.origin(value) }
                for value in ["https://example.com", "http://127.0.0.1:8088/evil", "file:///tmp", "http://user:password@localhost:8088"] { if (try? EndpointPolicy.origin(value)) != nil { fatalError("Untrusted origin accepted") } }
                let origin = try EndpointPolicy.origin("http://127.0.0.1:8088")
                for value in ["/api/../secret", "/api/%2e%2e/secret", "//example.com/api/auth/me", "/api/%252e%252e/secret", "/api/agents\\evil"] { if (try? EndpointPolicy.api(value, origin: origin)) != nil { fatalError("Unsafe path accepted") } }
                _ = try EndpointPolicy.api("/api/auth/me", origin: origin)
                PetSizing.selfTest()
                let sessions = CredentialStore()
                let other = try EndpointPolicy.origin("http://localhost:8089")
                precondition(sessions.read(origin: origin) == nil)
                try sessions.save("fixture-session", origin: origin)
                precondition(sessions.read(origin: origin) == "fixture-session")
                precondition(sessions.read(origin: other) == nil)
                precondition(CredentialStore().read(origin: origin) == nil)
                sessions.clear(origin: origin)
                precondition(sessions.read(origin: origin) == nil)
                for action in ["open", "size"] { precondition(CompanionLaunchAction(url: URL(string: "octop-companion://\(action)")!) != nil) }
                for url in ["octop-companion://open?token=bad", "octop-companion://size/evil", "octop-companion://open#token", "octop-companion://user@open", "https://open", "octop-companion://login"] { precondition(CompanionLaunchAction(url: URL(string: url)!) == nil) }
                let manifest = try JSONDecoder().decode(PetManifest.self, from: Data(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("Pet/pet.json")))
                for animation in manifest.animations.values { guard !animation.frames.isEmpty else { fatalError("Empty animation") } }
                PetEdgeDocking.selfTest(); CompanionWindowPlacement.selfTest()
                var flight = PetDragMotion()
                flight.begin(at: 10)
                precondition(flight.presentation(activity: "working") == "takeoff")
                flight.advance(at: 10.2)
                precondition(flight.phase == .takeoff)
                flight.advance(at: 10.4)
                precondition(flight.presentation(activity: "listening") == "dragging")
                precondition(flight.lift(at: 10.5, reducedMotion: true) == 0)
                flight.release(at: 11)
                precondition(flight.presentation(activity: "speaking") == "landing")
                flight.advance(at: 11.4)
                precondition(flight.presentation(activity: "speaking") == "speaking")
                print("{\"endpoint_policy\":\"passed\",\"session_only_credentials\":\"passed\",\"launcher_policy\":\"passed\",\"continuous_sizing_geometry\":\"passed\",\"pet_states\":\(manifest.animations.count),\"speech_voices\":\(AVSpeechSynthesisVoice.speechVoices().count),\"microphone_requested\":false}")
                exit(0)
            } catch { fputs("Self test failed: \(error.localizedDescription)\n", stderr); exit(1) }
        }
        if ProcessInfo.processInfo.arguments.contains("--acceptance-probe") || ProcessInfo.processInfo.arguments.contains("--preflight") || ProcessInfo.processInfo.arguments.contains("--inspect-test-thread") {
            let args = ProcessInfo.processInfo.arguments
            let imagePath = args.firstIndex(of: "--probe-image").flatMap { $0 + 1 < args.count ? args[$0 + 1] : nil }
            Task {
                let engine = EngineRuntime(dataName: "Acceptance")
                do {
                    let origin = try await engine.start()
                    var report: [String: Any]
                    if let index = args.firstIndex(of: "--inspect-test-thread"), index + 1 < args.count { report = try await AcceptanceProbe.inspectTestThread(args[index + 1], origin: origin) }
                    else if args.contains("--preflight") { report = try await AcceptanceProbe.preflight(origin: origin) }
                    else { report = try await AcceptanceProbe.run(imagePath: imagePath, origin: origin) }
                    if args.contains("--restart-check") {
                        engine.stop()
                        let secondOrigin = try await engine.start()
                        guard origin == secondOrigin else { throw CompanionError.unavailable("重启后未保留本机引擎地址。") }
                        report["restart_keeps_origin"] = true
                    }
                    let bytes = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
                    print(String(data: bytes, encoding: .utf8)!); engine.stop(); exit(0)
                } catch { engine.stop(); fputs("Acceptance probe: \(error.localizedDescription)\n", stderr); exit(1) }
            }
            RunLoop.main.run(); return
        }
        let ownPid = ProcessInfo.processInfo.processIdentifier
        if let running = NSRunningApplication.runningApplications(withBundleIdentifier: "com.chaoyangrao.octop.companion").first(where: { $0.processIdentifier != ownPid }) {
            running.activate(options: [.activateIgnoringOtherApps]); exit(0)
        }
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        let delegate = CompanionApp(); app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
