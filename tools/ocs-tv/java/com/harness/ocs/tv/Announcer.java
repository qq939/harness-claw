package com.harness.ocs.tv;

import android.content.Context;
import android.os.Build;
import android.util.Log;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * 启动时报一次自己的局域网地址，让服务器记住「这台电视在哪」。
 *
 * 只报一次（不是心跳）：之后由服务器按需探测 18099 端口的 /ping 判断在线，
 * 待机时电视一个字节都不发。服务器地址被改了会再报一次。
 */
final class Announcer {

    private static final String TAG = "ocs-tv";
    private static String lastReported = null;

    private Announcer() {
    }

    static void announceOnce(Context ctx, String base, String why) {
        final String ip = TvHttpServer.localIpv4();
        if (ip == null || ip.isEmpty()) {
            return;
        }
        final String body = "{\"ip\":\"" + ip + "\",\"port\":" + TvHttpServer.PORT
                + ",\"name\":\"" + escapeJson(Build.MODEL) + "\"}";
        final String current = trimSlash(base);
        final String fallback = trimSlash(ServerDialogActivity.DEFAULT_URL);
        String key = current + "|" + ip;
        if (key.equals(lastReported)) {
            return;
        }
        lastReported = key;
        Log.i(TAG, "上报电视地址 " + ip + " → " + current + "（" + why + "）");
        final Context app = ctx.getApplicationContext();
        new Thread(new Runnable() {
            @Override
            public void run() {
                post(current + "/api/tv/announce", body);
                if (!current.equalsIgnoreCase(fallback)) {
                    post(fallback + "/api/tv/announce", body);
                }
            }
        }, "ocs-tv-announce").start();
    }

    private static void post(String endpoint, String body) {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(endpoint).openConnection();
            conn.setRequestMethod("POST");
            conn.setConnectTimeout(4000);
            conn.setReadTimeout(4000);
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json");
            OutputStream out = conn.getOutputStream();
            out.write(body.getBytes("UTF-8"));
            out.close();
            conn.getResponseCode();
        } catch (Exception e) {
            Log.d(TAG, "上报失败 " + endpoint + ": " + e);
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private static String trimSlash(String s) {
        if (s == null) {
            return "";
        }
        return s.endsWith("/") ? s.substring(0, s.length() - 1) : s;
    }

    private static String escapeJson(String s) {
        return s == null ? "" : s.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}
