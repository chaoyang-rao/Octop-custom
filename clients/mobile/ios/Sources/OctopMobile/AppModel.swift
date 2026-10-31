import ActivityKit
import Foundation
import SwiftUI
import UIKit
import UserNotifications
import WebKit

@MainActor
final class AppModel: ObservableObject {
    static let shared = AppModel()
    @Published var localeMode = NativeStrings.mode { didSet { NativeStrings.mode = localeMode; localeRevision += 1 } }
    @Published var localeRevision = 0
    @Published var servers: [PairedServer] = []
    @Published var selected: PairedServer?
    @Published var routePath = "/"
    @Published var pendingShares: [SharedDraft] = []
    private var webStores: [String: WKWebsiteDataStore] = [:]
    @Published var challenge: PairingChallenge?
    @Published var errorMessage: String?
    @Published var pairing = false
    @Published var liveActivities = false {
        didSet {
            UserDefaults.standard.set(liveActivities, forKey: "octop.liveActivities")
            if !liveActivities { Task { await stopActivities() } }
        }
    }
    private var activityRevisions: [String: Int] = [:]
    private var revision = 0
    private var lastPushToken: Data?
    private var pairingTask: Task<Void, Never>?
    private var activities: [String: Activity<OctopActivityAttributes>] = [:]
    init() {
        liveActivities = UserDefaults.standard.bool(forKey: "octop.liveActivities")
        if let data = UserDefaults.standard.data(forKey: "octop.servers"), let decoded = try? JSONDecoder().decode([PairedServer].self, from: data) {
            servers = decoded
        }
    }
    func token(for server: PairedServer) -> String? { KeychainStore.read(account: server.id) }
    func connect(_ server: PairedServer) {
        reconcileActivities()
        NativeStrings.accountLanguage(server.locale ?? NativeStrings.systemLanguage)
        routePath = "/"; selected = server
        Task { await syncAccountProfile(server); await refreshShareAccounts(); if let lastPushToken { await registerPush(lastPushToken) } }
    }
    func syncAccountProfile(_ server: PairedServer) async {
        guard let credential = token(for: server),
              let data = try? await ServerAPI.shared.request(base: server.baseURL, path: "/api/auth/me", method: "GET", token: credential),
              let profile = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        var updated = server
        updated.locale = (profile["locale"] as? String ?? "en").hasPrefix("zh") ? "zh" : "en"
        updated.accountLabel = profile["display_name"] as? String ?? profile["username"] as? String
        if let index = servers.firstIndex(where: { $0.id == server.id }) { servers[index] = updated; persist() }
        if selected?.id == server.id { selected = updated; NativeStrings.accountLanguage(updated.locale ?? "en"); localeRevision += 1 }
    }
    func webStore(for server: PairedServer) -> WKWebsiteDataStore {
        if let existing = webStores[server.id] { return existing }
        let value = WKWebsiteDataStore.nonPersistent(); webStores[server.id] = value; return value
    }
    func openNotification(_ event: [String: Any]) {
        guard let fingerprint = event["server_fingerprint"] as? String,
              let server = servers.first(where: { $0.fingerprint == fingerprint && (event["device_id"] as? String == nil || $0.deviceID == event["device_id"] as? String) }) else { return }
        routePath = "/"
        if let agent = event["agent_id"] as? String, let thread = event["thread_id"] as? String,
           agent.range(of: "^[A-Za-z0-9_:-]+$", options: .regularExpression) != nil,
           thread.range(of: "^[A-Za-z0-9_:-]+$", options: .regularExpression) != nil {
            routePath = "/chat/\(agent)/\(thread)"
        }
        selected = server
        Task { await syncAccountProfile(server); await refreshShareAccounts(); if let lastPushToken { await registerPush(lastPushToken) } }
    }
    func pair(address: String) {
        guard !pairing else { return }
        pairingTask?.cancel()
        pairing = true
        errorMessage = nil
        pairingTask = Task {
            defer { pairing = false }
            do {
                let base = try ServerAPI.validatedURL(address)
                let challenge = try await ServerAPI.shared.begin(base: base, name: UIDevice.current.name)
                self.challenge = challenge
                while !Task.isCancelled && Int(Date().timeIntervalSince1970) < challenge.expiresAt {
                    try await Task.sleep(for: .seconds(max(3, challenge.interval)))
                    let result = try await ServerAPI.shared.exchange(base: base, challenge: challenge)
                    if result.status == "approved", let token = result.accessToken,
                       let deviceID = result.deviceID, result.hostFingerprint == challenge.hostFingerprint {
                        let server = PairedServer(baseURL: base, deviceID: deviceID, fingerprint: challenge.hostFingerprint, expiresAt: result.expiresAt, scopes: result.scopes)
                        try KeychainStore.save(token, account: server.id)
                        servers.removeAll { $0.id == server.id }
                        servers.append(server)
                        persist()
                        self.challenge = nil
                        selected = server
                        await syncAccountProfile(server)
                        await refreshShareAccounts()
                        if let lastPushToken { await registerPush(lastPushToken) }
                        return
                    }
                }
                if !Task.isCancelled { errorMessage = L("native_pairing_code_expired") }
            } catch is CancellationError { }
            catch { errorMessage = error.localizedDescription }
            challenge = nil
        }
    }
    func cancelPairing() { pairingTask?.cancel(); pairingTask = nil; challenge = nil; pairing = false }
    func forget(_ server: PairedServer, revoke: Bool = true) async {
        if revoke, let token = token(for: server) {
            do { _ = try await ServerAPI.shared.request(base: server.baseURL, path: "/api/mobile-access/self/revoke", token: token) }
            catch { errorMessage = L("native_revoke_on_the_desktop_if_the_server_is_unavailable"); return }
        }
        KeychainStore.delete(account: server.id)
        ShareStore.removeAccount(server.id)
        webStores.removeValue(forKey: server.id)
        servers.removeAll { $0.id == server.id }; persist()
        if selected == server { selected = nil }
    }
    func expired(_ server: PairedServer) {
        selected = nil
        KeychainStore.delete(account: server.id)
        ShareStore.removeAccount(server.id)
        errorMessage = L("native_re_pair_this_device")
    }
    func refreshShareAccounts() async {
        var records = (try? ShareStore.accounts()) ?? []
        let known = Set(servers.map(\.id)); records.removeAll { !known.contains($0.id) }
        for server in servers where server.allows("chat") {
            guard let token = token(for: server) else { records.removeAll { $0.id == server.id }; continue }
            do {
                let data = try await ServerAPI.shared.request(base: server.baseURL, path: "/api/mobile-access/self/share-grant", token: token)
                guard let value = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let credential = value["access_token"] as? String,
                      let scopes = value["scopes"] as? [String] else { continue }
                records.removeAll { $0.id == server.id }
                records.append(ShareAccount(server: server, credential: credential, scopes: scopes))
            } catch { /* Preserve an existing registration while a host is offline. */ }
        }
        try? ShareStore.accounts(records)
    }
    func refreshShares() async {
        pendingShares = (try? await Task.detached { try ShareStore.drafts() }.value) ?? []
    }
    private func persist() {
        if let data = try? JSONEncoder().encode(servers) { UserDefaults.standard.set(data, forKey: "octop.servers") }
    }
    func enableNotifications() async {
        do {
            let allowed = try await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound])
            if allowed { UIApplication.shared.registerForRemoteNotifications() }
        } catch { errorMessage = L("native_could_not_enable_notifications") }
    }
    func reportForeground(_ foreground: Bool, server: PairedServer) async {
        guard server.allows("notifications"), let credential = token(for: server) else { return }
        _ = try? await ServerAPI.shared.request(base: server.baseURL, path: "/api/mobile-access/self/notifications", method: "PUT", body: ["foreground": foreground], token: credential)
    }
    func notificationPreferences(server: PairedServer) async throws -> DeviceNotificationPreferences {
        guard let credential = token(for: server) else { throw MobileClientError(message: L("native_re_pair_this_device_7d841c")) }
        let data = try await ServerAPI.shared.request(base: server.baseURL, path: "/api/mobile-access/self", method: "GET", token: credential)
        return try JSONDecoder().decode(DevicePreferenceEnvelope.self, from: data).notificationPreferences
    }
    func saveNotificationPreferences(_ preferences: DeviceNotificationPreferences, server: PairedServer) async throws {
        guard let credential = token(for: server) else { throw MobileClientError(message: L("native_re_pair_this_device_7d841c")) }
        _ = try await ServerAPI.shared.request(base: server.baseURL, path: "/api/mobile-access/self/notifications", method: "PUT", body: preferences.body, token: credential)
    }
    func registerPush(_ token: Data) async {
        lastPushToken = token
        let hex = token.map { String(format: "%02x", $0) }.joined()
        for server in servers where server.allows("notifications") {
            guard let credential = self.token(for: server) else { continue }
            do { _ = try await ServerAPI.shared.request(base: server.baseURL, path: "/api/mobile-access/self/push", method: "PUT", body: ["platform": "apns", "token": hex], token: credential) }
            catch { errorMessage = L("native_push_registration_failed") }
        }
    }
    private func stopActivities() async {
        let running = Array(activities.values)
        activities.removeAll(); activityRevisions.removeAll()
        for activity in running { await activity.end(nil, dismissalPolicy: .immediate) }
        for server in servers {
            guard let credential = token(for: server) else { continue }
            _ = try? await ServerAPI.shared.request(base: server.baseURL, path: "/api/mobile-access/self/activity", method: "DELETE", token: credential)
        }
    }
    private func agentName(_ agentID: String, server: PairedServer) async -> String {
        guard agentID.range(of: "^[A-Za-z0-9_:-]+$", options: .regularExpression) != nil,
              let credential = token(for: server),
              let data = try? await ServerAPI.shared.request(base: server.baseURL, path: "/api/agents/\(agentID)", method: "GET", token: credential),
              let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let name = value["name"] as? String else { return "Octop" }
        return String(name.prefix(80))
    }
    func reconcileActivities() {
        activities = activities.filter { $0.value.activityState == .active || $0.value.activityState == .stale }
    }
    private func taskNavigation(_ value: [String: Any], server: PairedServer) async -> String? {
        guard server.allows("tasks"), let task = value["task_id"] as? String,
              let attempt = value["task_attempt"] as? Int, let credential = token(for: server),
              let data = try? await ServerAPI.shared.request(base: server.baseURL, path: "/api/mobile-access/task-actions/navigation", body: ["task_id": task, "attempt": attempt], token: credential),
              let result = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return result["navigation"] as? String
    }
    func handleStatus(_ value: [String: Any], source: PairedServer? = nil) {
        guard liveActivities, ActivityAuthorizationInfo().areActivitiesEnabled,
              let threadID = value["thread_id"] as? String, !threadID.isEmpty,
              let type = value["type"] as? String, let candidate = source ?? selected else { return }
        let server = servers.first(where: { $0.id == candidate.id }) ?? candidate
        guard server.allows("notifications") else { return }
        reconcileActivities()
        let activityKey = server.id + ":" + threadID
        let status: String
        switch type {
        case "turn.started", "turn.resumed": status = "working"
        case "approval.required", "hitl": status = "approval"
        case "error": status = "failed"
        case "turn.ended", "turn.completed": status = value["failed"] as? Bool == true || value["status"] as? String == "failed" ? "failed" : "complete"
        case "task.updated":
            switch value["status"] as? String {
            case "running", "queued": status = "working"
            case "waiting": status = "approval"
            case "paused": status = "paused"
            case "failed", "interrupted": status = "failed"
            case "completed", "cancelled": status = "complete"
            default: return
            }
        default: return
        }
        revision += 1
        let currentRevision = revision
        activityRevisions[activityKey] = currentRevision
        Task {
            let content = ActivityContent(state: OctopActivityAttributes.ContentState(status: status, updatedAt: Int(Date().timeIntervalSince1970), locale: server.locale ?? NativeStrings.language), staleDate: Date().addingTimeInterval(90))
            if let activity = activities[activityKey] {
                if status == "complete" || status == "failed" {
                    await activity.end(content, dismissalPolicy: .after(Date().addingTimeInterval(30)))
                    activities.removeValue(forKey: activityKey)
                } else { await activity.update(content) }
            } else if status == "working" && activities.count < 4 {
                do {
                    let navigation = await taskNavigation(value, server: server)
                    let name = await agentName(value["agent_id"] as? String ?? "", server: server)
                    guard activityRevisions[activityKey] == currentRevision, liveActivities else { return }
                    let activity = try Activity.request(attributes: OctopActivityAttributes(serverFingerprint: server.fingerprint, agentID: value["agent_id"] as? String ?? "", threadID: threadID, agentName: name, locale: server.locale ?? NativeStrings.language, deviceID: server.deviceID, actionNavigation: navigation), content: content, pushType: .token)
                    activities[activityKey] = activity
                    Task {
                        for await pushToken in activity.pushTokenUpdates {
                            guard let credential = self.token(for: server) else { return }
                            let hex = pushToken.map { String(format: "%02x", $0) }.joined()
                            do { _ = try await ServerAPI.shared.request(base: server.baseURL, path: "/api/mobile-access/self/activity", method: "PUT", body: ["activity_id": activity.id, "thread_id": threadID, "token": hex], token: credential) }
                            catch { /* Resource/configuration errors never expose tokens. */ }
                        }
                    }
                } catch { errorMessage = L("native_could_not_start_live_activity") }
            }
        }
    }
}

final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            if settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional {
                DispatchQueue.main.async { application.registerForRemoteNotifications() }
            }
        }
        return true
    }
    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        Task { @MainActor in await AppModel.shared.registerPush(deviceToken) }
    }
    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        Task { @MainActor in AppModel.shared.errorMessage = L("native_check_app_signing_and_apns") }
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        if let event = response.notification.request.content.userInfo["octop"] as? [String: Any] {
            Task { @MainActor in AppModel.shared.openNotification(event) }
        }
        completionHandler()
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
}
