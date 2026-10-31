package com.octop.mobile;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

final class SecureStore {
    private static final String ALIAS = "octop-mobile-device-session";
    private final SharedPreferences preferences;
    SecureStore(Context context) { preferences = context.getSharedPreferences("octop-mobile", Context.MODE_PRIVATE); }
    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (!store.containsAlias(ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            generator.generateKey();
        }
        return ((KeyStore.SecretKeyEntry) store.getEntry(ALIAS, null)).getSecretKey();
    }
    void saveToken(String id, String token) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key());
        String value = Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP) + ":" + Base64.encodeToString(cipher.doFinal(token.getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP);
        preferences.edit().putString("credential." + id, value).apply();
    }
    String token(String id) throws Exception {
        String value = preferences.getString("credential." + id, null);
        if (value == null) return null;
        String[] pieces = value.split(":", 2);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(pieces[0], Base64.NO_WRAP)));
        return new String(cipher.doFinal(Base64.decode(pieces[1], Base64.NO_WRAP)), StandardCharsets.UTF_8);
    }
    JSONArray servers() throws Exception { return new JSONArray(preferences.getString("servers", "[]")); }
    void addServer(JSONObject server, String token) throws Exception {
        String id = server.getString("id"); saveToken(id, token);
        JSONArray existing = servers(), next = new JSONArray();
        for (int index = 0; index < existing.length(); index++) if (!existing.getJSONObject(index).getString("id").equals(id)) next.put(existing.getJSONObject(index));
        next.put(server); preferences.edit().putString("servers", next.toString()).putString("active", id).apply();
    }
    void forget(String id) throws Exception {
        JSONArray next = new JSONArray(), existing = servers();
        for (int index = 0; index < existing.length(); index++) if (!existing.getJSONObject(index).getString("id").equals(id)) next.put(existing.getJSONObject(index));
        preferences.edit().putString("servers", next.toString()).remove("credential." + id).apply();
    }
    JSONObject active() throws Exception {
        String id = preferences.getString("active", ""); JSONArray all = servers();
        for (int i = 0; i < all.length(); i++) if (all.getJSONObject(i).getString("id").equals(id)) return all.getJSONObject(i);
        return null;
    }
    void updateServer(JSONObject server) throws Exception {
        JSONArray all = servers();
        for (int index = 0; index < all.length(); index++) if (all.getJSONObject(index).getString("id").equals(server.getString("id"))) all.put(index, server);
        preferences.edit().putString("servers", all.toString()).apply();
    }
    void select(String id) { preferences.edit().putString("active", id).apply(); }
}
