package com.harness.ocs.tv;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;

import java.io.File;

/**
 * 把自己下载的 APK 暴露成一个 content:// URI，交给系统安装器读。
 *
 * Android 7 起不允许 file:// 直接跨进程传给安装器（FileUriExposedException），
 * 标准做法是 FileProvider；这台机器没有 androidx 依赖，所以这里手写一个最小版本：
 * 只服务本 App 目录下的 update.apk，别的路径一律拒绝。
 */
public class ApkProvider extends ContentProvider {

    static final String AUTHORITY = "com.harness.ocs.tv.apk";
    private static final String NAME = "update.apk";

    static Uri uri() {
        return Uri.parse("content://" + AUTHORITY + "/" + NAME);
    }

    /** 安装器要读的那个文件（App 私有目录，不需要任何存储权限）。 */
    static File file(android.content.Context ctx) {
        return new File(ctx.getExternalFilesDir(null), NAME);
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public String getType(Uri uri) {
        return "application/vnd.android.package-archive";
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws java.io.FileNotFoundException {
        if (getContext() == null || !NAME.equals(uri.getLastPathSegment())) {
            throw new java.io.FileNotFoundException("unsupported uri: " + uri);
        }
        return ParcelFileDescriptor.open(file(getContext()), ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection, String[] args, String sort) {
        File f = file(getContext());
        String[] cols = {OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE};
        MatrixCursor c = new MatrixCursor(cols);
        c.addRow(new Object[]{"ocs-tv.apk", f.length()});
        return c;
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        return null;
    }

    @Override
    public int delete(Uri uri, String selection, String[] args) {
        return 0;
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] args) {
        return 0;
    }
}
