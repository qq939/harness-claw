package com.harness.ocs.tv;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;

/**
 * ocs TV —— 给电视/盒子用的壳：
 *   - 首页/文件列表用 WebView（Chrome 内核），遥控器方向键移动焦点、OK 确认
 *   - 视频一律不走 WebView：点标题进原生视频列表，点视频文件直接进原生播放器
 *     （极米 M1 这类投影仪的 WebView 解码能力弱，播视频会把渲染进程搞崩）
 *   - WebView 渲染进程即使崩了也能自己恢复，不会连带杀掉 App
 */
public class TvActivity extends Activity {

    private static final String PREFS = ServerDialogActivity.PREFS;
    private static final String KEY_URL = ServerDialogActivity.KEY_URL;
    private static final String DEFAULT_URL = ServerDialogActivity.DEFAULT_URL;

    private static final String[] VIDEO_EXT = {
            ".mp4", ".mkv", ".mov", ".m4v", ".webm", ".avi", ".ts", ".flv", ".wmv", ".mpg", ".mpeg"
    };

    private WebView web;
    private FrameLayout root;
    private String lastUrl;
    private String loadedBase;
    private long lastCrashAt;
    private final Handler ui = new Handler(Looper.getMainLooper());

    /** 遥控器 -> 页面：JS 从 shim.js 生成（构建脚本负责转义），见 ShimJs.java */
    private static final String SHIM_JS = ShimJs.JS;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        hideSystemUi();

        root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        setContentView(root);

        loadedBase = baseUrl();
        installWebView(loadedBase);        // 手机在 OCS 里点「投屏」后，电视自己拉流播放（轮询 /api/cast/current）
        CastPoller.start(this, loadedBase);
        // 常驻接收端：服务器按需探测这个端口判断在线，并直接推 /play 过来。
        // 启动时报一次地址（只一次，不是心跳）——之后待机零流量。
        TvHttpServer.start(this);
        Announcer.announceOnce(this, loadedBase, "启动");
    }

    @Override
    protected void onResume() {
        super.onResume();
        hideSystemUi();
        // 从「切换服务器」回来：地址变了就重载
        String now = baseUrl();
        if (web != null && !now.equals(loadedBase)) {
            loadedBase = now;
            web.loadUrl(now);
        }
    }

    private void hideSystemUi() {
        View d = getWindow().getDecorView();
        d.setSystemUiVisibility(View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_FULLSCREEN
                | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
    }

    private void installWebView(String url) {
        if (web != null) {
            root.removeView(web);
            web.destroy();
            web = null;
        }
        WebView w = new WebView(this);
        w.setLayoutParams(new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        w.setFocusable(true);
        w.setFocusableInTouchMode(true);
        configure(w);
        root.addView(w);
        web = w;
        lastUrl = url;
        w.loadUrl(url);
        w.requestFocus();
    }

    private void configure(WebView w) {
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setBuiltInZoomControls(false);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setUserAgentString(s.getUserAgentString() + " ocsTV/1.3");
        s.setTextZoom(130);          // 电视上看不清小字，整体放大
        s.setSupportZoom(false);

        w.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                lastUrl = url;
                try {
                    view.evaluateJavascript(SHIM_JS, null);
                } catch (Exception ignored) {
                }
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return route(url);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (Build.VERSION.SDK_INT >= 23 && request != null && request.isForMainFrame()) {
                    showErrorPage(String.valueOf(error.getDescription()));
                }
            }

            @Override
            public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
                boolean crashed = Build.VERSION.SDK_INT >= 26 && detail != null && detail.didCrash();
                onRendererGone(crashed);
                return true;   // 已处理，别杀进程
            }
        });

        w.setWebChromeClient(new WebChromeClient());

        // WebView 默认不处理下载：首页右上角「TV版」是 .apk 链接，没有这个监听器点了完全没反应。
        // 自己下载 + 交给系统安装器（见 UpdateInstaller），这样电视上可以直接升级。
        w.setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) -> {
            if (url == null) return;
            if (UpdateInstaller.looksLikeApk(url)) {
                UpdateInstaller.downloadAndInstall(this, url);
            } else {
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                } catch (Exception ignored) {
                    toast("这台设备打不开这个链接");
                }
            }
        });
    }

    /** 拦截导航：/video 走原生列表，视频文件走原生播放器，其余留给 WebView */
    private boolean route(String url) {
        if (url == null) return false;
        Uri u = Uri.parse(url);
        String path = u.getPath();
        if (path == null) path = "";
        String lower = path.toLowerCase();

        if ("/video".equals(path) || "/video/".equals(path)) {
            startActivity(new Intent(this, VideoListActivity.class));
            return true;
        }
        if (lower.startsWith("/preview/")) {
            String name = path.substring("/preview/".length());
            if (isVideoName(name)) {
                playVideo(base() + "/obs/" + Uri.encode(name), name);
                return true;
            }
            return false;
        }
        if (isVideoName(lower)) {
            playVideo(url, nameOf(path));
            return true;
        }
        if (url.startsWith("http://") || url.startsWith("https://")) {
            return false;
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, u));
        } catch (Exception ignored) {
        }
        return true;
    }

    private boolean isVideoName(String n) {
        String s = n.toLowerCase();
        for (String ext : VIDEO_EXT) {
            if (s.endsWith(ext)) return true;
        }
        return false;
    }

    private String nameOf(String path) {
        int i = path.lastIndexOf('/');
        return i >= 0 ? path.substring(i + 1) : path;
    }

    private void playVideo(String url, String name) {
        Intent it = new Intent(this, PlayerActivity.class);
        it.putExtra("url", url);
        it.putExtra("name", name);
        startActivity(it);
    }

    /** 渲染进程没了：提示 + 重建 WebView，退回文件列表（别再回那个把渲染搞崩的页面） */
    private void onRendererGone(final boolean crashed) {
        final long now = System.currentTimeMillis();
        final boolean repeat = (now - lastCrashAt) < 20000;
        lastCrashAt = now;
        ui.post(() -> {
            String home = baseUrl();
            String target = (repeat || lastUrl == null || lastUrl.contains("/video")) ? home : lastUrl;
            toast(crashed ? "页面渲染崩了（电视内存/解码限制），已自动回到文件列表"
                    : "页面渲染进程被系统回收，已重新加载");
            installWebView(target);
        });
    }

    private void showErrorPage(String desc) {
        String html = "<html><head><meta charset='utf-8'><style>"
                + "body{background:#111;color:#ddd;font:20px/1.6 sans-serif;padding:60px}"
                + "h1{color:#4ea1ff;font-size:26px}</style></head><body>"
                + "<h1>打不开这个页面</h1><p>" + (desc == null ? "" : desc) + "</p>"
                + "<p>遥控器「菜单」键可切换服务器，返回键回上一页。</p></body></html>";
        try {
            web.loadDataWithBaseURL(baseUrl(), html, "text/html", "utf-8", null);
        } catch (Exception ignored) {
        }
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        String dir = null;
        switch (keyCode) {
            case KeyEvent.KEYCODE_DPAD_UP:
                dir = "up";
                break;
            case KeyEvent.KEYCODE_DPAD_DOWN:
                dir = "down";
                break;
            case KeyEvent.KEYCODE_DPAD_LEFT:
                dir = "left";
                break;
            case KeyEvent.KEYCODE_DPAD_RIGHT:
                dir = "right";
                break;
            case KeyEvent.KEYCODE_DPAD_CENTER:
            case KeyEvent.KEYCODE_ENTER:
            case KeyEvent.KEYCODE_NUMPAD_ENTER:
                dir = "ok";
                break;
            case KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE:
                js("document.dispatchEvent(new KeyboardEvent('keydown',{key:' ',bubbles:true}))");
                return true;
            case KeyEvent.KEYCODE_BACK:
                if (web != null && web.canGoBack()) {
                    web.goBack();
                } else {
                    confirmExit();
                }
                return true;
            case KeyEvent.KEYCODE_MENU:
            case KeyEvent.KEYCODE_INFO:
                startActivity(new Intent(this, ServerDialogActivity.class));
                return true;
            default:
                break;
        }
        if (dir != null) {
            js("window.__ocsDpad && window.__ocsDpad('" + dir + "')");
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    private void js(String code) {
        try {
            if (web != null) web.evaluateJavascript(code, null);
        } catch (Exception ignored) {
        }
    }

    private void confirmExit() {
        new AlertDialog.Builder(this)
                .setMessage("退出 ocs TV？")
                .setPositiveButton("退出", (d, w) -> finish())
                .setNegativeButton("留下", null)
                .show();
    }

    private String base() {
        return baseUrl().replaceAll("/+$", "");
    }

    private String baseUrl() {
        SharedPreferences sp = getSharedPreferences(PREFS, MODE_PRIVATE);
        return sp.getString(KEY_URL, DEFAULT_URL);
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
    }

    @Override
    protected void onDestroy() {
        CastPoller.stop();
        TvHttpServer.stop();
        if (web != null) {
            root.removeView(web);
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
