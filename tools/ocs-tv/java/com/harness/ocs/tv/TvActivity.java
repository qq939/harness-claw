package com.harness.ocs.tv;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.util.TypedValue;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.BaseAdapter;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ListAdapter;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;

/**
 * ocs TV —— 给电视/盒子用的壳：
 *   - 全屏无地址栏，遥控器操作（方向键移动焦点/翻视频，OK 确认，返回退出）
 *   - 页面本身用 WebView 渲染；注入一段 JS，把遥控器按键翻译成页面能懂的操作
 *   - 没有触摸屏也能用（manifest 声明 touchscreen not required + leanback launcher）
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

    /** 遥控器 -> 页面：JS 从 shim.js 生成（构建脚本负责转义），见 ShimJs.java */
    private static final String SHIM_JS = ShimJs.JS;
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        hideSystemUi();

        root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);

        web = new WebView(this);
        web.setLayoutParams(new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        web.setFocusable(true);
        web.setFocusableInTouchMode(true);
        configureWebView(web);
        root.addView(web);
        setContentView(root);

        web.loadUrl(baseUrl());
        web.requestFocus();
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

    private void configureWebView(WebView w) {
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setBuiltInZoomControls(false);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setUserAgentString(s.getUserAgentString() + " ocsTV/1.0");
        // 电视上看不清小字，整体放大一点
        s.setTextZoom(130);

        w.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                view.evaluateJavascript(SHIM_JS, null);
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                if (url != null && (url.startsWith("http://") || url.startsWith("https://"))) {
                    return false;
                }
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                } catch (Exception ignored) {
                }
                return true;
            }
        });
        w.setWebChromeClient(new WebChromeClient());
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
                web.evaluateJavascript("document.dispatchEvent(new KeyboardEvent('keydown',{key:' ',bubbles:true}))", null);
                return true;
            case KeyEvent.KEYCODE_BACK:
                if (web.canGoBack()) {
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
            web.evaluateJavascript("window.__ocsDpad && window.__ocsDpad('" + dir + "')", null);
            return true;
        }
        return super.onKeyDown(keyCode, event);
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
        web.loadUrl(url);
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

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
