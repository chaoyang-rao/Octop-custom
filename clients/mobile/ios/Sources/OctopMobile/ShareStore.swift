import CryptoKit
import Foundation
import Security

struct ShareAccount: Codable, Identifiable {
    let server: PairedServer
    let credential: String
    let scopes: [String]
    var id: String { server.id }
}
struct SharedFile: Codable, Identifiable {
    var id: String { filename }
    var filename: String
    var mime: String
    var data: Data
}
struct SharedDraft: Codable, Identifiable {
    var id = UUID().uuidString
    var text: String
    var files: [SharedFile]
    var accountID: String?
    var agentID: String?
    var state = "draft"
    var taskID: String?
}

enum ShareStore {
    enum Failure: Error { case unavailable, invalid }
    private static var group: String? { Bundle.main.object(forInfoDictionaryKey: "OctopShareKeychainGroup") as? String }
    private static func query(_ account: String) throws -> [String: Any] {
        guard let group, !group.isEmpty else { throw Failure.unavailable }
        return [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "com.octop.mobile.share-v1",
                kSecAttrAccount as String: account, kSecAttrAccessGroup as String: group]
    }
    private static func read(_ account: String) throws -> Data? {
        var query = try query(account); query[kSecReturnData as String] = true; query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?; let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw Failure.unavailable }
        return result as? Data
    }
    private static func write(_ data: Data, account: String) throws {
        let selector = try query(account)
        let changed = SecItemUpdate(selector as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if changed == errSecSuccess { return }
        guard changed == errSecItemNotFound else { throw Failure.unavailable }
        var added = selector; added[kSecValueData as String] = data
        added[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        guard SecItemAdd(added as CFDictionary, nil) == errSecSuccess else { throw Failure.unavailable }
    }
    static func accounts() throws -> [ShareAccount] {
        guard let data = try read("accounts") else { return [] }
        return try JSONDecoder().decode([ShareAccount].self, from: data)
    }
    static func accounts(_ value: [ShareAccount]) throws { try write(JSONEncoder().encode(value), account: "accounts") }
    static func removeAccount(_ id: String) { if let accounts = try? accounts() { try? self.accounts(accounts.filter { $0.id != id }) } }
    private static func draftKey() throws -> SymmetricKey {
        if let data = try read("draft-key"), data.count == 32 { return SymmetricKey(data: data) }
        var query = try query("draft-key")
        let key = SymmetricKey(size: .bits256).withUnsafeBytes { Data($0) }
        query[kSecValueData as String] = key; query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let result = SecItemAdd(query as CFDictionary, nil)
        if result == errSecSuccess { return SymmetricKey(data: key) }
        if result == errSecDuplicateItem, let existing = try read("draft-key") { return SymmetricKey(data: existing) }
        throw Failure.unavailable
    }
    private static func directory() throws -> URL {
        guard let group = Bundle.main.object(forInfoDictionaryKey: "OctopShareAppGroup") as? String,
              let container = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: group) else { throw Failure.unavailable }
        let directory = container.appendingPathComponent("pending-shares", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }
    static func save(_ draft: SharedDraft) throws {
        let body = try JSONEncoder().encode(draft)
        let sealed = try AES.GCM.seal(body, using: draftKey(), nonce: AES.GCM.Nonce(), authenticating: Data(draft.id.utf8))
        guard let data = sealed.combined else { throw Failure.invalid }
        try data.write(to: directory().appendingPathComponent(draft.id + ".sealed"), options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }
    static func drafts() throws -> [SharedDraft] {
        let directory = try directory(), key = try draftKey()
        return try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil).compactMap { file in
            guard file.pathExtension == "sealed" else { return nil }
            let id = file.deletingPathExtension().lastPathComponent
            let data = try Data(contentsOf: file)
            let plain = try AES.GCM.open(AES.GCM.SealedBox(combined: data), using: key, authenticating: Data(id.utf8))
            return try JSONDecoder().decode(SharedDraft.self, from: plain)
        }
    }
    static func removeDraft(_ id: String) throws {
        guard UUID(uuidString: id) != nil else { throw Failure.invalid }
        try FileManager.default.removeItem(at: directory().appendingPathComponent(id + ".sealed"))
    }
}
