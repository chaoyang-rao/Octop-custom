package com.octop.mobile;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import org.json.JSONObject;
import java.io.File;
import java.nio.file.Files;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.Arrays;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

final class SharedDraftStore {
    private static final String ALIAS = "octop-mobile-share-drafts-v1";
    private final File folder;
    SharedDraftStore(Context context) { folder = new File(context.getFilesDir(), "share-drafts"); folder.mkdirs(); }
    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (!store.containsAlias(ALIAS)) { KeyGenerator generator = KeyGenerator.getInstance("AES", "AndroidKeyStore"); generator.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build()); generator.generateKey(); }
        return ((KeyStore.SecretKeyEntry) store.getEntry(ALIAS, null)).getSecretKey();
    }
    synchronized void save(JSONObject draft) throws Exception {
        String id = draft.optString("draft_id"); if (id.isEmpty()) { id = UUID.randomUUID().toString(); draft.put("draft_id", id); }
        UUID.fromString(id);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key()); cipher.updateAAD(id.getBytes(StandardCharsets.UTF_8));
        byte[] encrypted = cipher.doFinal(draft.toString().getBytes(StandardCharsets.UTF_8)), nonce = cipher.getIV();
        byte[] combined = new byte[nonce.length + encrypted.length]; System.arraycopy(nonce, 0, combined, 0, nonce.length); System.arraycopy(encrypted, 0, combined, nonce.length, encrypted.length);
        File temp = new File(folder, id + ".tmp"), target = new File(folder, id + ".sealed"); Files.write(temp.toPath(), combined);
        Files.move(temp.toPath(), target.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING, java.nio.file.StandardCopyOption.ATOMIC_MOVE);
    }
    JSONObject read(String id) throws Exception {
        UUID.fromString(id); byte[] combined = Files.readAllBytes(new File(folder, id + ".sealed").toPath());
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Arrays.copyOfRange(combined, 0, 12))); cipher.updateAAD(id.getBytes(StandardCharsets.UTF_8));
        return new JSONObject(new String(cipher.doFinal(Arrays.copyOfRange(combined, 12, combined.length)), StandardCharsets.UTF_8));
    }
    List<String> ids() { List<String> result = new ArrayList<>(); File[] files = folder.listFiles(); if (files != null) for (File file : files) if (file.getName().endsWith(".sealed")) result.add(file.getName().replace(".sealed", "")); return result; }
    void remove(String id) throws Exception { UUID.fromString(id); Files.deleteIfExists(new File(folder, id + ".sealed").toPath()); }
}
