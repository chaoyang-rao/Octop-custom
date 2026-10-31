import Darwin
import Foundation
import UserNotifications

final class NotificationService: UNNotificationServiceExtension {
    private var handler: ((UNNotificationContent) -> Void)?
    private var fallback: UNMutableNotificationContent?
    override func didReceive(_ request: UNNotificationRequest, withContentHandler contentHandler: @escaping (UNNotificationContent) -> Void) {
        handler = contentHandler
        guard let content = request.content.mutableCopy() as? UNMutableNotificationContent else { contentHandler(request.content); return }
        fallback = content.mutableCopy() as? UNMutableNotificationContent
        do {
            let envelope = Dictionary(uniqueKeysWithValues: request.content.userInfo.compactMap { key, value -> (String, String)? in
                guard let key = key as? String, let value = value as? String else { return nil }; return (key, value)
            })
            guard let host = envelope["host_fingerprint"], let device = envelope["device_id"],
                  let key = NotificationKeyStore.read(account: host + ":" + device) else { throw NotificationEnvelope.Failure.recipient }
            var seen = Set<String>()
            let now = Int(Date().timeIntervalSince1970)
            let payload = try NotificationEnvelope.open(envelope, key: key, host: host, device: device, now: now, seen: &seen)
            guard ReplayCache.accept(host: host, device: device, message: envelope["message_id"] ?? "", expiry: Int(envelope["expires_at"] ?? "") ?? 0, now: now) else { throw NotificationEnvelope.Failure.replay }
            content.title = payload["title"] as? String ?? "Octop"
            content.body = payload["body"] as? String ?? content.body
            if payload["sound"] as? Bool == false { content.sound = nil }
            content.userInfo["octop"] = payload["octop"]
            contentHandler(content)
        } catch {
            // Keep only the generic provider alert, without route data or preview.
            content.title = "Octop"
            content.userInfo.removeValue(forKey: "octop")
            contentHandler(content)
        }
        handler = nil
    }
    override func serviceExtensionTimeWillExpire() {
        if let handler, let fallback { handler(fallback) }
        handler = nil
    }
}

private struct ReplayCache {
    static func accept(host: String, device: String, message: String, expiry: Int, now: Int) -> Bool {
        guard !message.isEmpty, let directory = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first else { return false }
        do { try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true) } catch { return false }
        let lockURL = directory.appendingPathComponent("notification-replay.lock")
        let descriptor = Darwin.open(lockURL.path, O_RDWR | O_CREAT, S_IRUSR | S_IWUSR)
        guard descriptor >= 0 else { return false }
        defer { Darwin.close(descriptor) }
        guard flock(descriptor, LOCK_EX) == 0 else { return false }
        defer { flock(descriptor, LOCK_UN) }
        let file = directory.appendingPathComponent("notification-replay.json")
        do {
            var existing: [String: Int] = [:]
            if let data = try? Data(contentsOf: file), let decoded = try? JSONDecoder().decode([String: Int].self, from: data) { existing = decoded.filter { $0.value >= now } }
            let key = host + ":" + device + ":" + message
            guard existing[key] == nil, existing.count < 4096 else { return false }
            existing[key] = expiry
            try JSONEncoder().encode(existing).write(to: file, options: .atomic)
            return true
        } catch { return false }
    }
}
