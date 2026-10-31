package com.octop.mobile;

import android.content.Context;
import android.content.SharedPreferences;
import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

final class SealedNotification {
    static synchronized Map<String, String> open(Context context, Map<String, String> envelope) {
        try {
            SecureStore store = new SecureStore(context);
            JSONArray servers = store.servers(); JSONObject server = null;
            for (int i = 0; i < servers.length(); i++) {
                JSONObject candidate = servers.getJSONObject(i);
                if (candidate.getString("fingerprint").equals(envelope.get("host_fingerprint")) && candidate.getString("device_id").equals(envelope.get("device_id"))) { server = candidate; break; }
            }
            if (server == null) return null;
            String credential = store.token(server.getString("id")); if (credential == null) return null;
            long now = System.currentTimeMillis() / 1000;
            SharedPreferences preferences = context.getSharedPreferences("octop-notification-replay", Context.MODE_PRIVATE);
            JSONObject cache = new JSONObject(preferences.getString("seen", "{}")), retained = new JSONObject();
            for (var iterator = cache.keys(); iterator.hasNext();) { String key = iterator.next(); if (cache.optLong(key) >= now) retained.put(key, cache.getLong(key)); }
            String cacheKey = envelope.get("host_fingerprint") + ":" + envelope.get("device_id") + ":" + envelope.get("message_id");
            if (retained.has(cacheKey) || retained.length() >= 4096) return null;
            Set<String> seen = new HashSet<>();
            byte[] plain = NotificationEnvelope.open(envelope, NotificationEnvelope.key(credential), server.getString("fingerprint"), server.getString("device_id"), now, seen);
            JSONObject payload = new JSONObject(new String(plain, StandardCharsets.UTF_8)); JSONObject route = payload.getJSONObject("octop");
            if (!route.optString("agent_id").equals(envelope.get("agent_id")) || !route.optString("thread_id").equals(envelope.get("thread_id"))) return null;
            retained.put(cacheKey, Long.parseLong(envelope.get("expires_at")));
            if (!preferences.edit().putString("seen", retained.toString()).commit()) return null;
            Map<String, String> result = new HashMap<>();
            for (String name : new String[]{"server_fingerprint", "device_id", "thread_id", "agent_id"}) if (route.has(name)) result.put(name, route.getString(name));
            result.put("title", payload.optString("title", "Octop")); result.put("body", payload.optString("body", NativeStrings.text("native_new_activity")));
            result.put("notification_sound", payload.optBoolean("sound", true) ? "true" : "false");
            return result;
        } catch (Exception ignored) { return null; }
    }
}
