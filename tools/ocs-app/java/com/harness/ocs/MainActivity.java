package com.harness.ocs;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.ContentResolver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import java.io.BufferedInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.List;

/**
 * ocs —— 一个只有 OCS 页面的壳：
 *   - 没有地址栏，启动即打开 OCS 页面（WebView，Chrome 内核）
 *   - 接收别的 App「分享」过来的文件（单个/多个），批量 PUT 到 OCS
 *   - 左上角很小的齿轮用来改服务器地址（长按/点一下）
 */
public class MainActivity extends Activity {

    private static final String PREFS = "ocs";
    private static final String KEY_URL = "base_url";
    private static final String DEFAULT_URL = "https://ocs.dimond.top";
    private static final String UPLOAD_TOKEN = "agent";

    private static final String[] PRESET_LABELS = {
            "ocs.dimond.top（公网）",
            "NAS1 192.168.0.201（局域网）",
            "NAS2 8.130.124.108:5080（公网）",
    };
    private static final String[] PRESET_URLS = {
            "https://ocs.dimond.top",
            "http://192.168.0.201",
            "http://8.130.124.108:5080",
    };

    private static final int REQ_FILE = 1001;

    private WebView web;
    private FrameLayout root;
    private LinearLayout overlay;
    private TextView overlayText;
    private ProgressBar overlayBar;
    private ValueCallback<Uri[]> filePathCallback;

    private final Handler ui = new Handler(Looper.getMainLooper());

    // ---------------------------------------------------------------- lifecycle

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        root = new FrameLayout(this);
        root.setBackgroundColor(Color.WHITE);

        web = new WebView(this);
        web.setLayoutParams(new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        configureWebView(web);
        root.addView(web);

        // 左上角的小齿轮：改服务器地址（透明一点，不挡页面）
        TextView gear = new TextView(this);
        gear.setText("⚙");
        gear.setTextSize(16);
        gear.setGravity(Gravity.CENTER);
        gear.setAlpha(0.35f);
        FrameLayout.LayoutParams gp = new FrameLayout.LayoutParams(dp(34), dp(34));
        gp.gravity = Gravity.TOP | Gravity.START;
        gp.leftMargin = dp(4);
        gp.topMargin = dp(4);
        gear.setLayoutParams(gp);
        gear.setOnClickListener(v -> showServerDialog());
        root.addView(gear);

        overlay = buildOverlay();
        root.addView(overlay);

        setContentView(root);
        web.loadUrl(baseUrl());

        handleIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIntent(intent);
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }

    // ---------------------------------------------------------------- webview

    private void configureWebView(WebView w) {
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setBuiltInZoomControls(false);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setUserAgentString(s.getUserAgentString() + " ocsApp/1.0");

        w.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return openExternalIfNeeded(url);
            }
        });

        w.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> cb,
                                             FileChooserParams params) {
                if (filePathCallback != null) {
                    filePathCallback.onReceiveValue(null);
                }
                filePathCallback = cb;
                try {
                    Intent i = new Intent(Intent.ACTION_GET_CONTENT);
                    i.addCategory(Intent.CATEGORY_OPENABLE);
                    i.setType("*/*");
                    i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                    startActivityForResult(Intent.createChooser(i, "选择文件"), REQ_FILE);
                    return true;
                } catch (Exception e) {
                    filePathCallback = null;
                    return false;
                }
            }
        });

        w.setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) -> {
            try {
                DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
                req.setNotificationVisibility(
                        DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                req.addRequestHeader("User-Agent", userAgent);
                String name = android.webkit.URLUtil.guessFileName(url, contentDisposition, mimeType);
                req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
                DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
                if (dm != null) {
                    dm.enqueue(req);
                    toast("开始下载：" + name);
                    return;
                }
            } catch (Exception ignored) {
            }
            openExternalIfNeeded(url);
        });
    }

    /** 非 http(s) 交给系统（tel/mailto/intent 等），http(s) 留在 WebView 里 */
    private boolean openExternalIfNeeded(String url) {
        if (url == null) return false;
        if (url.startsWith("http://") || url.startsWith("https://")) {
            if (url.contains("target=_blank")) return false;
            return false;
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (Exception ignored) {
        }
        return true;
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == REQ_FILE && filePathCallback != null) {
            Uri[] result = null;
            if (resultCode == RESULT_OK && data != null) {
                if (data.getClipData() != null) {
                    int n = data.getClipData().getItemCount();
                    result = new Uri[n];
                    for (int i = 0; i < n; i++) {
                        result[i] = data.getClipData().getItemAt(i).getUri();
                    }
                } else if (data.getData() != null) {
                    result = new Uri[]{data.getData()};
                }
            }
            filePathCallback.onReceiveValue(result);
            filePathCallback = null;
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    // ---------------------------------------------------------------- share -> upload

    private void handleIntent(Intent it) {
        List<Uri> uris = urisFromIntent(it);
        if (uris.isEmpty()) return;
        uploadAll(uris);
    }

    private List<Uri> urisFromIntent(Intent it) {
        ArrayList<Uri> out = new ArrayList<>();
        if (it == null) return out;
        String action = it.getAction();
        if (Intent.ACTION_SEND.equals(action)) {
            Uri u = it.getParcelableExtra(Intent.EXTRA_STREAM);
            if (u != null) out.add(u);
        } else if (Intent.ACTION_SEND_MULTIPLE.equals(action)) {
            ArrayList<Uri> list = it.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
            if (list != null) out.addAll(list);
        }
        return out;
    }

    private void uploadAll(final List<Uri> uris) {
        final String base = baseUrl();
        showOverlay("准备上传 " + uris.size() + " 个文件…", 0);
        new Thread(() -> {
            int ok = 0;
            final ArrayList<String> failed = new ArrayList<>();
            for (int i = 0; i < uris.size(); i++) {
                final int idx = i + 1;
                final int total = uris.size();
                final String name = displayName(uris.get(i));
                ui.post(() -> showOverlay("上传 " + idx + "/" + total + "：" + name, 0));
                try {
                    putFile(uris.get(i), base, idx, total, name);
                    ok++;
                } catch (Exception e) {
                    failed.add(name + "（" + e.getMessage() + "）");
                }
            }
            final int okCount = ok;
            ui.post(() -> {
                hideOverlay();
                String msg = "上传完成：" + okCount + "/" + uris.size();
                if (!failed.isEmpty()) {
                    msg += "，失败：" + android.text.TextUtils.join("；", failed);
                }
                toast(msg);
                if (web != null) web.reload();
            });
        }).start();
    }

    private void putFile(Uri uri, String base, int idx, int total, String name) throws IOException {
        String endpoint = base.replaceAll("/+$", "") + "/" + Uri.encode(name)
                + "?token=" + UPLOAD_TOKEN;
        long size = sizeOf(uri);
        HttpURLConnection conn = (HttpURLConnection) new URL(endpoint).openConnection();
        conn.setRequestMethod("PUT");
        conn.setDoOutput(true);
        conn.setConnectTimeout(15000);
        conn.setReadTimeout(300000);
        conn.setRequestProperty("Content-Type", guessMime(name));
        if (size > 0) {
            conn.setFixedLengthStreamingMode(size);
        } else {
            conn.setChunkedStreamingMode(64 * 1024);
        }
        try (InputStream in = new BufferedInputStream(getContentResolver().openInputStream(uri));
             OutputStream out = conn.getOutputStream()) {
            byte[] buf = new byte[64 * 1024];
            long sent = 0;
            long nextReport = 0;
            int lastPct = -1;
            int r;
            while ((r = in.read(buf)) > 0) {
                out.write(buf, 0, r);
                sent += r;
                final int pct = size > 0 ? (int) (sent * 100 / size) : -1;
                // 进度只在百分比变化（大小未知时每 1MB）刷新，避免大文件把消息队列刷爆
                boolean due = (pct >= 0) ? (pct != lastPct) : (sent >= nextReport);
                if (!due) continue;
                lastPct = pct;
                if (pct < 0) nextReport = sent + 1024 * 1024;
                final int shown = pct >= 0 ? pct : 0;
                final String label = "上传 " + idx + "/" + total + "：" + name
                        + (pct >= 0 ? "（" + pct + "%）" : "");
                ui.post(() -> showOverlay(label, shown));
            }
        }
        int code = conn.getResponseCode();
        if (code != 201 && code != 200) {
            String body = "";
            try (InputStream es = conn.getErrorStream()) {
                if (es != null) {
                    byte[] b = new byte[512];
                    int n = es.read(b);
                    if (n > 0) body = new String(b, 0, n, "UTF-8");
                }
            } catch (Exception ignored) {
            }
            conn.disconnect();
            throw new IOException("HTTP " + code + (body.isEmpty() ? "" : " " + body));
        }
        conn.disconnect();
    }

    private String displayName(Uri uri) {
        try (Cursor c = getContentResolver().query(uri, null, null, null, null)) {
            if (c != null && c.moveToFirst()) {
                int i = c.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (i >= 0) {
                    String n = c.getString(i);
                    if (n != null && !n.isEmpty()) return n;
                }
            }
        } catch (Exception ignored) {
        }
        String last = uri.getLastPathSegment();
        return (last != null && !last.isEmpty()) ? last : ("share-" + System.currentTimeMillis());
    }

    private long sizeOf(Uri uri) {
        try (Cursor c = getContentResolver().query(uri, null, null, null, null)) {
            if (c != null && c.moveToFirst()) {
                int i = c.getColumnIndex(OpenableColumns.SIZE);
                if (i >= 0 && !c.isNull(i)) return c.getLong(i);
            }
        } catch (Exception ignored) {
        }
        return -1;
    }

    private static String guessMime(String name) {
        String n = name.toLowerCase();
        if (n.endsWith(".mp4") || n.endsWith(".m4v")) return "video/mp4";
        if (n.endsWith(".mov")) return "video/quicktime";
        if (n.endsWith(".mkv")) return "video/x-matroska";
        if (n.endsWith(".jpg") || n.endsWith(".jpeg")) return "image/jpeg";
        if (n.endsWith(".png")) return "image/png";
        if (n.endsWith(".gif")) return "image/gif";
        if (n.endsWith(".pdf")) return "application/pdf";
        if (n.endsWith(".apk")) return "application/vnd.android.package-archive";
        if (n.endsWith(".zip")) return "application/zip";
        if (n.endsWith(".txt")) return "text/plain";
        return "application/octet-stream";
    }

    // ---------------------------------------------------------------- ui bits

    private LinearLayout buildOverlay() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackgroundColor(0xEE222222);
        int p = dp(16);
        box.setPadding(p, p, p, p);

        TextView title = new TextView(this);
        title.setText("ocs 上传");
        title.setTextColor(Color.WHITE);
        title.setTextSize(16);
        box.addView(title);

        overlayText = new TextView(this);
        overlayText.setTextColor(0xFFDDDDDD);
        overlayText.setTextSize(13);
        overlayText.setPadding(0, dp(8), 0, dp(8));
        box.addView(overlayText);

        overlayBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        overlayBar.setMax(100);
        box.addView(overlayBar);

        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.gravity = Gravity.BOTTOM;
        lp.setMargins(dp(12), 0, dp(12), dp(24));
        box.setLayoutParams(lp);
        box.setVisibility(View.GONE);
        return box;
    }

    private void showOverlay(String text, int pct) {
        overlayText.setText(text);
        overlayBar.setProgress(pct);
        overlay.setVisibility(View.VISIBLE);
    }

    private void hideOverlay() {
        overlay.setVisibility(View.GONE);
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    // ---------------------------------------------------------------- server url

    private String baseUrl() {
        SharedPreferences sp = getSharedPreferences(PREFS, MODE_PRIVATE);
        return sp.getString(KEY_URL, DEFAULT_URL);
    }

    private void saveBaseUrl(String url) {
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_URL, url).apply();
        if (web != null) web.loadUrl(url);
    }

    private void showServerDialog() {
        String[] items = new String[PRESET_LABELS.length + 1];
        System.arraycopy(PRESET_LABELS, 0, items, 0, PRESET_LABELS.length);
        items[PRESET_LABELS.length] = "手动输入…";
        new AlertDialog.Builder(this)
                .setTitle("OCS 服务器：" + baseUrl())
                .setItems(items, (d, which) -> {
                    if (which < PRESET_URLS.length) {
                        saveBaseUrl(PRESET_URLS[which]);
                    } else {
                        showManualInput();
                    }
                })
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
                        if (!v.startsWith("http://") && !v.startsWith("https://")) {
                            v = "http://" + v;
                        }
                        saveBaseUrl(v);
                    }
                })
                .setNegativeButton("取消", null)
                .show();
    }
}
