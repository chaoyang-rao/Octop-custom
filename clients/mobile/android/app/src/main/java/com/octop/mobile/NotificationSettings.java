package com.octop.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.widget.ArrayAdapter;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONArray;
import org.json.JSONObject;
import java.net.URI;
import java.text.DateFormat;
import java.util.Date;
import java.util.HashSet;
import java.util.Set;
import java.util.TimeZone;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.atomic.AtomicBoolean;

final class NotificationSettings {
    static void open(Activity activity, JSONObject server, SecureStore store, ExecutorService network) {
        network.execute(() -> {
            try {
                URI base = new URI(server.getString("base_url")); String token = store.token(server.getString("id"));
                JSONObject device = ServerApi.request(base, "/api/mobile-access/self", "GET", null, token);
                JSONObject preferences = device.getJSONObject("notification_preferences");
                JSONArray experts = new JSONArray(); String timezone = null;
                try { experts = ServerApi.array(base, "/api/agents", token); } catch (Exception ignored) { }
                try { timezone = ServerApi.request(base, "/api/settings/timezone", "GET", null, token).getString("timezone"); } catch (Exception ignored) { }
                JSONArray labels = experts; String zone = timezone;
                activity.runOnUiThread(() -> dialog(activity, server, preferences, labels, zone, store, network));
            } catch (Exception ignored) { activity.runOnUiThread(() -> Toast.makeText(activity, NativeStrings.text("native_could_not_read_notification_choices"), Toast.LENGTH_LONG).show()); }
        });
    }
    private static void dialog(Activity activity, JSONObject server, JSONObject preferences, JSONArray experts, String timezone, SecureStore store, ExecutorService network) {
        ScrollView scroll = new ScrollView(activity); LinearLayout form = new LinearLayout(activity); form.setOrientation(LinearLayout.VERTICAL); form.setPadding(32, 16, 32, 16); scroll.addView(form);
        Spinner level = new Spinner(activity); String[] levels = {"all", "needs-me", "none"};
        level.setAdapter(new ArrayAdapter<>(activity, android.R.layout.simple_spinner_dropdown_item, new String[]{NativeStrings.text("native_all"), NativeStrings.text("native_needs_me"), NativeStrings.text("native_none")}));
        for (int i = 0; i < levels.length; i++) if (levels[i].equals(preferences.optString("level", "all"))) level.setSelection(i);
        form.addView(level);
        TextView currentMute = new TextView(activity);
        if (!preferences.isNull("muted_until")) {
            long until = preferences.optLong("muted_until"); DateFormat formatter = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT, NativeStrings.locale()); if (timezone != null) formatter.setTimeZone(TimeZone.getTimeZone(timezone));
            currentMute.setText(until == 0 ? NativeStrings.text("native_muted_until_changed") : timezone == null ? NativeStrings.text("native_muted_timezone_unavailable") : NativeStrings.text("native_muted_until") + formatter.format(new Date(until * 1000)));
        } else currentMute.setText(NativeStrings.text("native_not_muted"));
        form.addView(currentMute);
        Spinner mute = new Spinner(activity); mute.setAdapter(new ArrayAdapter<>(activity, android.R.layout.simple_spinner_dropdown_item, new String[]{NativeStrings.text("native_keep"), NativeStrings.text("native_unmute"), NativeStrings.text("native_15_minutes"), NativeStrings.text("native_1_hour"), NativeStrings.text("native_8_hours"), NativeStrings.text("native_until_changed")})); form.addView(mute);
        CheckBox sound = new CheckBox(activity); sound.setText(NativeStrings.text("native_play_notification_sound")); sound.setChecked(preferences.optBoolean("sound", true)); form.addView(sound);
        CheckBox preview = new CheckBox(activity); preview.setText(NativeStrings.text("native_show_filtered_previews")); preview.setChecked(preferences.optBoolean("preview", false)); form.addView(preview);
        AtomicBoolean consent = new AtomicBoolean(preferences.optBoolean("preview", false));
        preview.setOnCheckedChangeListener((view, checked) -> {
            if (checked && !consent.get()) {
                preview.setChecked(false);
                new AlertDialog.Builder(activity).setTitle(NativeStrings.text("native_enable_previews"))
                    .setMessage(NativeStrings.text("native_filtered_text_is_sent_to_your_push_provider_only_aft_c127a9"))
                    .setNegativeButton(NativeStrings.text("native_cancel"), null).setPositiveButton(NativeStrings.text("native_enable"), (dialog, which) -> { consent.set(true); preview.setChecked(true); }).show();
            }
        });
        Set<String> muted = new HashSet<>(); JSONArray oldMuted = preferences.optJSONArray("muted_agent_ids");
        if (oldMuted != null) for (int i = 0; i < oldMuted.length(); i++) muted.add(oldMuted.optString(i));
        TextView heading = new TextView(activity); heading.setText(NativeStrings.text("native_expert_notifications")); form.addView(heading);
        for (int i = 0; i < experts.length(); i++) {
            JSONObject expert = experts.optJSONObject(i); if (expert == null) continue;
            String id = expert.optString("agent_id"); if (id.isEmpty()) continue;
            CheckBox enabled = new CheckBox(activity); enabled.setText(expert.optString("name", id)); enabled.setChecked(!muted.contains(id));
            enabled.setOnCheckedChangeListener((view, checked) -> { if (checked) muted.remove(id); else muted.add(id); }); form.addView(enabled);
        }
        AlertDialog dialog = new AlertDialog.Builder(activity).setTitle(NativeStrings.text("native_notifications")).setView(scroll).setNegativeButton(NativeStrings.text("native_cancel"), null).setPositiveButton(NativeStrings.text("native_save"), null).create();
        dialog.setOnShowListener(event -> dialog.getButton(DialogInterface.BUTTON_POSITIVE).setOnClickListener(view -> {
            try {
                JSONObject changes = new JSONObject().put("level", levels[level.getSelectedItemPosition()]).put("sound", sound.isChecked()).put("preview", preview.isChecked()).put("muted_agent_ids", new JSONArray(muted));
                int choice = mute.getSelectedItemPosition(); Object until = preferences.opt("muted_until");
                if (choice == 1) until = JSONObject.NULL;
                else if (choice >= 2 && choice <= 4) until = System.currentTimeMillis() / 1000 + new int[]{0, 0, 900, 3600, 28800}[choice];
                else if (choice == 5) until = 0;
                changes.put("muted_until", until == null ? JSONObject.NULL : until);
                dialog.getButton(DialogInterface.BUTTON_POSITIVE).setEnabled(false);
                network.execute(() -> {
                    try {
                        JSONObject saved = ServerApi.request(new URI(server.getString("base_url")), "/api/mobile-access/self/notifications", "PUT", changes, store.token(server.getString("id")));
                        server.put("notification_preferences", saved); store.updateServer(server);
                        activity.runOnUiThread(dialog::dismiss);
                    } catch (Exception ignored) { activity.runOnUiThread(() -> { dialog.getButton(DialogInterface.BUTTON_POSITIVE).setEnabled(true); Toast.makeText(activity, NativeStrings.text("native_could_not_save_choices"), Toast.LENGTH_LONG).show(); }); }
                });
            } catch (Exception ignored) { Toast.makeText(activity, NativeStrings.text("native_check_choices"), Toast.LENGTH_LONG).show(); }
        }));
        dialog.show();
    }
}
