package com.harness.ocs.tv;

import android.content.Context;
import android.os.Build;
import android.util.Log;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.URL;
import java.util.Enumeration;

/**
 * 把自己的局域网地址报给 OCS：{"ip": "192.168.0.116", "port": 18099, "name": "..."}。
 *
 * 服务器收到就能直接 POST 到 http://ip:port/play 指挥这台电视，不必等它轮询、
 * 也不要求电视「连的就是这台」——所以手机用哪个域名点投屏都行，电视这边永远不用改设置。
 *
 * 同时报给两个地方：当前配置的服务器 + 内置默认服务器（ocs.dimond.top）。
 * 两个都报是为了让「默认那台」也能指挥这台电视，切换服务器不会把它从列表里弄丢。
 */
final class Announcer {

    private static final String TAG = "ocs-tv";
    private static final long INTERVAL_MS = 10000;

    private static volatile boolean running;
    private static String baseUrl;

    private Announcer() {
    }

    static void start(Context ctx, String base) {
        baseUrl = base;
        if (running) {
            return;
        }
        running = true;
        final Context app = ctx.getApplicationContext();
        Thread t = new Thread(new Runnable() {
            @Override
            public void run() {
                while (running) {
                    announce(app);
                    try {
                        Thread.sleep(INTERVAL_MS);
                    } catch (InterruptedException e) {
                        return;
                    }
                }
            }
        }, "ocs-tv-announce");
        t.setDaemon(true);
        t.start();
    }

    /** 服务器地址变了：下一轮直接报到新地址。 */
    static void setBase(String base) {
        baseUrl = base;
    }

    static void stop() {
        running = false;
    }

    private static void announce(Context app) {
        String ip = localIpv4();
        if (ip == null || ip.isEmpty()) {
            return;
        }
        String body = "{\"ip\":\"" + ip + "\",\"port\":" + TvHttpServer.PORT
                + ",\"name\":\"" + escapeJson(Build.MODEL) + "\"}";
        String current = baseUrl;
        String fallback = ServerDialogActivity.DEFAULT_URL;
        post(trimSlash(current) + "/api/tv/announce", body);
        if (current == null || !trimSlash(current).equalsIgnoreCase(trimSlash(fallback))) {
            post(trimSlash(fallback) + "/api/tv/announce", body);
        }
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

    /**
     * 本机的局域网 IPv4。优先用 wlan/eth 这类真实网卡，避开回环和 VPN 虚拟网卡——
     * 报错了地址服务器就推不到，所以这里宁可返回 null 让调用方跳过这一轮。
     */
    static String localIpv4() {
        try {
            String fallback = null;
            Enumeration<NetworkInterface> nics = NetworkInterface.getNetworkInterfaces();
            while (nics.hasMoreElements()) {
                NetworkInterface nic = nics.nextElement();
                if (!nic.isUp() || nic.isLoopback()) {
                    continue;
                }
                String name = nic.getName() == null ? "" : nic.getName().toLowerCase();
                Enumeration<InetAddress> addrs = nic.getInetAddresses();
                while (addrs.hasMoreElements()) {
                    InetAddress a = addrs.nextElement();
                    if (!(a instanceof Inet4Address) || a.isLoopbackAddress()) {
                        continue;
                    }
                    String ip = a.getHostAddress();
                    if (ip.startsWith("169.254.")) {
                        continue;
                    }
                    if (name.startsWith("wlan") || name.startsWith("eth")) {
                        return ip;
                    }
                    if (fallback == null) {
                        fallback = ip;
                    }
                }
            }
            return fallback;
        } catch (Exception e) {
            return null;
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
