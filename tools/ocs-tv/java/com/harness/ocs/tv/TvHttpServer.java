package com.harness.ocs.tv;

import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.net.URLEncoder;
import java.util.HashMap;
import java.util.Map;

/**
 * 电视侧的接收端：在局域网固定端口上等着，OCS 服务器把播放指令直接 POST 过来。
 *
 * 有了这个端口，投屏就不再依赖「电视当前连的是哪台 OCS」——只要服务器能访问到电视的
 * 局域网地址，就能指挥它；换域名、换实例、多台服务器共用同一台电视都不用再去电视上改设置。
 *
 * 协议是最小的 HTTP/1.1：
 *   GET  /ping                          → 报身份（服务器用来确认「这台电视真的在听」）
 *   POST /play?file=&base=&seq=         → 立刻播放 base/obs/file
 *   POST /stop                          → 退出播放
 */
final class TvHttpServer {

    static final int PORT = 18099;
    private static final String VER = "1.8";
    private static final String TAG = "ocs-tv";

    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    private static ServerSocket server;
    private static volatile boolean running;
    private static Context appCtx;

    private TvHttpServer() {
    }

    /** 开始监听；重复调用无副作用（地址变了不用重启）。 */
    static synchronized void start(Context ctx) {
        if (running) {
            return;
        }
        appCtx = ctx.getApplicationContext();
        running = true;
        Thread t = new Thread(new Runnable() {
            @Override
            public void run() {
                loop();
            }
        }, "ocs-tv-http");
        t.setDaemon(true);
        t.start();
    }

    static synchronized void stop() {
        running = false;
        if (server != null) {
            try {
                server.close();
            } catch (Exception ignored) {
                // 关掉监听失败无所谓，进程退出时内核会回收
            }
            server = null;
        }
    }

    private static void loop() {
        while (running) {
            try {
                if (server == null) {
                    ServerSocket s = new ServerSocket();
                    s.setReuseAddress(true);
                    s.bind(new InetSocketAddress(PORT));
                    server = s;
                    Log.i(TAG, "HTTP 接收端已监听 :" + PORT);
                }
                final Socket sock = server.accept();
                Thread worker = new Thread(new Runnable() {
                    @Override
                    public void run() {
                        handle(sock);
                    }
                }, "ocs-tv-http-req");
                worker.setDaemon(true);
                worker.start();
            } catch (Exception e) {
                if (!running) {
                    return;
                }
                // 端口被占用 / 网卡抖动：歇一下再重试，别把小错误刷成死循环
                try {
                    Thread.sleep(1000);
                } catch (InterruptedException ie) {
                    return;
                }
            }
        }
    }

    private static void handle(Socket sock) {
        try {
            sock.setSoTimeout(4000);
            InputStream in = new BufferedInputStream(sock.getInputStream());
            String requestLine = readLine(in);
            if (requestLine == null || requestLine.isEmpty()) {
                return;
            }
            int contentLength = 0;
            String line;
            while ((line = readLine(in)) != null && !line.isEmpty()) {
                int colon = line.indexOf(':');
                if (colon > 0 && "content-length".equalsIgnoreCase(line.substring(0, colon).trim())) {
                    try {
                        contentLength = Integer.parseInt(line.substring(colon + 1).trim());
                    } catch (NumberFormatException ignored) {
                        contentLength = 0;
                    }
                }
            }
            if (contentLength > 0) {
                byte[] body = new byte[Math.min(contentLength, 8192)];
                int read = 0;
                while (read < body.length) {
                    int n = in.read(body, read, body.length - read);
                    if (n < 0) {
                        break;
                    }
                    read += n;
                }
            }

            String[] parts = requestLine.split(" ");
            String method = parts.length > 0 ? parts[0] : "GET";
            String target = parts.length > 1 ? parts[1] : "/";
            String path = target;
            String query = "";
            int q = target.indexOf('?');
            if (q >= 0) {
                path = target.substring(0, q);
                query = target.substring(q + 1);
            }
            Map<String, String> params = parseQuery(query);

            if ("/ping".equals(path)) {
                respond(sock, 200, "{\"app\":\"ocs-tv\",\"ver\":\"" + VER + "\",\"name\":\"" + escapeJson(Build.MODEL) + "\""
                        + ",\"ip\":\"" + localIpv4() + "\",\"port\":" + PORT + "}");
                return;
            }
            if ("/play".equals(path) && "POST".equalsIgnoreCase(method)) {
                long seq = parseLong(params.get("seq"));
                String file = params.get("file");
                String base = params.get("base");
                if (file == null || file.isEmpty()) {
                    respond(sock, 400, "{\"ok\":false,\"error\":\"no file\"}");
                    return;
                }
                play(file, base, seq);
                respond(sock, 200, "{\"ok\":true,\"seq\":" + seq + "}");
                return;
            }
            if ("/state".equals(path)) {
                // 调试用：当前播到哪、是否暂停、倍速多少（同步有没有生效一眼可见）
                respond(sock, 200, PlayerActivity.stateJson());
                return;
            }
            if ("/ctl".equals(path)) {
                // 手机是遥控器：进度、播放/暂停、倍速都跟着手机走
                double pos = parseDouble(params.get("pos"), -1);
                boolean paused = "1".equals(params.get("paused")) || "true".equals(params.get("paused"));
                float rate = (float) parseDouble(params.get("rate"), 0);
                PlayerActivity.remote(pos, paused, rate);
                respond(sock, 200, "{\"ok\":true}");
                return;
            }
            if ("/stop".equals(path)) {
                MAIN.post(new Runnable() {
                    @Override
                    public void run() {
                        // 关掉正在播的播放器就是「停止投屏」；没在播就是空操作
                        PlayerActivity.finishAll();
                    }
                });
                respond(sock, 200, "{\"ok\":true}");
                return;
            }
            respond(sock, 404, "{\"ok\":false}");
        } catch (Exception e) {
            Log.w(TAG, "请求处理失败: " + e);
        } finally {
            try {
                sock.close();
            } catch (Exception ignored) {
                // 对端已断开，忽略
            }
        }
    }

    /** 起播放器；ack 会在播放器拿到第一帧后自己发回去，所以这里只管把指令变成 Intent。 */
    private static void play(final String file, final String base, final long seq) {
        final String playBase = (base == null || base.isEmpty()) ? ServerDialogActivity.DEFAULT_URL : base;
        MAIN.post(new Runnable() {
            @Override
            public void run() {
                try {
                    // 先关掉上一集：投屏是「跟着手机换台」，叠着开会在屏幕上留下两个播放器，
                    // 后起的那个拿不到焦点、不会走 onPrepared，回执就永远等不到。
                    PlayerActivity.finishAll();
                    Intent i = new Intent(appCtx, PlayerActivity.class);
                    i.putExtra("url", trimSlash(playBase) + "/obs/" + encodePath(file));
                    i.putExtra("name", file);
                    i.putExtra("base", playBase);
                    i.putExtra("seq", seq);
                    i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    appCtx.startActivity(i);
                } catch (Exception e) {
                    Log.w(TAG, "起播放器失败: " + e);
                }
            }
        });
    }

    private static void respond(Socket sock, int code, String body) {
        try {
            byte[] bytes = body.getBytes("UTF-8");
            String head = "HTTP/1.1 " + code + " " + (code == 200 ? "OK" : "ERR") + "\r\n"
                    + "Content-Type: application/json; charset=utf-8\r\n"
                    + "Content-Length: " + bytes.length + "\r\n"
                    + "Connection: close\r\n\r\n";
            OutputStream out = sock.getOutputStream();
            out.write(head.getBytes("UTF-8"));
            out.write(bytes);
            out.flush();
        } catch (Exception ignored) {
            // 客户端提前断开：没有需要清理的状态
        }
    }

    private static String readLine(InputStream in) throws Exception {
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        int c;
        while ((c = in.read()) != -1) {
            if (c == '\n') {
                break;
            }
            if (c != '\r') {
                buf.write(c);
            }
            if (buf.size() > 8192) {
                break;
            }
        }
        if (c == -1 && buf.size() == 0) {
            return null;
        }
        return new String(buf.toByteArray(), "UTF-8");
    }

    private static Map<String, String> parseQuery(String query) {
        Map<String, String> map = new HashMap<>();
        if (query == null || query.isEmpty()) {
            return map;
        }
        for (String pair : query.split("&")) {
            if (pair.isEmpty()) {
                continue;
            }
            int eq = pair.indexOf('=');
            String k = eq >= 0 ? pair.substring(0, eq) : pair;
            String v = eq >= 0 ? pair.substring(eq + 1) : "";
            try {
                map.put(URLDecoder.decode(k, "UTF-8"), URLDecoder.decode(v, "UTF-8"));
            } catch (Exception ignored) {
                map.put(k, v);
            }
        }
        return map;
    }

    private static long parseLong(String s) {
        try {
            return Long.parseLong(s.trim());
        } catch (Exception e) {
            return 0;
        }
    }

    private static double parseDouble(String s, double dflt) {
        if (s == null) {
            return dflt;
        }
        try {
            return Double.parseDouble(s.trim());
        } catch (Exception e) {
            return dflt;
        }
    }

    private static String trimSlash(String s) {
        return s.endsWith("/") ? s.substring(0, s.length() - 1) : s;
    }

    private static String escapeJson(String s) {
        return s == null ? "" : s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    /**
     * 本机的局域网 IPv4，随 /ping 一起报给服务器（服务器据此把地址显示/记录下来）。
     * 优先真实网卡，避开回环、169.254 和 VPN 虚拟网卡；取不到就返回空串。
     */
    static String localIpv4() {
        try {
            String fallback = null;
            java.util.Enumeration<java.net.NetworkInterface> nics =
                    java.net.NetworkInterface.getNetworkInterfaces();
            while (nics != null && nics.hasMoreElements()) {
                java.net.NetworkInterface nic = nics.nextElement();
                if (!nic.isUp() || nic.isLoopback()) {
                    continue;
                }
                String name = nic.getName() == null ? "" : nic.getName().toLowerCase();
                java.util.Enumeration<java.net.InetAddress> addrs = nic.getInetAddresses();
                while (addrs.hasMoreElements()) {
                    java.net.InetAddress a = addrs.nextElement();
                    if (!(a instanceof java.net.Inet4Address) || a.isLoopbackAddress()) {
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
            return fallback == null ? "" : fallback;
        } catch (Exception e) {
            return "";
        }
    }

    static String encodePath(String p) {        String[] parts = p.split("/");
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
