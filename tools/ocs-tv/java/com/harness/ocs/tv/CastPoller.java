package com.harness.ocs.tv;

import android.content.Context;
import android.content.Intent;
import android.os.Handler;
import android.os.Looper;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;

/**
 * 轮询 OCS 的 /api/cast/current：手机在 OCS 页面点「投屏」后，电视自己拉 /obs/&lt;file&gt; 播放。
 *
 * 不走 Cast / AirPlay，两端只要能访问同一台 OCS 就行（同网段、跨网段、走公网都可以）。
 * seq 变化才视为新指令，避免每 3 秒重复起播放器；file 为空表示停止投屏。
 */
final class CastPoller {

    private static final long INTERVAL_MS = 3000;
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    private static volatile boolean running;
    private static long lastSeq = -1;
    private static String baseUrl;

    private CastPoller() {
    }

    /** 开始轮询；baseUrl 是 OCS 站点根地址（例如 http://192.168.0.201）。 */
    static void start(Context ctx, String url) {
        if (running) {
            baseUrl = url;
            return;
        }
        running = true;
        baseUrl = url;
        final Context app = ctx.getApplicationContext();
        MAIN.postDelayed(new Runnable() {
            @Override
            public void run() {
                if (!running) {
                    return;
                }
                final Context c = app;
                new Thread(new Runnable() {
                    @Override
                    public void run() {
                        pollOnce(c);
                    }
                }).start();
                MAIN.postDelayed(this, INTERVAL_MS);
            }
        }, INTERVAL_MS);
    }

    static void stop() {
        running = false;
    }

    private static void pollOnce(Context app) {
        String base = baseUrl;
        if (base == null) {
            return;
        }
        HttpURLConnection conn = null;
        try {
            URL u = new URL(trimSlash(base) + "/api/cast/current");
            conn = (HttpURLConnection) u.openConnection();
            conn.setConnectTimeout(3000);
            conn.setReadTimeout(3000);
            conn.setRequestProperty("Cache-Control", "no-store");
            StringBuilder sb = new StringBuilder();
            BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream(), "UTF-8"));
            try {
                String line;
                while ((line = reader.readLine()) != null) {
                    sb.append(line);
                }
            } finally {
                reader.close();
            }
            JSONObject obj = new JSONObject(sb.toString());
            long seq = obj.optLong("seq", 0);
            String file = obj.optString("file", "");
            if (seq == lastSeq) {
                return;
            }
            lastSeq = seq;
            if (file == null || file.isEmpty()) {
                return;   // 停止投屏
            }
            final String url = trimSlash(base) + "/obs/" + encodePath(file);
            final String name = file;
            MAIN.post(new Runnable() {
                @Override
                public void run() {
                    Intent i = new Intent(app, PlayerActivity.class);
                    i.putExtra("url", url);
                    i.putExtra("name", name);
                    i.putExtra("base", base);
                    i.putExtra("seq", seq);
                    i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    app.startActivity(i);
                }
            });
        } catch (Exception ignored) {
            // 网络抖动 / 服务器没起来时静默跳过，下一轮再试
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private static String trimSlash(String s) {
        return s.endsWith("/") ? s.substring(0, s.length() - 1) : s;
    }

    private static String encodePath(String p) {
        String[] parts = p.split("/");
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < parts.length; i++) {
            if (i > 0) {
                sb.append('/');
            }
            try {
                sb.append(URLEncoder.encode(parts[i], "UTF-8").replace("+", "%20"));
            } catch (Exception e) {
                sb.append(parts[i]);
            }
        }
        return sb.toString();
    }
}
