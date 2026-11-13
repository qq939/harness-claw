package com.harness.ocs.tv;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * 电视上的自更新：把「TV版」链接指向的 APK 下到本地，再交给系统安装器。
 *
 * 之前 WebView 里点 TV版 是死链接——WebView 没有 DownloadListener，遇到 .apk 什么都不做。
 * 这里自己下载（后台线程），下载完用 ApkProvider 的 content:// 拉起安装器，
 * 顺带处理 Android 8+ 的「安装未知应用」授权（没授权时先把用户带到设置页）。
 */
final class UpdateInstaller {

    private static final String TAG = "ocs-tv";

    private UpdateInstaller() {
    }

    /** 链接是不是一个 APK 下载地址。 */
    static boolean looksLikeApk(String url) {
        if (url == null) {
            return false;
        }
        String lower = url.toLowerCase();
        int cut = lower.indexOf('?');
        if (cut >= 0) {
            lower = lower.substring(0, cut);
        }
        return lower.endsWith(".apk");
    }

    /** 下载并拉起安装器；全过程在后台线程，失败只在屏幕上提示一句。 */
    static void downloadAndInstall(final Activity activity, final String url) {
        final Context app = activity.getApplicationContext();
        Toast.makeText(app, "开始下载新版本…", Toast.LENGTH_SHORT).show();
        new Thread(new Runnable() {
            @Override
            public void run() {
                final File out = ApkProvider.file(app);
                String error = null;
                HttpURLConnection conn = null;
                try {
                    File parent = out.getParentFile();
                    if (parent != null && !parent.exists()) {
                        parent.mkdirs();
                    }
                    conn = (HttpURLConnection) new URL(url).openConnection();
                    conn.setConnectTimeout(10000);
                    conn.setReadTimeout(60000);
                    conn.setInstanceFollowRedirects(true);
                    conn.setRequestProperty("Cache-Control", "no-store");
                    int code = conn.getResponseCode();
                    if (code != 200) {
                        throw new java.io.IOException("HTTP " + code);
                    }
                    InputStream in = conn.getInputStream();
                    FileOutputStream fos = new FileOutputStream(out);
                    try {
                        byte[] buf = new byte[64 * 1024];
                        int n;
                        while ((n = in.read(buf)) > 0) {
                            fos.write(buf, 0, n);
                        }
                    } finally {
                        try { fos.close(); } catch (Exception ignored) { }
                        try { in.close(); } catch (Exception ignored) { }
                    }
                    if (out.length() < 10 * 1024) {
                        throw new java.io.IOException("下载不完整");
                    }
                } catch (Exception e) {
                    error = String.valueOf(e.getMessage());
                } finally {
                    if (conn != null) {
                        conn.disconnect();
                    }
                }

                final String err = error;
                activity.runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        if (err != null) {
                            Toast.makeText(app, "下载失败：" + err, Toast.LENGTH_LONG).show();
                            return;
                        }
                        launchInstaller(activity);
                    }
                });
            }
        }, "ocs-tv-update").start();
    }

    private static void launchInstaller(Activity activity) {
        Context ctx = activity.getApplicationContext();
        // Android 8+ 每个 App 要单独授权「安装未知应用」，没授权时安装器会直接拒绝
        if (Build.VERSION.SDK_INT >= 26 && !activity.getPackageManager().canRequestPackageInstalls()) {
            Toast.makeText(ctx, "请允许 ocs TV 安装应用，然后回来再点一次 TV版", Toast.LENGTH_LONG).show();
            try {
                Intent i = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:" + ctx.getPackageName()));
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                ctx.startActivity(i);
            } catch (Exception e) {
                Log.w(TAG, "打不开未知应用授权页: " + e);
            }
            return;
        }
        try {
            Intent i = new Intent(Intent.ACTION_VIEW);
            i.setDataAndType(ApkProvider.uri(), "application/vnd.android.package-archive");
            i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
            ctx.startActivity(i);
        } catch (Exception e) {
            Log.w(TAG, "拉起安装器失败: " + e);
            Toast.makeText(ctx, "拉不起安装器：" + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }
}
