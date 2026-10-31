import SwiftUI

@main
struct OctopMobileApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = AppModel.shared
    var body: some Scene { WindowGroup { MobileRootView(model: model) } }
}

struct MobileRootView: View {
    @ObservedObject var model: AppModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var address = ""
    @State private var notificationSettings = false
    @State private var selectedShare: SharedDraft?
    @State private var taskAction: TaskActionLink?
    var body: some View {
        NavigationStack {
            Group {
                if let server = model.selected, let token = model.token(for: server) {
                    WorkspaceView(server: server, token: token, routePath: model.routePath, model: model).id(server.id)
                        .navigationTitle("Octop")
                        .navigationBarTitleDisplayMode(.inline)
                        .toolbar {
                            ToolbarItem(placement: .topBarLeading) { Button(L("native_servers")) { model.selected = nil } }
                            ToolbarItem(placement: .topBarTrailing) {
                                Menu {
                                    Button(L("native_enable_notifications")) { Task { await model.enableNotifications() } }.disabled(!server.allows("notifications"))
                                    if !model.pendingShares.isEmpty {
                                        Menu(L("native_shared_drafts")) {
                                            ForEach(model.pendingShares) { draft in
                                                Button(draft.text.isEmpty ? draft.files.map(\.filename).joined(separator: ", ") : String(draft.text.prefix(40))) { selectedShare = draft }
                                            }
                                        }
                                    }
                                    Button(L("native_notification_preferences")) { notificationSettings = true }.disabled(!server.allows("notifications"))
                                    Toggle(L("native_live_activities"), isOn: $model.liveActivities).disabled(!server.allows("notifications"))
                                    Button(L("native_revoke_this_device"), role: .destructive) { Task { await model.forget(server) } }
                                } label: { Image(systemName: "ellipsis.circle") }
                            }
                        }
                        .sheet(isPresented: $notificationSettings) { NotificationSettingsView(server: server, model: model) }
                        .task(id: scenePhase) {
                            if scenePhase == .active { await NotificationReader.listen(server: server, token: token, model: model) }
                        }
                } else {
                    Form {
                        Section(L("native_language")) {
                            Picker(L("native_language"), selection: $model.localeMode) {
                                Text(L("native_follow_account")).tag("account")
                                Text("中文").tag("zh")
                                Text("English").tag("en")
                            }
                        }
                        Section(L("native_connect_a_server")) {
                            TextField("https://your-octop.example", text: $address)
                                .textInputAutocapitalization(.never).keyboardType(.URL).autocorrectionDisabled()
                            Button(L("native_request_pairing")) { model.pair(address: address) }.disabled(model.pairing || address.isEmpty)
                            Text(L("native_approve_this_device_from_an_already_signed_in_comput")).font(.footnote).foregroundStyle(.secondary)
                        }
                        if let challenge = model.challenge {
                            Section(L("native_enter_on_your_computer")) {
                                Text(challenge.userCode).font(.system(.largeTitle, design: .monospaced)).textSelection(.enabled)
                                Text(challenge.hostFingerprint).font(.caption.monospaced()).textSelection(.enabled)
                                ProgressView(L("native_waiting_for_approval"))
                                Button(L("native_cancel")) { model.cancelPairing() }
                            }
                        }
                        if !model.pendingShares.isEmpty {
                            Section(L("native_shared_drafts")) {
                                ForEach(model.pendingShares) { draft in
                                    Button { selectedShare = draft } label: { Text(draft.text.isEmpty ? draft.files.map(\.filename).joined(separator: ", ") : String(draft.text.prefix(60))) }
                                }
                            }
                        }
                        Section(L("native_paired_servers")) {
                            ForEach(model.servers) { server in
                                Button { model.connect(server) } label: {
                                    VStack(alignment: .leading) {
                                        Text((server.baseURL.host ?? "Octop") + (server.accountLabel.map { " · " + $0 } ?? ""))
                                        Text(server.baseURL.absoluteString).font(.caption).foregroundStyle(.secondary)
                                    }
                                }.swipeActions { Button(L("native_revoke"), role: .destructive) { Task { await model.forget(server) } } }
                            }
                        }
                    }.navigationTitle("Octop")
                }
            }
        }
        .task { await model.refreshShares(); await model.refreshShareAccounts() }
        .onChange(of: scenePhase) { _, phase in if phase == .active { Task { await model.refreshShares() } } }
        .sheet(item: $selectedShare) { draft in ShareComposerView(original: draft) { selectedShare = nil; Task { await model.refreshShares() } } }
        .sheet(item: $taskAction) { link in TaskActionReview(server: link.server, navigation: link.navigation, model: model) { taskAction = nil } }
        .environment(\.locale, Locale(identifier: NativeStrings.language))
        .onOpenURL { url in
            let parts = url.pathComponents.filter { $0 != "/" }
            if url.scheme == "octop-mobile", url.host == "activity", parts.count == 3 {
                var event: [String: Any] = ["server_fingerprint": parts[0], "agent_id": parts[1], "thread_id": parts[2]]
                if let device = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first(where: { $0.name == "device" })?.value, !device.isEmpty { event["device_id"] = device }
                model.openNotification(event)
            } else if url.scheme == "octop-mobile", url.host == "task-action", parts.count == 3,
                      let server = model.servers.first(where: { $0.fingerprint == parts[0] && $0.deviceID == parts[1] }),
                      parts[2].count < 2049, parts[2].range(of: "^[A-Za-z0-9_.-]+$", options: .regularExpression) != nil {
                taskAction = TaskActionLink(server: server, navigation: parts[2])
            }
        }
        .alert("Octop", isPresented: Binding(get: { model.errorMessage != nil }, set: { if !$0 { model.errorMessage = nil } })) {
            Button(L("native_ok")) { model.errorMessage = nil }
        } message: { Text(model.errorMessage ?? "") }
    }
}


struct TaskActionLink: Identifiable {
    let id = UUID()
    let server: PairedServer
    let navigation: String
}
struct TaskActionReview: View {
    let server: PairedServer
    let navigation: String
    @ObservedObject var model: AppModel
    let closed: () -> Void
    @State private var confirmation: String?
    @State private var title = ""
    @State private var attempt = 0
    @State private var busy = false
    @State private var message: String?
    var body: some View {
        NavigationStack {
            Form {
                Text(server.accountLabel ?? server.baseURL.host ?? "Octop")
                if !title.isEmpty { Text(title).font(.headline); Text(L("native_task_attempt", attempt)) }
                Text(L("native_cancel_review_notice"))
                if let message { Text(message) }
                if confirmation != nil {
                    Button(L("native_confirm_cancel"), role: .destructive) { Task { await execute() } }.disabled(busy)
                }
            }.navigationTitle(L("native_review_cancel"))
            .toolbar { Button(L("native_close")) { closed() }.disabled(busy) }
            .task { await prepare() }
        }
    }
    private func prepare() async {
        guard let token = model.token(for: server) else { message = L("native_re_pair_this_device"); return }
        do {
            let data = try await ServerAPI.shared.request(base: server.baseURL, path: "/api/mobile-access/task-actions/prepare", body: ["navigation": navigation], token: token)
            let result = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            title = result?["title"] as? String ?? ""; attempt = result?["attempt"] as? Int ?? 0
            confirmation = result?["confirmation"] as? String
        } catch { message = L("native_action_stale") }
    }
    private func execute() async {
        guard let proof = confirmation, let token = model.token(for: server) else { return }
        confirmation = nil; busy = true; defer { busy = false }
        do {
            _ = try await ServerAPI.shared.request(base: server.baseURL, path: "/api/mobile-access/task-actions/execute", body: ["confirmation": proof], token: token)
            message = L("native_task_cancelled")
        } catch { message = L("native_action_unknown") }
    }
}
