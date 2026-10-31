import Foundation
import SwiftUI

struct ShareComposerView: View {
    let original: SharedDraft
    let completed: () -> Void
    @State private var accounts: [ShareAccount] = []
    @State private var accountID = ""
    @State private var agentID = ""
    @State private var experts: [MobileAgentLabel] = []
    @State private var text = ""
    @State private var busy = false
    @State private var canSend = false
    @State private var info: String?
    @State private var uncertain = false
    @State private var draftState = "draft"
    @State private var lastTaskID: String?
    @State private var loadGeneration = 0
    @State private var language = NativeStrings.language
    var body: some View {
        NavigationStack {
            Form {
                if accounts.isEmpty { Text(L("native_open_octop_and_pair_a_server_first")) }
                Picker(L("native_server"), selection: $accountID) {
                    ForEach(accounts) { account in Text((account.server.baseURL.host ?? "Octop") + (account.server.accountLabel.map { " · " + $0 } ?? "")).tag(account.id) }
                }
                Picker(L("native_expert"), selection: $agentID) { ForEach(experts) { Text($0.name).tag($0.agentID) } }
                TextEditor(text: $text).frame(minHeight: 100)
                ForEach(Array(original.files.enumerated()), id: \.offset) { _, file in Text(file.filename).font(.footnote) }
                Text(L("native_sharing_uses_a_separate_background_conversation_and_")).font(.footnote).foregroundStyle(.secondary)
                if !canSend { Text(L("native_without_task_permission_save_an_encrypted_draft_for_")).font(.footnote) }
                if let info { Text(info).foregroundStyle(uncertain ? Color.orange : Color.secondary) }
            }
            .disabled(busy)
            .environment(\.locale, Locale(identifier: language))
            .navigationTitle(L("native_share_to_octop"))
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(L("native_close")) { completed() }.disabled(busy) }
                ToolbarItem(placement: .bottomBar) {
                    HStack {
                        Button(L("native_save_draft")) { saveDraft() }.disabled(busy)
                        Spacer()
                        Button(L("native_send_background_task")) { Task { await send() } }.disabled(busy || !canSend || agentID.isEmpty || uncertain || draftState == "sent")
                    }
                }
            }
            .task {
                text = original.text; draftState = original.state; lastTaskID = original.taskID; uncertain = original.state == "unknown"
                accounts = (try? ShareStore.accounts()) ?? []
                accountID = original.accountID ?? accounts.first?.id ?? ""
                agentID = original.agentID ?? ""
                if uncertain { info = L("native_check_the_task_list_before_sending_again") }
                await loadExperts()
            }
            .onChange(of: accountID) { _, _ in Task { await loadExperts() } }
        }
    }
    private var account: ShareAccount? { accounts.first { $0.id == accountID } }
    private func loadExperts() async {
        guard let account else { return }
        loadGeneration += 1; let generation = loadGeneration
        canSend = false
        NativeStrings.accountLanguage(account.server.locale ?? NativeStrings.systemLanguage)
        do {
            let data = try await ServerAPI.shared.request(base: account.server.baseURL, path: "/api/mobile-access/share/experts", method: "GET", token: account.credential)
            guard generation == loadGeneration, accountID == account.id else { return }
            experts = try JSONDecoder().decode([MobileAgentLabel].self, from: data)
            if !experts.contains(where: { $0.agentID == agentID }) { agentID = experts.first?.agentID ?? "" }
            let profileData = try await ServerAPI.shared.request(base: account.server.baseURL, path: "/api/auth/me", method: "GET", token: account.credential)
            let profile = try JSONSerialization.jsonObject(with: profileData) as? [String: Any]
            guard generation == loadGeneration, accountID == account.id else { return }
            NativeStrings.accountLanguage(profile?["locale"] as? String ?? account.server.locale ?? "en"); language = NativeStrings.language
            canSend = account.scopes.contains("tasks") && ((profile?["permissions"] as? [String]) ?? []).contains("tasks")
        } catch { canSend = false; info = L("native_could_not_load_experts_local_drafts_remain_available") }
    }
    private func snapshot() -> SharedDraft {
        var draft = original; draft.text = text; draft.accountID = accountID; draft.agentID = agentID; draft.state = draftState; draft.taskID = lastTaskID
        return draft
    }
    private func saveDraft() {
        do { try ShareStore.save(snapshot()); info = L("native_encrypted_draft_saved_for_octop") }
        catch { info = L("native_check_app_signing_and_the_shared_container") }
    }
    private func send() async {
        guard let account, canSend, !agentID.isEmpty else { return }
        let targetAgent = agentID
        let targetText = text
        busy = true; defer { busy = false }
        var draft = snapshot()
        do {
            guard original.files.count <= 10, original.files.reduce(0, { $0 + $1.data.count }) <= 10 * 1024 * 1024 else { throw ShareStore.Failure.invalid }
            try ShareStore.save(draft)
            var attachments: [[String: Any]] = []
            for file in original.files {
                let result = try await ServerAPI.shared.upload(base: account.server.baseURL, agentID: targetAgent, file: file, token: account.credential)
                attachments.append(["workspace_path": result["workspace_path"] ?? result["path"] ?? "", "filename": file.filename, "mime_type": result["media_type"] ?? file.mime, "size": file.data.count, "upload_receipt": result["upload_receipt"] ?? ""])
            }
            let prompt = targetText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? L("native_analyze_the_shared_attachments") : targetText
            // Persist the unknown-outcome guard before POST; never auto-retry this request.
            draft.state = "unknown"; draftState = "unknown"; try ShareStore.save(draft); uncertain = true
            let response = try await ServerAPI.shared.request(base: account.server.baseURL, path: "/api/tasks", body: ["agent_id": targetAgent, "title": String(prompt.prefix(80)), "prompt": prompt, "attachments": attachments], token: account.credential)
            let result = try JSONSerialization.jsonObject(with: response) as? [String: Any]
            draft.taskID = result?["task_id"] as? String ?? result?["id"] as? String
            draft.state = "sent"; draftState = "sent"; uncertain = false; lastTaskID = draft.taskID
            try? ShareStore.save(draft)
            try? ShareStore.removeDraft(draft.id)
            info = L("native_queued_view_the_result_in_octop")
        } catch {
            if let failure = error as? MobileClientError, let code = failure.statusCode, [400, 401, 403, 404, 409, 413, 422].contains(code) {
                draft.state = "draft"; draftState = "draft"; uncertain = false
                try? ShareStore.save(draft)
            }
            if draft.state != "unknown" { uncertain = false }
            info = uncertain ? L("native_outcome_unknown_draft_retained_check_tasks_before_re") : L("native_could_not_send_draft_retained")
        }
    }
}
