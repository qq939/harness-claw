// ocs TV 遥控器映射：由 TvActivity 在所有页面加载完后注入
//   /video 页：上下左右直接派发 Arrow* 事件（页面自己处理切视频/翻页），OK 派发空格（播放/暂停）
//   其它页：做空间焦点导航（方向键移动高亮框，OK 点击）
(function () {
    if (window.__ocsTV) { return 'ok'; }
    window.__ocsTV = 1;

    var st = document.createElement('style');
    st.textContent = '.__tv_focus{outline:5px solid #2f7cf6 !important;outline-offset:3px;border-radius:8px;background:rgba(47,124,246,.10) !important}';
    document.head.appendChild(st);

    var items = [], idx = -1;
    var SEL = 'a[href],button,input,select,textarea,[role=button],.video-item';

    function vis(el) {
        var r = el.getBoundingClientRect();
        return r.width > 2 && r.height > 2 && r.bottom > -40 && r.top < window.innerHeight + 40;
    }
    function collect() {
        items = Array.prototype.slice.call(document.querySelectorAll(SEL)).filter(vis);
    }
    function focusAt(i) {
        if (idx >= 0 && items[idx]) { items[idx].classList.remove('__tv_focus'); }
        idx = i;
        var el = items[idx];
        if (!el) { return; }
        el.classList.add('__tv_focus');
        try { el.scrollIntoView({ block: 'center' }); } catch (e) { }
    }
    function move(dir) {
        collect();
        if (!items.length) { return; }
        if (idx < 0 || idx >= items.length) { focusAt(0); return; }
        var c = items[idx].getBoundingClientRect();
        var cx = c.left + c.width / 2, cy = c.top + c.height / 2;
        var best = -1, bestScore = 1e18;
        for (var i = 0; i < items.length; i++) {
            if (i === idx) { continue; }
            var r = items[i].getBoundingClientRect();
            var x = r.left + r.width / 2, y = r.top + r.height / 2;
            var dx = x - cx, dy = y - cy, ok = false;
            if (dir === 'up') { ok = dy < -4; }
            else if (dir === 'down') { ok = dy > 4; }
            else if (dir === 'left') { ok = dx < -4; }
            else { ok = dx > 4; }
            if (!ok) { continue; }
            // 左右移动时要求大致在同一水平带内（文件列表是纵向的，避免按右键跳到上面的排序栏）
            if (dir === 'left' || dir === 'right') {
                var band = (c.height + r.height) / 2 + 60;
                if (Math.abs(dy) > band) { continue; }
            }
            var p = (dir === 'up' || dir === 'down') ? Math.abs(dy) : Math.abs(dx);
            var s = (dir === 'up' || dir === 'down') ? Math.abs(dx) : Math.abs(dy);
            var score = p + s * 2.5;
            if (score < bestScore) { bestScore = score; best = i; }
        }
        if (best >= 0) { focusAt(best); }
    }
    function activate() {
        collect();
        if (idx < 0 || idx >= items.length) { focusAt(0); return; }
        var el = items[idx];
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') { el.focus(); return; }
        el.click();
    }

    window.__ocsDpad = function (dir) {
        var p = location.pathname;
        if (p.indexOf('/video') === 0) {
            var key = dir === 'up' ? 'ArrowUp' : dir === 'down' ? 'ArrowDown'
                : dir === 'left' ? 'ArrowLeft' : dir === 'right' ? 'ArrowRight' : ' ';
            document.dispatchEvent(new KeyboardEvent('keydown', { key: key, bubbles: true }));
            return;
        }
        if (dir === 'ok') { activate(); return; }
        move(dir);
    };
    return 'ok';
})();
