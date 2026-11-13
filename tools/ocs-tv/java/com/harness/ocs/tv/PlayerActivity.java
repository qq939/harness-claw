package com.harness.ocs.tv;

import android.app.Activity;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.View;
import android.widget.MediaController;
import android.widget.Toast;
import android.widget.VideoView;

/**
 * 原生播放器：电视上的视频一律走这里，不经过 WebView，避免渲染进程被解码搞崩。
 * 遥控器：OK / 播放暂停键 = 播放暂停（会带出进度条），返回 = 退出。
 */
public class PlayerActivity extends Activity {

    private VideoView vv;
    private String name;
    private String origUrl;
    private String curUrl;
    private String base;
    private long seq;
    private boolean triedAlt;

    /** 正在播的播放器实例：服务器的 /stop 指令要能一把关掉全部（可能叠了几个）。 */
    private static final java.util.Set<PlayerActivity> LIVE =
            java.util.Collections.newSetFromMap(new java.util.WeakHashMap<PlayerActivity, Boolean>());

    /** 停止投屏：把当前所有播放器关掉；没在播就是空操作。 */
    static void finishAll() {
        for (PlayerActivity a : new java.util.ArrayList<>(LIVE)) {
            try {
                a.finish();
            } catch (Exception ignored) {
                // 实例已经销毁，忽略
            }
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LIVE.add(this);
        getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);

        String url = getIntent().getStringExtra("url");
        name = getIntent().getStringExtra("name");
        base = getIntent().getStringExtra("base");
        seq = getIntent().getLongExtra("seq", 0);
        if (url == null) {
            finish();
            return;
        }
        origUrl = url;
        curUrl = normalize(url);

        vv = new VideoView(this);
        setContentView(vv);

        MediaController mc = new MediaController(this);
        mc.setAnchorView(vv);
        vv.setMediaController(mc);

        vv.setOnPreparedListener((MediaPlayer mp) -> {
            mp.setLooping(false);
            vv.start();
            toast("正在播放：" + (name == null ? "" : name));
            // 真正拿到第一帧才开始回执：网页据此显示「已投屏」，播不起来的不会误报成功
            ackCast(base, seq);
        });
        vv.setOnErrorListener((mp, what, extra) -> {
            // 域名站点常把 http 301 到 https；MediaPlayer 不一定跟随，这里换一次协议再试
            if (!triedAlt) {
                triedAlt = true;
                String alt = switchScheme(curUrl);
                if (!alt.equals(curUrl)) {
                    toast("换个协议重试…");
                    curUrl = alt;
                    vv.setVideoURI(Uri.parse(alt));
                    return true;
                }
            }
            toast("这台设备播不了这个格式（" + what + "/" + extra + "）");
            finish();
            return true;
        });
        vv.setOnCompletionListener(mp -> toast("播放结束"));
        vv.setVideoURI(Uri.parse(curUrl));
        vv.requestFocus();
    }

    /** 通知 OCS「投屏指令已经真的播起来了」，网页看到回执才显示「已投屏」。 */
    private void ackCast(final String baseUrl, final long castSeq) {
        if (baseUrl == null || baseUrl.isEmpty() || castSeq <= 0) {
            return;
        }
        final String endpoint = baseUrl + "/api/cast/ack";
        final String body = "{\"seq\":" + castSeq + "}";
        new Thread(new Runnable() {
            @Override
            public void run() {
                java.net.HttpURLConnection conn = null;
                try {
                    conn = (java.net.HttpURLConnection) new java.net.URL(endpoint).openConnection();
                    conn.setRequestMethod("POST");
                    conn.setConnectTimeout(3000);
                    conn.setReadTimeout(3000);
                    conn.setDoOutput(true);
                    conn.setRequestProperty("Content-Type", "application/json");
                    conn.getOutputStream().write(body.getBytes("UTF-8"));
                    conn.getResponseCode();
                } catch (Exception ignored) {
                    // 回执失败不影响播放
                } finally {
                    if (conn != null) {
                        conn.disconnect();
                    }
                }
            }
        }).start();
    }

    /** 非 IP/localhost 的 http 地址直接升级成 https（这些站点都会 301 到 https） */
    private String normalize(String u) {
        try {
            java.net.URL p = new java.net.URL(u);
            String host = p.getHost();
            if ("http".equals(p.getProtocol()) && host != null
                    && !host.matches("\\d{1,3}(\\.\\d{1,3}){3}") && !"localhost".equals(host)) {
                return "https://" + u.substring("http://".length());
            }
        } catch (Exception ignored) {
        }
        return u;
    }

    private String switchScheme(String u) {
        if (u.startsWith("https://")) return "http://" + u.substring(8);
        if (u.startsWith("http://")) return "https://" + u.substring(7);
        return u;
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        switch (keyCode) {
            case KeyEvent.KEYCODE_DPAD_CENTER:
            case KeyEvent.KEYCODE_ENTER:
            case KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE:
                toggle();
                return true;
            case KeyEvent.KEYCODE_BACK:
                finish();
                return true;
            case KeyEvent.KEYCODE_DPAD_LEFT:
                if (vv != null) vv.seekTo(Math.max(0, vv.getCurrentPosition() - 10000));
                return true;
            case KeyEvent.KEYCODE_DPAD_RIGHT:
                if (vv != null) vv.seekTo(vv.getCurrentPosition() + 10000);
                return true;
            default:
                return super.onKeyDown(keyCode, event);
        }
    }

    private void toggle() {
        if (vv == null) return;
        if (vv.isPlaying()) {
            vv.pause();
            toast("暂停");
        } else {
            vv.start();
        }
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }

    @Override
    protected void onDestroy() {
        LIVE.remove(this);
        if (vv != null) {
            try {
                vv.stopPlayback();
            } catch (Exception ignored) {
            }
        }
        super.onDestroy();
    }
}
