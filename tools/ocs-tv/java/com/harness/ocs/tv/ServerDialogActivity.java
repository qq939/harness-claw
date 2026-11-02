package com.harness.ocs.tv;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.EditText;
import android.widget.ListAdapter;
import android.widget.TextView;

/**
 * 只负责弹「切换服务器」对话框（电视上没法输网址，这是唯一入口）。
 * 选完写进 SharedPreferences 就关掉，调用方在 onResume 里发现地址变了会自己重载。
 */
public class ServerDialogActivity extends Activity {

    static final String PREFS = "ocs_tv";
    static final String KEY_URL = "base_url";
    static final String DEFAULT_URL = "http://oas.dimond.top";

    private static final String[] SERVERS = {
            "http://oas.dimond.top",
            "http://obs.dimond.top",
            "http://ocs.dimond.top",
            "http://192.168.0.201",
            "http://192.168.0.202",
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setFinishOnTouchOutside(true);
        showList();
    }

    private String baseUrl() {
        SharedPreferences sp = getSharedPreferences(PREFS, MODE_PRIVATE);
        return sp.getString(KEY_URL, DEFAULT_URL);
    }

    private void save(String url) {
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_URL, url).apply();
        finish();
    }

    private void showList() {
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
                TextView tv = new TextView(ServerDialogActivity.this);
                tv.setText(SERVERS[i]);
                tv.setTextSize(20);
                tv.setTextColor(SERVERS[i].equals(baseUrl()) ? 0xFF2F7CF6 : 0xFF222222);
                int p = Math.round(28 * getResources().getDisplayMetrics().density);
                int v = Math.round(20 * getResources().getDisplayMetrics().density);
                tv.setPadding(p, v, p, v);
                android.util.TypedValue out = new android.util.TypedValue();
                getTheme().resolveAttribute(android.R.attr.selectableItemBackground, out, true);
                tv.setBackgroundResource(out.resourceId);
                return tv;
            }
        };
        new AlertDialog.Builder(this)
                .setTitle("切换服务器（当前：" + baseUrl() + "）")
                .setAdapter(adapter, (d, which) -> save(SERVERS[which]))
                .setNeutralButton("手动输入…", (d, w) -> showManual())
                .setNegativeButton("取消", (d, w) -> finish())
                .setOnCancelListener(d -> finish())
                .show();
    }

    private void showManual() {
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
                        save(v);
                    } else {
                        finish();
                    }
                })
                .setNegativeButton("取消", (d, w) -> finish())
                .show();
    }
}
