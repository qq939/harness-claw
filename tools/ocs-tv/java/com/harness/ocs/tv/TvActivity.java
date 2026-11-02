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
import android.text.InputType;
import android.util.TypedValue;
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
import android.widget.BaseAdapter;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ListAdapter;
import android.widget.TextView;
import android.widget.Toast;

/**
 * ocs TV —— 给电视/盒子用的壳：
 *   - 全屏无地址栏，遥控器操作（方向键移动焦点/翻视频，OK 确认，返回退出）
 *   - 页面本身用 WebView 渲染；注入一段 JS，把遥控器按键翻译成页面能懂的操作
 *   - 电视上的 WebView 容易在重的页面（/video、大图）把渲染进程搞崩，崩了要能自己恢复，
 *     否则系统会把整个 App 进程一起杀掉（表现就是「闪退」）
 */
public class TvActivity extends Activity {

    private static final String PREFS = "ocs_tv";
    private static final String KEY_URL = "base_url";
    private static final String DEFAULT_URL = "http://oas.dimond.top";

    private static final String[] SERVERS = {
            "http://oas.dimond.top",
            "http://obs.dimond.top",
            "http://ocs.dimond.top",
            "http://192.168.0.201",
            "http://192.168.0.202",
    };

    private WebView web;
    private FrameLayout root;
    private String lastUrl;
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

        installWebView(baseUrl());
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

    /** 建（或重建）WebView 并加载 url。渲染进程崩溃后也走这里。 */
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
        s.setUserAgentString(s.getUserAgentString() + " ocsTV/1.1");
        s.setTextZoom(130);          // 电视上小字看不清，整体放大
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
                return openExternalIfNeeded(url);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (Build.VERSION.SDK_INT >= 23 && request != null && request.isForMainFrame()) {
                    showErrorPage(String.valueOf(error.getDescription()));
                }
            }

            /**
             * WebView 渲染进程崩溃（电视上很常见：内存小 / 解码不支持）。
             * 不接管的话系统会把宿主 App 一起杀掉 —— 这就是「点标题闪退」的根因。
             */
            @Override
            public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
                boolean crashed = Build.VERSION.SDK_INT >= 26 && detail != null && detail.didCrash();
                onRendererGone(crashed);
                return true;   // 已处理，别杀进程
            }
        });

        w.setWebChromeClient(new WebChromeClient());
    }

    /** 渲染进程没了：提示 + 重建 WebView，并退回文件列表（别再回那个把渲染搞崩的页面） */
    private void onRendererGone(final boolean crashed) {
        final long now = System.currentTimeMillis();
        final boolean repeat = (now - lastCrashAt) < 20000;
        lastCrashAt = now;
        ui.post(() -> {
            String home = baseUrl();
            String target = repeat ? home : (lastUrl != null && lastUrl.contains("/video") ? home : (lastUrl == null ? home : lastUrl));
            toast(crashed
                    ? "视频页/页面渲染崩了（电视内存或解码限制），已自动回到文件列表"
                    : "页面渲染进程被系统回收，已重新加载");
            installWebView(target);
        });
    }

    private void showErrorPage(String desc) {
        String html = "<html><head><meta charset='utf-8'><style>"
                + "body{background:#111;color:#ddd;font:20px/1.6 sans-serif;padding:60px}"
                + "h1{color:#4ea1ff;font-size:26px}code{color:#ffb86b}</style></head><body>"
                + "<h1>打不开这个页面</h1><p>" + (desc == null ? "" : desc) + "</p>"
                + "<p>遥控器「菜单」键可切换服务器，返回键回上一页。</p></body></html>";
        try {
            web.loadDataWithBaseURL(baseUrl(), html, "text/html", "utf-8", null);
        } catch (Exception ignored) {
        }
    }

    private boolean openExternalIfNeeded(String url) {
        if (url == null) return false;
        if (url.startsWith("http://") || url.startsWith("https://")) return false;
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (Exception ignored) {
        }
        return true;
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
                showServerDialog();
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

    // ---------------------------------------------------------------- server

    private String baseUrl() {
        SharedPreferences sp = getSharedPreferences(PREFS, MODE_PRIVATE);
        return sp.getString(KEY_URL, DEFAULT_URL);
    }

    private void saveBaseUrl(String url) {
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_URL, url).apply();
        if (web != null) {
            web.loadUrl(url);
        } else {
            installWebView(url);
        }
    }

    /** 遥控器「菜单」键打开：切换服务器（电视上没法输网址，这里是唯一入口） */
    private void showServerDialog() {
        ListAdapter adapter = new BaseAdapter() {
            @Override
            public int getCount() {
                return SERVERS.length;
            }

            @Override
            public Object getItem(int i) {
                return SERVERS[i];
            }

            @Override
            public long getItemId(int i) {
                return i;
            }

            @Override
            public View getView(int i, View convertView, ViewGroup parent) {
                TextView tv = new TextView(TvActivity.this);
                tv.setText(SERVERS[i]);
                tv.setTextSize(20);
                tv.setTextColor(SERVERS[i].equals(baseUrl()) ? 0xFF2F7CF6 : 0xFF222222);
                tv.setPadding(dp(28), dp(20), dp(28), dp(20));
                TypedValue out = new TypedValue();
                getTheme().resolveAttribute(android.R.attr.selectableItemBackground, out, true);
                tv.setBackgroundResource(out.resourceId);
                return tv;
            }
        };
        new AlertDialog.Builder(this)
                .setTitle("切换服务器（当前：" + baseUrl() + "）")
                .setAdapter(adapter, (d, which) -> saveBaseUrl(SERVERS[which]))
                .setNeutralButton("手动输入…", (d, w) -> showManualInput())
                .setNegativeButton("取消", null)
                .show();
    }

    private void showManualInput() {
        EditText et = new EditText(this);
        et.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        et.setText(baseUrl());
        new AlertDialog.Builder(this)
                .setTitle("服务器地址")
                .setView(et)
                .setPositiveButton("保存", (d, w) -> {
                    String v = et.getText().toString().trim();
                    if (!v.isEmpty()) {
                        if (!v.startsWith("http://") && !v.startsWith("https://")) v = "http://" + v;
                        saveBaseUrl(v);
                    }
                })
                .setNegativeButton("取消", null)
                .show();
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            root.removeView(web);
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
