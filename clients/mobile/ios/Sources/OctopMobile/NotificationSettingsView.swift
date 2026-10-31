import Foundation
import SwiftUI

struct NotificationSettingsView: View {
    let server: PairedServer
    @ObservedObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var preferences = DeviceNotificationPreferences()
    @State private var agents: [MobileAgentLabel] = []
    @State private var timezone: String?
    @State private var saving = false
    @State private var previewConsent = false
    @State private var errorText: String?
    var body: some View {
        NavigationStack {
            Form {
                Section(L("native_notification_level")) {
                    Picker(L("native_notify"), selection: $preferences.level) {
                        Text(L("native_all")).tag("all")
                        Text(L("native_needs_me")).tag("needs-me")
                        Text(L("native_none")).tag("none")
                    }
                    Menu(L("native_mute")) {
                        Button(L("native_unmute")) { preferences.mutedUntil = nil }
                        Button(L("native_15_minutes")) { mute(900) }
                        Button(L("native_1_hour")) { mute(3600) }
                        Button(L("native_8_hours")) { mute(28800) }
                        Button(L("native_until_unmuted")) { preferences.mutedUntil = 0 }
                    }
                    Text(muteLabel).font(.footnote).foregroundStyle(.secondary)
                    Toggle(L("native_notification_sound"), isOn: $preferences.sound)
                    Toggle(L("native_show_filtered_previews"), isOn: Binding(get: { preferences.preview }, set: { if $0 { previewConsent = true } else { preferences.preview = false } }))
                    Text(L("native_previews_are_off_by_default_and_never_include_tool_a")).font(.footnote).foregroundStyle(.secondary)
                }
                if !agents.isEmpty {
                    Section(L("native_expert_notifications")) {
                        ForEach(agents) { agent in
                            Toggle(agent.name, isOn: Binding(get: { !preferences.mutedAgentIDs.contains(agent.agentID) }, set: { enabled in
                                preferences.mutedAgentIDs.removeAll { $0 == agent.agentID }
                                if !enabled { preferences.mutedAgentIDs.append(agent.agentID) }
                            }))
                        }
                    }
                }
                if let errorText { Text(errorText).foregroundStyle(.red) }
            }
            .navigationTitle(L("native_notifications"))
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(L("native_cancel")) { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button(L("native_save")) { Task { await save() } }.disabled(saving) }
            }
            .task { await load() }
            .alert(L("native_enable_previews"), isPresented: $previewConsent) {
                Button(L("native_enable")) { preferences.preview = true }
                Button(L("native_cancel"), role: .cancel) {}
            } message: { Text(L("native_filtered_text_is_sent_to_your_push_provider_only_aft")) }
        }
    }
    private func mute(_ seconds: Int) { preferences.mutedUntil = Int(Date().timeIntervalSince1970) + seconds }
    private var muteLabel: String {
        guard let until = preferences.mutedUntil else { return L("native_not_muted") }
        if until == 0 { return L("native_muted_until_changed") }
        guard let timezone, let zone = TimeZone(identifier: timezone) else { return L("native_muted_timezone_unavailable") }
        let formatter = DateFormatter(); formatter.dateStyle = .short; formatter.timeStyle = .short
        formatter.locale = Locale(identifier: NativeStrings.language)
        formatter.timeZone = zone
        return L("native_muted_until") + formatter.string(from: Date(timeIntervalSince1970: TimeInterval(until)))
    }
    private func load() async {
        do {
            preferences = try await model.notificationPreferences(server: server)
            if let token = model.token(for: server) {
                if let data = try? await ServerAPI.shared.request(base: server.baseURL, path: "/api/agents", method: "GET", token: token) { agents = (try? JSONDecoder().decode([MobileAgentLabel].self, from: data)) ?? [] }
                if let data = try? await ServerAPI.shared.request(base: server.baseURL, path: "/api/settings/timezone", method: "GET", token: token), let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let zone = value["timezone"] as? String { timezone = zone }
            }
        } catch { errorText = L("native_could_not_read_preferences") }
    }
    private func save() async {
        saving = true; defer { saving = false }
        do { try await model.saveNotificationPreferences(preferences, server: server); dismiss() }
        catch { errorText = L("native_could_not_save_preferences") }
    }
}
