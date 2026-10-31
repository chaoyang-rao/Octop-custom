package com.octop.mobile;

import org.json.JSONObject;
import org.json.JSONArray;
import org.json.JSONTokener;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.nio.charset.StandardCharsets;

final class ServerApi {
    static final class Failure extends Exception {
        final int status;
        Failure(int status, String message) { super(message); this.status = status; }
    }
    static URI validate(String value) throws Exception {
        URI uri = new URI(value.trim()); String host = uri.getHost();
        boolean local = "127.0.0.1".equals(host) || "localhost".equals(host) || "[::1]".equals(host);
        if (host == null || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null || !(uri.getPath().isEmpty() || uri.getPath().equals("/")) || !("https".equals(uri.getScheme()) || local && "http".equals(uri.getScheme())))
            throw new Exception(NativeStrings.text("native_enter_the_server_https_address"));
        return new URI(uri.getScheme(), null, host.toLowerCase(java.util.Locale.ROOT), uri.getPort(), "", null, null);
    }
    static JSONObject request(URI base, String path, String method, JSONObject body, String token) throws Exception {
        Object value = json(base, path, method, body, token);
        if (!(value instanceof JSONObject)) throw new Exception("Invalid server response");
        return (JSONObject) value;
    }
    static JSONArray array(URI base, String path, String token) throws Exception {
        Object value = json(base, path, "GET", null, token);
        if (!(value instanceof JSONArray)) throw new Exception("Invalid server response");
        return (JSONArray) value;
    }
    private static Object json(URI base, String path, String method, JSONObject body, String token) throws Exception {
        URI target = base.resolve(path);
        if (!base.getScheme().equals(target.getScheme()) || !base.getHost().equals(target.getHost()) || base.getPort() != target.getPort()) throw new Exception("Invalid server path");
        HttpURLConnection connection = (HttpURLConnection) new URL(target.toString()).openConnection();
        connection.setInstanceFollowRedirects(false); connection.setConnectTimeout(15000); connection.setReadTimeout(20000);
        connection.setRequestMethod(method); connection.setRequestProperty("Content-Type", "application/json");
        if (token != null) connection.setRequestProperty("Authorization", "Bearer " + token);
        try {
            if (body != null) { connection.setDoOutput(true); try (var output = connection.getOutputStream()) { output.write(body.toString().getBytes(StandardCharsets.UTF_8)); } }
            int status = connection.getResponseCode();
            if (status < 200 || status >= 300) throw new Failure(status, status == 401 ? NativeStrings.text("native_device_authorization_expired") : NativeStrings.text("native_server_request_failed") + status + ")");
            if (status == 204) return new JSONObject();
            try (InputStream input = connection.getInputStream(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[8192]; int count;
                while ((count = input.read(buffer)) >= 0) { output.write(buffer, 0, count); if (output.size() > 1024 * 1024) throw new Exception("Server response is too large"); }
                return new JSONTokener(output.toString(StandardCharsets.UTF_8.name())).nextValue();
            }
        } finally { connection.disconnect(); }
    }
    static JSONObject upload(URI base, String agent, String filename, String mime, byte[] data, String token) throws Exception {
        if (!agent.matches("[A-Za-z0-9_:-]+")) throw new Exception("Invalid expert");
        URI target = base.resolve("/api/agents/" + agent + "/upload");
        HttpURLConnection connection = (HttpURLConnection) target.toURL().openConnection();
        connection.setInstanceFollowRedirects(false); connection.setConnectTimeout(15000); connection.setReadTimeout(20000); connection.setRequestMethod("POST"); connection.setDoOutput(true);
        String boundary = "Octop-" + java.util.UUID.randomUUID();
        connection.setRequestProperty("Authorization", "Bearer " + token); connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
        filename = filename.replace('\\', '_').replace('"', '_').replace('\r', '_').replace('\n', '_');
        if (!mime.matches("[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+")) mime = "application/octet-stream";
        byte[] prefix = ("--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"" + filename + "\"\r\nContent-Type: " + mime + "\r\n\r\n").getBytes(StandardCharsets.UTF_8);
        byte[] suffix = ("\r\n--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8);
        connection.setFixedLengthStreamingMode(prefix.length + data.length + suffix.length);
        try {
            try (var output = connection.getOutputStream()) { output.write(prefix); output.write(data); output.write(suffix); }
            int status = connection.getResponseCode(); if (status < 200 || status >= 300) throw new Failure(status, "Upload failed");
            try (InputStream input = connection.getInputStream(); ByteArrayOutputStream result = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[8192]; int count; while ((count = input.read(buffer)) >= 0) { if (result.size() + count > 1024 * 1024) throw new Exception("Invalid upload response"); result.write(buffer, 0, count); }
                return new JSONObject(result.toString(StandardCharsets.UTF_8.name()));
            }
        } finally { connection.disconnect(); }
    }

}
