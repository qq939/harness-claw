package com.harness.ocs.tv;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.BaseAdapter;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLDecoder;
import java.util.ArrayList;
import java.util.List;

/**
 * 电视版视频列表：不再用 WebView 播视频（极米这类投影仪 WebView 解码弱，容易把渲染进程搞崩）。
 * 这里直接用 /videos 接口拉列表，OK 交给原生播放器。
 */
public class VideoListActivity extends Activity {

    private static final String PREFS = "ocs_tv";
    private static final String KEY_URL = "base_url";
    private static final String DEFAULT_URL = "http://oas.dimond.top";

    private final List<String[]> items = new ArrayList<>();   // [name, url, size]
    private BaseAdapter adapter;
    private ListView list;
    private TextView title;
    private TextView hint;
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackgroundColor(Color.parseColor("#0E1420"));

        title = new TextView(this);
        title.setText("视频");
        title.setTextSize(24);
        title.setTextColor(Color.WHITE);
        title.setPadding(dp(36), dp(22), dp(36), dp(8));
        box.addView(title);

        hint = new TextView(this);
        hint.setText("OK 播放 · 返回 回首页 · 菜单 换服务器");
        hint.setTextSize(14);
        hint.setTextColor(Color.parseColor("#8CA0BF"));
        hint.setPadding(dp(36), 0, dp(36), dp(10));
        box.addView(hint);

        list = new ListView(this);
        list.setDivider(null);
        list.setSelector(android.R.color.transparent);
        list.setLayoutParams(new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        box.addView(list);

        setContentView(box);
        list.requestFocus();

        adapter = new BaseAdapter() {
            @Override
            public int getCount() {
                return items.size();
            }

            @Override
            public Object getItem(int i) {
                return items.get(i);
            }

            @Override
            public long getItemId(int i) {
                return i;
            }

            @Override
            public View getView(int i, View reuse, ViewGroup parent) {
                TextView tv = new TextView(VideoListActivity.this);
                tv.setText(items.get(i)[0]);
                tv.setTextSize(20);
                tv.setTextColor(Color.parseColor("#E8EEF7"));
                tv.setPadding(dp(36), dp(18), dp(36), dp(18));
                tv.setBackgroundColor(Color.parseColor("#141C2B"));
                tv.setGravity(Gravity.CENTER_VERTICAL);
                tv.setFocusable(true);
                return tv;
            }
        };
        list.setAdapter(adapter);

        list.setOnItemClickListener((AdapterView<?> parent, View view, int pos, long id) -> play(items.get(pos)));
        list.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int pos, long id) {
                if (view != null) {
                    view.setBackgroundColor(Color.parseColor("#1E3A5F"));
                    view.setScaleX(1.02f);
                    view.setScaleY(1.02f);
                }
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
            }
        });

        load();
    }

    /** GET 一个地址，手动跟随 301/302/303/307/308（http→https 的跳转某些设备不会自动跟） */
    private String httpGet(String url) throws Exception {
        String cur = url;
        for (int hop = 0; hop < 5; hop++) {
            HttpURLConnection c = (HttpURLConnection) new URL(cur).openConnection();
            c.setInstanceFollowRedirects(false);
            c.setConnectTimeout(10000);
            c.setReadTimeout(20000);
            c.setRequestProperty("Accept", "application/json");
            int code = c.getResponseCode();
            if (code == 301 || code == 302 || code == 303 || code == 307 || code == 308) {
                String loc = c.getHeaderField("Location");
                c.disconnect();
                if (loc == null) throw new RuntimeException("HTTP " + code + "（无 Location）");
                cur = new URL(new URL(cur), loc).toString();
                continue;
            }
            if (code != 200) {
                c.disconnect();
                throw new RuntimeException("HTTP " + code);
            }
            StringBuilder sb = new StringBuilder();
            try (InputStream in = c.getInputStream();
                 BufferedReader r = new BufferedReader(new InputStreamReader(in, "UTF-8"))) {
                String line;
                while ((line = r.readLine()) != null) sb.append(line);
            }
            c.disconnect();
            return sb.toString();
        }
        throw new RuntimeException("重定向次数过多");
    }

    private void load() {
        final String base = baseUrl();
        title.setText("视频 · 加载中…");
        new Thread(() -> {
            String err = null;
            final List<String[]> got = new ArrayList<>();
            try {
                JSONObject root = new JSONObject(httpGet(base.replaceAll("/+$", "") + "/videos"));
                JSONArray arr = root.optJSONArray("videos");
                if (arr != null) {
                    for (int i = 0; i < arr.length(); i++) {
                        JSONObject v = arr.getJSONObject(i);
                        String name = v.optString("name");
                        String url = v.optString("url");
                        if (name.isEmpty()) continue;
                        if (url.isEmpty()) url = "/obs/" + name;
                        long size = v.optLong("size", 0);
                        got.add(new String[]{name, url, String.valueOf(size)});
                    }
                }
            } catch (Exception e) {
                err = e.getMessage();
            }
            final String ferr = err;
            ui.post(() -> {
                items.clear();
                items.addAll(got);
                if (adapter != null) adapter.notifyDataSetChanged();
                // 标题里带上文件个数与大小，方便确认是不是同一台服务器
                if (ferr != null) {
                    title.setText("视频 · 读取失败");
                    hint.setText("错误：" + ferr + "（菜单键换服务器，返回键回首页）");
                } else {
                    title.setText("视频 · " + items.size() + " 个");
                    hint.setText("OK 播放 · 返回 回首页 · 菜单 换服务器");
                }
                if (!items.isEmpty()) list.requestFocus();
            });
        }).start();
    }

    private void play(String[] item) {
        String name = item[0];
        String url = item[1];
        if (!url.startsWith("http")) {
            url = baseUrl() + (url.startsWith("/") ? "" : "/") + url;
        }
        url = url.replace(" ", "%20");
        Intent it = new Intent(this, PlayerActivity.class);
        it.putExtra("url", url);
        it.putExtra("name", name);
        startActivity(it);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_MENU || keyCode == KeyEvent.KEYCODE_INFO) {
            startActivity(new Intent(this, ServerDialogActivity.class));
            return true;
        }
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            finish();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    private String baseUrl() {
        SharedPreferences sp = getSharedPreferences(PREFS, MODE_PRIVATE);
        return sp.getString(KEY_URL, DEFAULT_URL);
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
