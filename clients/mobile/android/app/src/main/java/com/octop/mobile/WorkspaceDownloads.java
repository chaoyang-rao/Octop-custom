package com.octop.mobile;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.util.Base64;
import android.webkit.DownloadListener;
import android.webkit.URLUtil;
import android.webkit.WebView;
import android.widget.Toast;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.util.UUID;
import java.util.concurrent.ExecutorService;

/** User-selected document downloads; bearer headers never leave the paired origin. */
final class WorkspaceDownloads implements DownloadListener {
    static final int SAVE_DOCUMENT = 44;
    private static final int LIMIT = 10 * 1024 * 1024;
    private final Activity activity;
    private final WebView view;
    private final URI base;
    private final String token;
    private final ExecutorService network;
    private String nonce;
    private boolean busy;
    private byte[] pending;
    private String filename;
    WorkspaceDownloads(Activity activity, WebView view, URI base, String token, ExecutorService network) {
        this.activity = activity; this.view = view; this.base = base; this.token = token; this.network = network;
    }
    @Override public void onDownloadStart(String url, String userAgent, String disposition, String mime, long length) {
        if (busy) { Toast.makeText(activity, NativeStrings.text("native_finish_the_current_download"), Toast.LENGTH_SHORT).show(); return; }
        busy = true;
        if (length > LIMIT) { error(); return; }
        filename = URLUtil.guessFileName(url, disposition, mime).replaceAll("[\\\\/\\r\\n]", "_");
        if (filename.length() > 180) filename = filename.substring(0, 180);
        if (url.startsWith("blob:" + base)) {
            nonce = UUID.randomUUID().toString();
            String script = "fetch(" + JSONObject.quote(url) + ").then(r=>r.blob()).then(blob=>{if(blob.size>" + LIMIT + ")throw Error();const reader=new FileReader();reader.onload=()=>octopNative.postMessage(JSON.stringify({kind:'download',nonce:" + JSONObject.quote(nonce) + ",data:reader.result,mime:blob.type}));reader.readAsDataURL(blob);}).catch(()=>octopNative.postMessage(JSON.stringify({kind:'download',nonce:" + JSONObject.quote(nonce) + ",error:true})))";
            view.evaluateJavascript(script, null);
            return;
        }
        network.execute(() -> {
            HttpURLConnection connection = null;
            try {
                URI target = new URI(url);
                if (!base.getScheme().equals(target.getScheme()) || !base.getHost().equals(target.getHost()) || base.getPort() != target.getPort()) throw new Exception();
                connection = (HttpURLConnection) target.toURL().openConnection();
                connection.setInstanceFollowRedirects(false); connection.setConnectTimeout(15000); connection.setReadTimeout(20000);
                connection.setRequestProperty("Authorization", "Bearer " + token);
                if (connection.getResponseCode() != 200) throw new Exception();
                try (InputStream input = connection.getInputStream(); ByteArrayOutputStream result = new ByteArrayOutputStream()) {
                    byte[] buffer = new byte[8192]; int count;
                    while ((count = input.read(buffer)) >= 0) { if (result.size() + count > LIMIT) throw new Exception(); result.write(buffer, 0, count); }
                    pending = result.toByteArray();
                }
                activity.runOnUiThread(() -> chooseDestination(mime));
            } catch (Exception ignored) { error(); }
            finally { if (connection != null) connection.disconnect(); }
        });
    }
    void acceptMessage(JSONObject value) {
        if (nonce == null || !nonce.equals(value.optString("nonce"))) return;
        nonce = null;
        String data = value.optString("data"); int comma = data.indexOf(',');
        if (value.optBoolean("error") || comma < 0 || data.length() > LIMIT * 4L / 3 + 1024) { error(); return; }
        try { pending = Base64.decode(data.substring(comma + 1), Base64.DEFAULT); if (pending.length > LIMIT) throw new Exception(); chooseDestination(value.optString("mime")); }
        catch (Exception ignored) { pending = null; error(); }
    }
    private void chooseDestination(String mime) {
        if (activity.isDestroyed()) { pending = null; return; }
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                .setType(mime == null || mime.isEmpty() ? "application/octet-stream" : mime).putExtra(Intent.EXTRA_TITLE, filename);
        activity.startActivityForResult(intent, SAVE_DOCUMENT);
    }
    void result(int result, Intent data) {
        byte[] contents = pending; pending = null; busy = false;
        if (result != Activity.RESULT_OK || data == null || data.getData() == null || contents == null) return;
        Uri uri = data.getData();
        network.execute(() -> {
            try (var output = activity.getContentResolver().openOutputStream(uri)) {
                if (output == null) throw new Exception(); output.write(contents);
                activity.runOnUiThread(() -> Toast.makeText(activity, NativeStrings.text("native_saved"), Toast.LENGTH_SHORT).show());
            } catch (Exception ignored) { error(); }
        });
    }
    private void error() { busy = false; nonce = null; pending = null; activity.runOnUiThread(() -> Toast.makeText(activity, NativeStrings.text("native_download_failed_10_mb_maximum"), Toast.LENGTH_LONG).show()); }
}
