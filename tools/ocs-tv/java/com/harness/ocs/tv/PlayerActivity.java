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

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);

        String url = getIntent().getStringExtra("url");
        name = getIntent().getStringExtra("name");
        if (url == null) {
            finish();
            return;
        }

        vv = new VideoView(this);
        setContentView(vv);

        MediaController mc = new MediaController(this);
        mc.setAnchorView(vv);
        vv.setMediaController(mc);

        vv.setOnPreparedListener((MediaPlayer mp) -> {
            mp.setLooping(false);
            vv.start();
            toast("正在播放：" + (name == null ? "" : name));
        });
        vv.setOnErrorListener((mp, what, extra) -> {
            toast("这台设备播不了这个格式（" + what + "/" + extra + "），换一个试试");
            finish();
            return true;
        });
        vv.setOnCompletionListener(mp -> toast("播放结束"));
        vv.setVideoURI(Uri.parse(url));
        vv.requestFocus();
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
        if (vv != null) {
            try {
                vv.stopPlayback();
            } catch (Exception ignored) {
            }
        }
        super.onDestroy();
    }
}
