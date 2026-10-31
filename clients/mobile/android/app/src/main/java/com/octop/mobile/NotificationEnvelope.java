package com.octop.mobile;

import com.google.crypto.tink.subtle.Hkdf;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Base64;
import java.util.Map;
import java.util.Set;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/** Standard HKDF-SHA256 and AES-GCM; no notification key is a login credential. */
final class NotificationEnvelope {
    static final String[] FIELDS = {"seal_version", "host_fingerprint", "device_id", "agent_id", "thread_id", "issued_at", "expires_at", "message_id"};
    static byte[] key(String credential) throws Exception {
        byte[] material = MessageDigest.getInstance("SHA-256").digest(credential.getBytes(StandardCharsets.UTF_8));
        return Hkdf.computeHkdf("HmacSha256", material,
                "octop-mobile-notifications-salt-v1".getBytes(StandardCharsets.UTF_8),
                "octop/mobile/notification-content/v1".getBytes(StandardCharsets.UTF_8), 32);
    }
    static byte[] aad(Map<String, String> envelope) throws Exception {
        ByteArrayOutputStream result = new ByteArrayOutputStream();
        for (String field : FIELDS) {
            String value = envelope.get(field); if (value == null) throw new SecurityException("Invalid envelope");
            byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
            result.write(ByteBuffer.allocate(4).putInt(bytes.length).array()); result.write(bytes);
        }
        return result.toByteArray();
    }
    static byte[] open(Map<String, String> envelope, byte[] key, String host, String device, long now, Set<String> seen) throws Exception {
        if (!"1".equals(envelope.get("seal_version")) || !host.equals(envelope.get("host_fingerprint")) || !device.equals(envelope.get("device_id"))) throw new SecurityException("Recipient mismatch");
        byte[] combined = Base64.getUrlDecoder().decode(envelope.get("sealed"));
        if (combined.length < 28) throw new SecurityException("Invalid envelope");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, new SecretKeySpec(key, "AES"), new GCMParameterSpec(128, Arrays.copyOfRange(combined, 0, 12)));
        cipher.updateAAD(aad(envelope));
        byte[] content = cipher.doFinal(Arrays.copyOfRange(combined, 12, combined.length));
        long issued = Long.parseLong(envelope.get("issued_at")), expiry = Long.parseLong(envelope.get("expires_at"));
        if (issued > now + 60 || expiry <= now || expiry <= issued || expiry - issued > 300) throw new SecurityException("Expired envelope");
        if (!seen.add(envelope.get("message_id"))) throw new SecurityException("Replayed envelope");
        return content;
    }
}
