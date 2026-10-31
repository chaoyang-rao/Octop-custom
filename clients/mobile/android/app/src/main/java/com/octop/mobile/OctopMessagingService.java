package com.octop.mobile;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.content.pm.PackageManager;
import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;
import org.json.JSONObject;
import java.net.URI;
import java.util.Map;
import java.util.concurrent.Executors;

public class OctopMessagingService extends FirebaseMessagingService {
    private static final java.util.concurrent.ExecutorService NETWORK = Executors.newSingleThreadExecutor();
    @Override public void onNewToken(String token) { register(this, token); }
    @Override public void onMessageReceived(RemoteMessage message) {
        Map<String, String> content = SealedNotification.open(this, message.getData());
        if (content == null) { content = new java.util.HashMap<>(); content.put("title", "Octop"); content.put("body", NativeStrings.text("native_new_activity")); content.put("notification_sound", "false"); }
        show(this, content);
    }
    static void register(Context context, String pushToken) {
        NETWORK.execute(() -> {
            try {
                if (Build.VERSION.SDK_INT >= 33 && context.checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) return;
                SecureStore store = new SecureStore(context); org.json.JSONArray servers = store.servers();
                for (int index = 0; index < servers.length(); index++) {
                    JSONObject server = servers.getJSONObject(index);
                    if (!MainActivity.allows(server, "notifications")) continue;
                    String credential = store.token(server.getString("id")); if (credential == null) continue;
                    try { ServerApi.request(new URI(server.getString("base_url")), "/api/mobile-access/self/push", "PUT", new JSONObject().put("platform", "fcm").put("token", pushToken), credential); }
                    catch (Exception ignored) { }
                }
            } catch (Exception ignored) { /* Never log device credentials or push tokens. */ }
        });
    }
    static void ensureChannel(Context context) {
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        manager.createNotificationChannel(new NotificationChannel("octop_activity", "Octop activity", NotificationManager.IMPORTANCE_DEFAULT));
        NotificationChannel silent = new NotificationChannel("octop_activity_silent", "Octop silent", NotificationManager.IMPORTANCE_LOW); silent.setSound(null, null); manager.createNotificationChannel(silent);
    }
    static void show(Context context, Map<String, String> data) {
        if (MainActivity.FOREGROUND) return;
        if (Build.VERSION.SDK_INT >= 33 && context.checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) return;
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        ensureChannel(context);
        Intent intent = new Intent(context, MainActivity.class).setFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        for (String key : new String[]{"server_fingerprint", "device_id", "thread_id", "agent_id"}) if (data.containsKey(key)) intent.putExtra(key, data.get(key));
        String route = data.getOrDefault("server_fingerprint", "") + ":" + data.getOrDefault("device_id", "") + ":" + data.getOrDefault("thread_id", "generic");
        int notificationID = route.hashCode();
        intent.setData(android.net.Uri.parse("octop-mobile://notification/" + Integer.toUnsignedString(notificationID)));
        PendingIntent pending = PendingIntent.getActivity(context, notificationID, intent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        String channel = "false".equals(data.get("notification_sound")) ? "octop_activity_silent" : "octop_activity";
        Notification notification = new Notification.Builder(context, channel).setSmallIcon(android.R.drawable.sym_action_chat)
                .setContentTitle(data.containsKey("title") ? data.get("title") : "Octop").setContentText(data.containsKey("body") ? data.get("body") : NativeStrings.text("native_new_activity")).setContentIntent(pending).setAutoCancel(true).build();
        manager.notify(notificationID, notification);
    }
}
