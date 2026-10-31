import CryptoKit
import Foundation

@main
struct VerifyNotificationProtocol {
    static func main() throws {
        let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
        let vector = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        let envelope = vector["envelope"] as! [String: String]
        let key = NotificationEnvelope.key(credential: vector["credential"] as! String)
        let host = envelope["host_fingerprint"]!, device = envelope["device_id"]!, now = vector["now"] as! Int
        try require(key.withUnsafeBytes { Data($0) }.base64EncodedString() == vector["notification_key_base64"] as! String)
        try require(try NotificationEnvelope.aad(envelope).base64EncodedString() == vector["aad_base64"] as! String)
        var seen = Set<String>()
        let payload = try NotificationEnvelope.open(envelope, key: key, host: host, device: device, now: now, seen: &seen)
        try require((payload as NSDictionary).isEqual(to: vector["expected_payload"] as! [String: Any]))
        try fails { _ = try NotificationEnvelope.open(envelope, key: key, host: host, device: device, now: now, seen: &seen) }
        try fails { var empty = Set<String>(); _ = try NotificationEnvelope.open(envelope, key: key, host: host, device: "wrong", now: now, seen: &empty) }
        try fails { var empty = Set<String>(); _ = try NotificationEnvelope.open(envelope, key: key, host: host, device: device, now: now + 301, seen: &empty) }
        try fails { var empty = Set<String>(); _ = try NotificationEnvelope.open(envelope, key: key, host: host, device: device, now: now - 61, seen: &empty) }
        for field in ["thread_id", "agent_id", "message_id", "expires_at", "host_fingerprint"] {
            var changed = envelope; changed[field] = field == "expires_at" ? String(now + 1) : "tampered"
            try fails { var empty = Set<String>(); _ = try NotificationEnvelope.open(changed, key: key, host: host, device: device, now: now, seen: &empty) }
        }
        print("Swift notification protocol: HKDF, AAD, golden payload, tamper, recipient, expiry and replay passed")
    }
    static func require(_ value: Bool) throws { if !value { throw NotificationEnvelope.Failure.invalid } }
    static func fails(_ body: () throws -> Void) throws {
        do { try body() } catch { return }
        throw NotificationEnvelope.Failure.invalid
    }
}
