import CryptoKit
import Foundation
import Security

struct NotificationEnvelope {
    enum Failure: Error { case invalid, recipient, expired, replay, routing }
    static let fields = ["seal_version", "host_fingerprint", "device_id", "agent_id", "thread_id", "issued_at", "expires_at", "message_id"]
    static func key(credential: String) -> SymmetricKey {
        let material = SymmetricKey(data: Data(SHA256.hash(data: Data(credential.utf8))))
        return HKDF<SHA256>.deriveKey(inputKeyMaterial: material,
             salt: Data("octop-mobile-notifications-salt-v1".utf8),
             info: Data("octop/mobile/notification-content/v1".utf8), outputByteCount: 32)
    }
    static func aad(_ envelope: [String: String]) throws -> Data {
        var data = Data()
        for field in fields {
            guard let value = envelope[field] else { throw Failure.invalid }
            let bytes = Data(value.utf8)
            var size = UInt32(bytes.count).bigEndian
            data.append(Data(bytes: &size, count: 4)); data.append(bytes)
        }
        return data
    }
    static func open(_ envelope: [String: String], key: SymmetricKey, host: String, device: String,
                     now: Int, seen: inout Set<String>) throws -> [String: Any] {
        guard envelope["seal_version"] == "1", envelope["host_fingerprint"] == host,
              envelope["device_id"] == device else { throw Failure.recipient }
        guard let sealed = envelope["sealed"], let combined = Data(base64Encoded: sealed.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")) else { throw Failure.invalid }
        let box = try AES.GCM.SealedBox(combined: combined)
        let decrypted = try AES.GCM.open(box, using: key, authenticating: try aad(envelope))
        guard let issued = Int(envelope["issued_at"] ?? ""), let expiry = Int(envelope["expires_at"] ?? ""),
              issued <= now + 60, expiry > now, expiry > issued, expiry - issued <= 300 else { throw Failure.expired }
        guard let message = envelope["message_id"], !seen.contains(message) else { throw Failure.replay }
        guard let payload = try JSONSerialization.jsonObject(with: decrypted) as? [String: Any],
              let routing = payload["octop"] as? [String: Any],
              (routing["agent_id"] as? String ?? "") == envelope["agent_id"],
              (routing["thread_id"] as? String ?? "") == envelope["thread_id"] else { throw Failure.routing }
        seen.insert(message)
        return payload
    }
}

struct NotificationKeyStore {
    static let service = "com.octop.mobile.notification-key-v1"
    private static var group: String? { Bundle.main.object(forInfoDictionaryKey: "OctopSharedKeychainGroup") as? String }
    static func store(credential: String, account: String) {
        guard let group, !group.isEmpty else { return }
        remove(account: account)
        let key = NotificationEnvelope.key(credential: credential).withUnsafeBytes { Data($0) }
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
           kSecAttrService as String: service, kSecAttrAccount as String: account,
           kSecAttrAccessGroup as String: group,
           kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
           kSecValueData as String: key]
        SecItemAdd(query as CFDictionary, nil)
    }
    static func read(account: String) -> SymmetricKey? {
        guard let group, !group.isEmpty else { return nil }
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
           kSecAttrService as String: service, kSecAttrAccount as String: account,
           kSecAttrAccessGroup as String: group, kSecReturnData as String: true,
           kSecMatchLimit as String: kSecMatchLimitOne]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let key = result as? Data, key.count == 32 else { return nil }
        return SymmetricKey(data: key)
    }
    static func remove(account: String) {
        guard let group, !group.isEmpty else { return }
        SecItemDelete([kSecClass as String: kSecClassGenericPassword,
                      kSecAttrService as String: service, kSecAttrAccount as String: account,
                      kSecAttrAccessGroup as String: group] as CFDictionary)
    }
}
