import Foundation
import Security

struct KeychainStore {
    private static let service = "com.octop.mobile.device-session"
    static func save(_ token: String, account: String) throws {
        delete(account: account)
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service, kSecAttrAccount as String: account,
                                    kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
                                    kSecValueData as String: Data(token.utf8)]
        guard SecItemAdd(query as CFDictionary, nil) == errSecSuccess else {
            throw MobileClientError(message: L("native_could_not_save_the_device_credential"))
        }
        NotificationKeyStore.store(credential: token, account: account)
    }
    static func read(account: String) -> String? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service, kSecAttrAccount as String: account,
                                    kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }
    static func delete(account: String) {
        NotificationKeyStore.remove(account: account)
        SecItemDelete([kSecClass as String: kSecClassGenericPassword,
                       kSecAttrService as String: service, kSecAttrAccount as String: account] as CFDictionary)
    }
}
