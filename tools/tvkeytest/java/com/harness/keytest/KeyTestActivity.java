package com.harness.keytest;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/**
 * 遥控器按键探针：把收到的每一个 KeyEvent 打在屏幕上，用来搞清楚
 * 极米遥控器的「语音键」到底发的是哪个 keyCode（第三方 App 才能抢它）。
 *
 * 用法：装到电视上打开 → 依次按 方向键 / OK / 返回 / 语音键，屏幕上会累积显示
 *       keyCode=xxx KEYCODE_XXX scanCode=… repeat=… down/up
 */
public class KeyTestActivity extends Activity {

    private TextView log;
    private TextView hint;
    private int count;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.BLACK);
        root.setPadding(48, 36, 48, 36);

        hint = new TextView(this);
        hint.setText("按键探针：按一下遥控器上的键，下面会显示 keyCode\n先按 方向键/OK/返回，最后按「语音键」，把结果告诉我");
        hint.setTextColor(Color.parseColor("#7fd1ff"));
        hint.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        root.addView(hint);

        log = new TextView(this);
        log.setTextColor(Color.WHITE);
        log.setTextSize(TypedValue.COMPLEX_UNIT_SP, 24);
        log.setGravity(Gravity.TOP);
        ScrollView sv = new ScrollView(this);
        sv.addView(log);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f);
        lp.topMargin = 24;
        root.addView(sv, lp);

        setContentView(root);
    }

    private void append(String line) {
        count++;
        CharSequence old = log.getText();
        String text = (old == null || old.length() == 0) ? line : (old + "\n" + line);
        log.setText(text);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        append(String.format("#%d DOWN  keyCode=%d %s  scan=%d  repeat=%d",
                count + 1, keyCode, KeyEvent.keyCodeToString(keyCode),
                event.getScanCode(), event.getRepeatCount()));
        // 返回键不退出，方便继续观察
        return true;
    }

    @Override
    public boolean onKeyUp(int keyCode, KeyEvent event) {
        append(String.format("      UP    keyCode=%d %s", keyCode, KeyEvent.keyCodeToString(keyCode)));
        return true;
    }

    @Override
    public boolean onGenericMotionEvent(MotionEvent event) {
        append("MOTION action=" + event.getAction() + " source=" + event.getSource());
        return super.onGenericMotionEvent(event);
    }
}
