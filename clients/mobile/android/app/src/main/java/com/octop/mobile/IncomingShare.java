package com.octop.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;
import android.util.Base64;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;
import android.widget.AdapterView;
import android.view.View;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.URI;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;

final class IncomingShare {
    private static final int MAX = 10 * 1024 * 1024;
    static boolean accepts(Intent intent) { return Intent.ACTION_SEND.equals(intent.getAction()) || Intent.ACTION_SEND_MULTIPLE.equals(intent.getAction()); }
    static void receive(Activity activity, Intent intent, SecureStore store, ExecutorService network) {
        network.execute(() -> {
            try {
                JSONObject draft = new JSONObject().put("text", String.valueOf(intent.getCharSequenceExtra(Intent.EXTRA_TEXT) == null ? "" : intent.getCharSequenceExtra(Intent.EXTRA_TEXT))).put("state", "draft");
                if (draft.getString("text").length() > 32000) throw new Exception();
                List<Uri> uris = new ArrayList<>();
                if (Intent.ACTION_SEND_MULTIPLE.equals(intent.getAction())) { ArrayList<Uri> incoming = intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM); if (incoming != null) uris.addAll(incoming); }
                else { Uri uri = intent.getParcelableExtra(Intent.EXTRA_STREAM); if (uri != null) uris.add(uri); }
                if (uris.size() > 10) throw new Exception();
                JSONArray files = new JSONArray(); int total = 0;
                for (Uri uri : uris) {
                    if (!"content".equals(uri.getScheme())) throw new Exception();
                    String name = "attachment";
                    try (Cursor cursor = activity.getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) { if (cursor != null && cursor.moveToFirst()) name = cursor.getString(0); }
                    name = name == null ? "attachment" : name.replaceAll("[\\\\/\\r\\n]", "_"); if (name.length() > 180) name = name.substring(0, 180);
                    String mime = activity.getContentResolver().getType(uri); if (mime == null || !mime.matches("[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+")) mime = "application/octet-stream";
                    try (InputStream input = activity.getContentResolver().openInputStream(uri); ByteArrayOutputStream data = new ByteArrayOutputStream()) {
                        if (input == null) throw new Exception(); byte[] buffer = new byte[8192]; int count;
                        while ((count = input.read(buffer)) >= 0) { if (total + data.size() + count > MAX) throw new Exception(); data.write(buffer, 0, count); }
                        total += data.size(); files.put(new JSONObject().put("filename", name).put("mime", mime).put("data", Base64.encodeToString(data.toByteArray(), Base64.NO_WRAP)));
                    }
                }
                draft.put("files", files); if (files.length() == 0 && draft.getString("text").trim().isEmpty()) throw new Exception();
                activity.runOnUiThread(() -> dialog(activity, draft, store, network));
            } catch (Exception ignored) { activity.runOnUiThread(() -> Toast.makeText(activity, NativeStrings.text("native_could_not_read_shared_content"), Toast.LENGTH_LONG).show()); }
        });
    }
    static void inbox(Activity activity, SecureStore store, ExecutorService network) {
        network.execute(() -> {
            SharedDraftStore drafts = new SharedDraftStore(activity); List<String> ids = drafts.ids();
            List<String> labels = new ArrayList<>(); List<String> valid = new ArrayList<>();
            for (String id : ids) { try { JSONObject draft = drafts.read(id); String label = draft.optString("text"); labels.add(label.isEmpty() ? NativeStrings.text("native_shared_files") : label.substring(0, Math.min(60, label.length()))); valid.add(id); } catch (Exception ignored) { } }
            activity.runOnUiThread(() -> new AlertDialog.Builder(activity).setTitle(NativeStrings.text("native_shared_drafts")).setItems(labels.toArray(new String[0]), (view, index) -> network.execute(() -> { try { JSONObject draft = drafts.read(valid.get(index)); activity.runOnUiThread(() -> dialog(activity, draft, store, network)); } catch (Exception ignored) { } })).setNegativeButton(NativeStrings.text("native_close"), null).show());
        });
    }
    private static void dialog(Activity activity, JSONObject draft, SecureStore store, ExecutorService network) {
        try {
            JSONArray accounts = store.servers(); if (accounts.length() == 0) { Toast.makeText(activity, NativeStrings.text("native_pair_a_server_first"), Toast.LENGTH_LONG).show(); return; }
            ScrollView scroll = new ScrollView(activity); LinearLayout form = new LinearLayout(activity); form.setOrientation(LinearLayout.VERTICAL); form.setPadding(28, 12, 28, 12); scroll.addView(form);
            Spinner account = new Spinner(activity), expert = new Spinner(activity); EditText text = new EditText(activity); text.setMinLines(4); text.setText(draft.optString("text"));
            String[] names = new String[accounts.length()]; for (int i = 0; i < names.length; i++) names[i] = accounts.getJSONObject(i).getString("base_url") + " · " + accounts.getJSONObject(i).optString("account_label");
            account.setAdapter(new ArrayAdapter<>(activity, android.R.layout.simple_spinner_dropdown_item, names)); form.addView(account); form.addView(expert); form.addView(text);
            for (int i = 0; i < accounts.length(); i++) if (accounts.getJSONObject(i).optString("id").equals(draft.optString("account_id"))) account.setSelection(i);
            JSONArray incomingFiles = draft.optJSONArray("files");
            if (incomingFiles != null) for (int i = 0; i < incomingFiles.length(); i++) { TextView fileLabel = new TextView(activity); fileLabel.setText(incomingFiles.getJSONObject(i).optString("filename")); form.addView(fileLabel); }
            TextView information = new TextView(activity); information.setText(NativeStrings.text("native_separate_background_conversation_your_current_draft_")); form.addView(information);
            int[] generation = {0}; String[] credentialAccount = {null};
            boolean[] canSend = {false}; String[] credential = {null}; JSONArray[] experts = {new JSONArray()};
            Button send = new Button(activity); send.setText(NativeStrings.text("native_send_background_task")); send.setEnabled(false); form.addView(send);
            Button save = new Button(activity); save.setText(NativeStrings.text("native_save_draft")); form.addView(save);
            SharedDraftStore drafts = new SharedDraftStore(activity);
            AlertDialog dialog = new AlertDialog.Builder(activity).setTitle(NativeStrings.text("native_share_to_octop")).setView(scroll).setNegativeButton(NativeStrings.text("native_close"), null).create();
            account.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
                public void onNothingSelected(AdapterView<?> parent) { }
                public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                    send.setEnabled(false); canSend[0] = false; credential[0] = null; credentialAccount[0] = null; final int loadGeneration = ++generation[0];
                    network.execute(() -> {
                        try {
                            JSONObject server = accounts.getJSONObject(position); URI base = new URI(server.getString("base_url"));
                            JSONObject grant = ServerApi.request(base, "/api/mobile-access/self/share-grant", "POST", null, store.token(server.getString("id")));
                            String share = grant.getString("access_token"); JSONArray labels = ServerApi.array(base, "/api/mobile-access/share/experts", share);
                            JSONObject profile = ServerApi.request(base, "/api/auth/me", "GET", null, share); boolean tasks = false; JSONArray permissions = profile.optJSONArray("permissions"); if (permissions != null) for (int i = 0; i < permissions.length(); i++) if ("tasks".equals(permissions.optString(i))) tasks = true;
                            boolean allowed = tasks;
                            activity.runOnUiThread(() -> { if (generation[0] != loadGeneration || account.getSelectedItemPosition() != position) return; NativeStrings.accountLanguage(profile.optString("locale", "en"));
                                send.setText(NativeStrings.text("native_send_background_task")); save.setText(NativeStrings.text("native_save_draft"));
                                dialog.setTitle(NativeStrings.text("native_share_to_octop")); dialog.getButton(AlertDialog.BUTTON_NEGATIVE).setText(NativeStrings.text("native_close"));
                                information.setText(NativeStrings.text("native_separate_background_conversation_your_current_draft_"));
                                credentialAccount[0] = server.optString("id"); credential[0] = share; experts[0] = labels; canSend[0] = allowed; List<String> rows = new ArrayList<>(); for (int i = 0; i < labels.length(); i++) rows.add(labels.optJSONObject(i).optString("name")); expert.setAdapter(new ArrayAdapter<>(activity, android.R.layout.simple_spinner_dropdown_item, rows));
                                for (int i = 0; i < labels.length(); i++) if (labels.optJSONObject(i).optString("agent_id").equals(draft.optString("agent_id"))) expert.setSelection(i);
                                send.setEnabled(allowed && labels.length() > 0 && !"unknown".equals(draft.optString("state")) && !"sent".equals(draft.optString("state"))); });
                        } catch (Exception ignored) { activity.runOnUiThread(() -> information.setText(NativeStrings.text("native_could_not_load_experts_save_a_local_draft"))); }
                    });
                }
            });
            save.setOnClickListener(view -> { try { draft.put("text", text.getText().toString()); draft.put("account_id", accounts.getJSONObject(account.getSelectedItemPosition()).getString("id")); if (expert.getSelectedItemPosition() >= 0 && expert.getSelectedItemPosition() < experts[0].length()) draft.put("agent_id", experts[0].getJSONObject(expert.getSelectedItemPosition()).getString("agent_id")); JSONObject savedSnapshot = new JSONObject(draft.toString()); network.execute(() -> { try { drafts.save(savedSnapshot); activity.runOnUiThread(() -> information.setText(NativeStrings.text("native_encrypted_draft_saved"))); } catch (Exception ignored) { activity.runOnUiThread(() -> information.setText(NativeStrings.text("native_could_not_save_draft"))); } }); } catch (Exception ignored) { } });
            send.setOnClickListener(view -> {
                if (!canSend[0] || credential[0] == null || account.getSelectedItemPosition() < 0 || expert.getSelectedItemPosition() < 0) return;
                if (!accounts.optJSONObject(account.getSelectedItemPosition()).optString("id").equals(credentialAccount[0])) return;
                final String shareCredential = credential[0]; send.setEnabled(false); save.setEnabled(false); dialog.setCancelable(false); dialog.getButton(AlertDialog.BUTTON_NEGATIVE).setEnabled(false);
                try {
                    JSONObject server = accounts.getJSONObject(account.getSelectedItemPosition()); account.setEnabled(false); expert.setEnabled(false); text.setEnabled(false); String agentID = experts[0].getJSONObject(expert.getSelectedItemPosition()).getString("agent_id"); String prompt = text.getText().toString().trim(); if (prompt.isEmpty()) prompt = NativeStrings.text("native_analyze_the_shared_attachments"); String finalPrompt = prompt;
                    network.execute(() -> {
                        try {
                            draft.put("text", finalPrompt); draft.put("account_id", server.getString("id")); draft.put("agent_id", agentID); drafts.save(draft);
                            JSONArray files = draft.optJSONArray("files"), attachments = new JSONArray(); URI base = new URI(server.getString("base_url"));
                            if (files != null) for (int index = 0; index < files.length(); index++) { JSONObject file = files.getJSONObject(index); byte[] data = Base64.decode(file.getString("data"), Base64.NO_WRAP); JSONObject uploaded = ServerApi.upload(base, agentID, file.getString("filename"), file.getString("mime"), data, shareCredential); attachments.put(new JSONObject().put("workspace_path", uploaded.getString("workspace_path")).put("filename", file.getString("filename")).put("mime_type", uploaded.optString("media_type", file.getString("mime"))).put("size", data.length).put("upload_receipt", uploaded.getString("upload_receipt"))); }
                            draft.put("state", "unknown"); drafts.save(draft);
                            JSONObject receipt = ServerApi.request(base, "/api/tasks", "POST", new JSONObject().put("agent_id", agentID).put("title", finalPrompt.substring(0, Math.min(80, finalPrompt.length()))).put("prompt", finalPrompt).put("attachments", attachments), shareCredential);
                            draft.put("state", "sent"); draft.put("task_id", receipt.optString("task_id", receipt.optString("id"))); drafts.save(draft); drafts.remove(draft.getString("draft_id"));
                            activity.runOnUiThread(() -> information.setText(NativeStrings.text("native_queued_view_in_octop")));
                        } catch (Exception error) {
                            if (error instanceof ServerApi.Failure && ((ServerApi.Failure)error).status >= 400 && ((ServerApi.Failure)error).status < 500) { try { draft.put("state", "draft"); drafts.save(draft); } catch (Exception ignored) { } }
                            activity.runOnUiThread(() -> information.setText("unknown".equals(draft.optString("state")) ? NativeStrings.text("native_outcome_unknown_check_tasks_before_retry") : NativeStrings.text("native_not_sent_draft_retained")));
                        }
                        activity.runOnUiThread(() -> { save.setEnabled(true); dialog.setCancelable(true); dialog.getButton(AlertDialog.BUTTON_NEGATIVE).setEnabled(true); });
                    });
                } catch (Exception ignored) { save.setEnabled(true); dialog.setCancelable(true); dialog.getButton(AlertDialog.BUTTON_NEGATIVE).setEnabled(true); }
            });
            dialog.show();
        } catch (Exception ignored) { Toast.makeText(activity, NativeStrings.text("native_could_not_open_share_sheet"), Toast.LENGTH_LONG).show(); }
    }
}
