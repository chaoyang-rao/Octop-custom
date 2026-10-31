package com.octop.mobile;

import org.junit.Test;
import static org.junit.Assert.*;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Properties;
import java.util.Set;

public class NotificationEnvelopeTest {
    private Properties vector() throws Exception {
        Properties value = new Properties();
        try (var input = new InputStreamReader(getClass().getClassLoader().getResourceAsStream("notification-vector.properties"), StandardCharsets.UTF_8)) { value.load(input); }
        return value;
    }
    private Map<String, String> envelope(Properties vector) {
        Map<String, String> result = new HashMap<>();
        for (String name : NotificationEnvelope.FIELDS) result.put(name, vector.getProperty("envelope." + name));
        result.put("sealed", vector.getProperty("envelope.sealed")); return result;
    }
    @Test public void goldenHkdfAadAndPlaintext() throws Exception {
        Properties value = vector(); Map<String, String> envelope = envelope(value);
        byte[] key = NotificationEnvelope.key(value.getProperty("credential"));
        assertEquals(value.getProperty("notification_key_base64"), Base64.getEncoder().encodeToString(key));
        assertEquals(value.getProperty("aad_base64"), Base64.getEncoder().encodeToString(NotificationEnvelope.aad(envelope)));
        Set<String> seen = new HashSet<>(); long now = Long.parseLong(value.getProperty("now"));
        byte[] plain = NotificationEnvelope.open(envelope, key, envelope.get("host_fingerprint"), envelope.get("device_id"), now, seen);
        assertArrayEquals(Base64.getDecoder().decode(value.getProperty("plaintext_base64")), plain);
        assertThrows(Exception.class, () -> NotificationEnvelope.open(envelope, key, envelope.get("host_fingerprint"), envelope.get("device_id"), now, seen));
    }
    @Test public void recipientExpiryFutureAndTamperingRejected() throws Exception {
        Properties value = vector(); Map<String, String> envelope = envelope(value);
        byte[] key = NotificationEnvelope.key(value.getProperty("credential")); long now = Long.parseLong(value.getProperty("now"));
        assertThrows(Exception.class, () -> NotificationEnvelope.open(envelope, key, envelope.get("host_fingerprint"), "wrong", now, new HashSet<>()));
        assertThrows(Exception.class, () -> NotificationEnvelope.open(envelope, key, envelope.get("host_fingerprint"), envelope.get("device_id"), now + 301, new HashSet<>()));
        assertThrows(Exception.class, () -> NotificationEnvelope.open(envelope, key, envelope.get("host_fingerprint"), envelope.get("device_id"), now - 61, new HashSet<>()));
        for (String field : new String[]{"thread_id", "agent_id", "message_id", "expires_at", "host_fingerprint"}) {
            Map<String, String> changed = new HashMap<>(envelope); changed.put(field, "expires_at".equals(field) ? Long.toString(now + 1) : "tampered");
            assertThrows(Exception.class, () -> NotificationEnvelope.open(changed, key, envelope.get("host_fingerprint"), envelope.get("device_id"), now, new HashSet<>()));
        }
    }
}
