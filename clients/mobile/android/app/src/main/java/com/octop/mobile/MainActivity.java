package com.octop.mobile;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Spinner;
import android.widget.ArrayAdapter;
import android.widget.AdapterView;
import androidx.webkit.ProfileStore;
import android.widget.Toast;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import com.google.firebase.FirebaseApp;
import com.google.firebase.messaging.FirebaseMessaging;
import org.json.JSONArray;
import org.json.JSONObject;
import java.net.URI;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;

public class MainActivity extends Activity {
    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private final AtomicInteger generation = new AtomicInteger();
    public static volatile boolean FOREGROUND;
    private final Handler lifecycle = new Handler(Looper.getMainLooper());
    private final Runnable foregroundHeartbeat = new Runnable() { public void run() { if (FOREGROUND) { reportForeground(true); lifecycle.postDelayed(this, 15000); } } };
    private SecureStore store;
    private WebView workspace;
    private WorkspaceDownloads downloads;
    private JSONObject currentServer;
    private ValueCallback<Uri[]> fileCallback;
    private PermissionRequest audioPermission;
    private Future<?> pairing;
    private LinearLayout content;
    private static final int PICK_FILE = 41, AUDIO_PERMISSION = 42;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state); OctopMessagingService.ensureChannel(this); store = new SecureStore(this); showServers(); if (IncomingShare.accepts(getIntent())) IncomingShare.receive(this, getIntent(), store, network); else handleNotification(getIntent());
    }
    @Override protected void onResume() { super.onResume(); syncExistingPush(); FOREGROUND = true; lifecycle.post(foregroundHeartbeat); }
    @Override protected void onPause() { FOREGROUND = false; lifecycle.removeCallbacks(foregroundHeartbeat); reportForeground(false); super.onPause(); }
    private void reportForeground(boolean active) {
        JSONObject server = currentServer;
        if (server == null || !allows(server, "notifications")) return;
        network.execute(() -> {
            try { ServerApi.request(new URI(server.getString("base_url")), "/api/mobile-access/self/notifications", "PUT", new JSONObject().put("foreground", active), store.token(server.getString("id"))); }
            catch (Exception ignored) { }
        });
    }
    static boolean allows(JSONObject server, String scope) {
        JSONArray scopes = server.optJSONArray("scopes"); if (scopes == null) return true;
        for (int i = 0; i < scopes.length(); i++) if (scope.equals(scopes.optString(i))) return true;
        return false;
    }
    @Override protected void onNewIntent(Intent intent) { super.onNewIntent(intent); setIntent(intent); if (IncomingShare.accepts(intent)) IncomingShare.receive(this, intent, store, network); else handleNotification(intent); }
    private void handleNotification(Intent intent) {
        String fingerprint = intent.getStringExtra("server_fingerprint");
        if (fingerprint == null) return;
        try {
            JSONArray servers = store.servers();
            for (int i = 0; i < servers.length(); i++) if (servers.getJSONObject(i).getString("fingerprint").equals(fingerprint) && (intent.getStringExtra("device_id") == null || servers.getJSONObject(i).getString("device_id").equals(intent.getStringExtra("device_id")))) {
                openWorkspace(servers.getJSONObject(i), intent.getStringExtra("agent_id"), intent.getStringExtra("thread_id")); return;
            }
        } catch (Exception ignored) { showError(NativeStrings.text("native_select_your_server")); }
    }
    private Button button(String label, Runnable action) { Button button = new Button(this); button.setText(label); button.setOnClickListener(view -> action.run()); return button; }
    private TextView text(String value) { TextView text = new TextView(this); text.setText(value); text.setTextSize(14); text.setPadding(8, 12, 8, 12); text.setTextIsSelectable(true); return text; }
    private void showError(String value) { if (!isDestroyed()) runOnUiThread(() -> Toast.makeText(this, value, Toast.LENGTH_LONG).show()); }
    private void resetView() {
        reportForeground(false);
        generation.incrementAndGet(); if (pairing != null) pairing.cancel(true);
        if (workspace != null) { workspace.stopLoading(); workspace.clearHistory(); workspace.clearCache(true); workspace.destroy(); workspace = null; }
        content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL); content.setPadding(16, 16, 16, 0); setContentView(content);
    }
    private void showServers() {
        resetView(); currentServer = null;
        TextView title = text(NativeStrings.text("native_octop_mobile_and_remote_access")); title.setTextSize(24); content.addView(title);
        Spinner language = new Spinner(this);
        String[] modes = {"account", "zh", "en"};
        language.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, new String[]{NativeStrings.text("native_follow_account"), "中文", "English"}));
        for (int index = 0; index < modes.length; index++) if (modes[index].equals(NativeStrings.mode())) language.setSelection(index);
        language.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            public void onNothingSelected(AdapterView<?> parent) { }
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                if (!modes[position].equals(NativeStrings.mode())) { NativeStrings.mode(modes[position]); showServers(); }
            }
        });
        content.addView(language);
        EditText address = new EditText(this); address.setSingleLine(true); address.setHint("https://your-octop.example"); address.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_URI); content.addView(address);
        content.addView(button(NativeStrings.text("native_request_pairing"), () -> beginPairing(address.getText().toString())));
        content.addView(text(NativeStrings.text("native_approve_this_phone_from_an_already_signed_in_compute")));
        content.addView(button(NativeStrings.text("native_shared_drafts"), () -> IncomingShare.inbox(this, store, network)));
        try {
            JSONArray servers = store.servers();
            for (int i = 0; i < servers.length(); i++) {
                JSONObject server = servers.getJSONObject(i);
                content.addView(button(server.getString("base_url") + (server.optString("account_label").isEmpty() ? "" : " · " + server.optString("account_label")), () -> openWorkspace(server, null, null)));
            }
        } catch (Exception ignored) { showError(NativeStrings.text("native_could_not_load_servers")); }
    }
    private void beginPairing(String address) {
        if (pairing != null) pairing.cancel(true); final int taskGeneration = generation.incrementAndGet();
        pairing = network.submit(() -> {
            try {
                URI base = ServerApi.validate(address);
                JSONObject challenge = ServerApi.request(base, "/api/mobile-access/pairings/request", "POST", new JSONObject().put("name", Build.MANUFACTURER + " " + Build.MODEL).put("platform", "android"), null);
                runOnUiThread(() -> {
                    if (taskGeneration != generation.get()) return;
                    content.addView(text(challenge.optString("user_code")));
                    content.addView(text(challenge.optString("host_fingerprint")));
                    content.addView(text(NativeStrings.text("native_waiting_for_approval_31da20")));
                    content.addView(button(NativeStrings.text("native_cancel"), this::showServers));
                });
                while (!Thread.currentThread().isInterrupted() && taskGeneration == generation.get() && System.currentTimeMillis() / 1000 < challenge.getLong("expires_at")) {
                    Thread.sleep(3000);
                    JSONObject result = ServerApi.request(base, "/api/mobile-access/pairings/exchange", "POST", new JSONObject().put("pairing_secret", challenge.getString("pairing_secret")), null);
                    if ("approved".equals(result.getString("status"))) {
                        if (!challenge.getString("host_fingerprint").equals(result.getString("host_fingerprint"))) throw new Exception(NativeStrings.text("native_server_identity_mismatch"));
                        String id = result.getString("host_fingerprint") + ":" + result.getString("device_id");
                        JSONObject server = new JSONObject().put("id", id).put("base_url", base.toString()).put("device_id", result.getString("device_id")).put("fingerprint", result.getString("host_fingerprint")).put("expires_at", result.getLong("expires_at")).put("scopes", result.getJSONArray("scopes"));
                        store.addServer(server, result.getString("access_token"));
                        runOnUiThread(() -> { if (taskGeneration == generation.get()) openWorkspace(server, null, null); }); return;
                    }
                }
                if (taskGeneration == generation.get()) showError(NativeStrings.text("native_pairing_code_expired"));
            } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
            catch (Exception error) { if (taskGeneration == generation.get()) showError(error.getMessage()); }
        });
    }
    private void openWorkspace(JSONObject server, String agent, String thread) {
        if (workspace != null && currentServer != null && currentServer.optString("id").equals(server.optString("id"))) {
            if (agent != null && thread != null && agent.matches("[A-Za-z0-9_:-]+") && thread.matches("[A-Za-z0-9_:-]+")) {
                workspace.evaluateJavascript("history.pushState(null,''," + JSONObject.quote("/chat/" + agent + "/" + thread) + ");window.dispatchEvent(new PopStateEvent('popstate'))", null);
            }
            return;
        }
        network.execute(() -> {
            try {
                URI base = ServerApi.validate(server.getString("base_url"));
                JSONObject profile = ServerApi.request(base, "/api/auth/me", "GET", null, store.token(server.getString("id")));
                server.put("locale", profile.optString("locale", "en"));
                server.put("account_label", profile.optString("display_name", profile.optString("username", "")));
                store.updateServer(server);
                runOnUiThread(() -> { NativeStrings.accountLanguage(server.optString("locale", "en")); openWorkspaceNow(server, agent, thread); });
            } catch (Exception ignored) { showError(NativeStrings.text("native_generic_network_error")); }
        });
    }
    private void openWorkspaceNow(JSONObject server, String agent, String thread) {
        try {
            URI base = ServerApi.validate(server.getString("base_url")); String token = store.token(server.getString("id"));
            if (token == null) { showError(NativeStrings.text("native_pair_this_device_again")); return; }
            if (!WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT) || !WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER) || !WebViewFeature.isFeatureSupported(WebViewFeature.MULTI_PROFILE)) { showError(NativeStrings.text("native_update_android_system_webview")); return; }
            resetView(); currentServer = server; store.select(server.getString("id")); syncExistingPush();
            LinearLayout toolbar = new LinearLayout(this); toolbar.addView(button(NativeStrings.text("native_servers"), this::showServers)); toolbar.addView(button(NativeStrings.text("native_notifications_2ca143"), this::enableNotifications)); toolbar.addView(button(NativeStrings.text("native_preferences"), () -> { if (allows(server, "notifications")) NotificationSettings.open(this, server, store, network); })); toolbar.addView(button(NativeStrings.text("native_revoke"), () -> revoke(server))); content.addView(toolbar);
            workspace = new WebView(this); content.addView(workspace, new LinearLayout.LayoutParams(-1, 0, 1));
            WebViewCompat.setProfile(workspace, "octop_" + server.getString("device_id"));
            WebSettings settings = workspace.getSettings(); settings.setJavaScriptEnabled(true); settings.setDomStorageEnabled(true); settings.setCacheMode(WebSettings.LOAD_NO_CACHE); settings.setAllowFileAccess(false); settings.setAllowContentAccess(true); settings.setGeolocationEnabled(false); settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
            String origin = base.toString();
            WebViewCompat.addWebMessageListener(workspace, "octopNative", java.util.Collections.singleton(origin), (view, message, sourceOrigin, mainFrame, replyProxy) -> {
                if (!mainFrame || !sameOrigin(base, sourceOrigin)) return;
                try {
                    JSONObject value = new JSONObject(message.getData());
                    if ("unauthorized".equals(value.optString("kind"))) { store.forget(server.getString("id")); showServers(); deleteProfile(server); showError(NativeStrings.text("native_re_pair_this_device_8570d1")); }
                    else if ("download".equals(value.optString("kind")) && downloads != null) downloads.acceptMessage(value);

                } catch (Exception ignored) { /* Only structured messages from the trusted main frame. */ }
            });
            String script = "(()=>{localStorage.removeItem('auth_token');sessionStorage.setItem('auth_token'," + JSONObject.quote(token) + ");window.addEventListener('octop:unauthorized',()=>octopNative.postMessage(JSON.stringify({kind:'unauthorized'})));})();";
            WebViewCompat.addDocumentStartJavaScript(workspace, script, java.util.Collections.singleton(origin));
            downloads = new WorkspaceDownloads(this, workspace, base, token, network);
            workspace.setDownloadListener(downloads);
            workspace.setWebViewClient(new WebViewClient() {
                @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                    if (!request.isForMainFrame() || sameOrigin(base, request.getUrl())) return false;
                    if (request.hasGesture() && java.util.Arrays.asList("https", "http").contains(request.getUrl().getScheme())) startActivity(new Intent(Intent.ACTION_VIEW, request.getUrl()));
                    return true;
                }
            });
            workspace.setWebChromeClient(new WebChromeClient() {
                @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams parameters) {
                    if (fileCallback != null) fileCallback.onReceiveValue(null); fileCallback = callback;
                    try { startActivityForResult(parameters.createIntent(), PICK_FILE); return true; }
                    catch (Exception ignored) { fileCallback = null; callback.onReceiveValue(null); return true; }
                }
                @Override public void onPermissionRequest(PermissionRequest request) {
                    if (!sameOrigin(base, request.getOrigin()) || !java.util.Arrays.asList(request.getResources()).contains(PermissionRequest.RESOURCE_AUDIO_CAPTURE)) { request.deny(); return; }
                    audioPermission = request;
                    if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) { request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE}); audioPermission = null; }
                    else requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, AUDIO_PERMISSION);
                }
            });
            String start = base.toString() + "/";
            if (agent != null && thread != null && agent.matches("[A-Za-z0-9_:-]+") && thread.matches("[A-Za-z0-9_:-]+")) start = base + "/chat/" + agent + "/" + thread;
            workspace.loadUrl(start);
            reportForeground(true);
        } catch (Exception error) { showError(NativeStrings.text("native_could_not_connect_re_pair_this_device")); }
    }
    private static boolean sameOrigin(URI base, Uri target) {
        return base.getScheme().equals(target.getScheme()) && base.getHost().equals(target.getHost()) && base.getPort() == target.getPort();
    }
    private void deleteProfile(JSONObject server) {
        if (WebViewFeature.isFeatureSupported(WebViewFeature.MULTI_PROFILE)) {
            try { ProfileStore.getInstance().deleteProfile("octop_" + server.optString("device_id")); } catch (IllegalStateException ignored) { }
        }
    }
    private void syncExistingPush() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return;
        try { if (FirebaseApp.initializeApp(this) != null) FirebaseMessaging.getInstance().getToken().addOnSuccessListener(value -> OctopMessagingService.register(this, value)); }
        catch (Exception ignored) { /* No configuration or OS permission prompt on app launch. */ }
    }
    private void enableNotifications() {
        if (currentServer == null || !allows(currentServer, "notifications")) { showError(NativeStrings.text("native_grant_notifications_on_the_computer_first")); return; }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) { requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 43); return; }
        try {
            if (FirebaseApp.initializeApp(this) == null) { showError(NativeStrings.text("native_configure_your_firebase_project_for_background_push")); return; }
            FirebaseMessaging.getInstance().getToken().addOnSuccessListener(value -> { OctopMessagingService.register(this, value); showError(NativeStrings.text("native_notification_registration_submitted")); }).addOnFailureListener(error -> showError(NativeStrings.text("native_notification_registration_failed")));
        } catch (Exception ignored) { showError(NativeStrings.text("native_firebase_project_is_not_configured")); }
    }
    private void revoke(JSONObject server) {
        new AlertDialog.Builder(this).setTitle(NativeStrings.text("native_revoke_this_device_ceeb31")).setMessage(NativeStrings.text("native_chat_history_is_retained"))
                .setNegativeButton(NativeStrings.text("native_cancel"), null).setPositiveButton(NativeStrings.text("native_revoke"), (dialog, which) -> network.execute(() -> {
                    try { ServerApi.request(new URI(server.getString("base_url")), "/api/mobile-access/self/revoke", "POST", null, store.token(server.getString("id"))); store.forget(server.getString("id")); runOnUiThread(() -> { showServers(); deleteProfile(server); }); }
                    catch (Exception ignored) { showError(NativeStrings.text("native_revoke_on_the_desktop_if_unavailable")); }
                })).show();
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == WorkspaceDownloads.SAVE_DOCUMENT && downloads != null) downloads.result(result, data);
        if (request == PICK_FILE && fileCallback != null) { fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result, data)); fileCallback = null; }
    }
    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] grants) {
        super.onRequestPermissionsResult(request, permissions, grants);
        if (request == AUDIO_PERMISSION && audioPermission != null) { if (grants.length > 0 && grants[0] == PackageManager.PERMISSION_GRANTED) audioPermission.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE}); else audioPermission.deny(); audioPermission = null; }
        if (request == 43 && grants.length > 0 && grants[0] == PackageManager.PERMISSION_GRANTED) enableNotifications();
    }
    @Override public void onBackPressed() { if (workspace != null && workspace.canGoBack()) workspace.goBack(); else showServers(); }
    @Override protected void onDestroy() { generation.incrementAndGet(); if (pairing != null) pairing.cancel(true); network.shutdownNow(); if (workspace != null) workspace.destroy(); super.onDestroy(); }
}
