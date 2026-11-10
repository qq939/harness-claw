/* 面板「端口」弹窗：显示已映射端口（8082:19xxx 格式），支持新增与删除。 */
(function () {
  'use strict';

  var RE = /^\d{1,5}:\d{1,5}$/;

  function api(url, opts) {
    return fetch(url, opts).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok || (d && d.error)) throw new Error((d && d.error) || ('HTTP ' + r.status));
        return d;
      });
    });
  }

  function css(el, obj) { for (var k in obj) el.style[k] = obj[k]; return el; }

  function el(tag, text, style) {
    var n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (style) css(n, style);
    return n;
  }

  function build(container, state, onSaved) {
    var extras = (state.extra || []).slice();
    var primary = state.primary || null;

    var overlay = el('div', '', {
      position: 'fixed', inset: '0', background: 'rgba(0,0,0,.62)', zIndex: '99999',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    });
    var box = el('div', '', {
      width: 'min(560px, 92vw)', background: '#14181f', color: '#e6e6e6',
      border: '1px solid #2a3040', borderRadius: '12px', padding: '18px 20px',
      boxShadow: '0 18px 48px rgba(0,0,0,.55)', font: '13px/1.5 system-ui, sans-serif',
    });

    box.appendChild(el('div', '端口映射 · ' + container, { fontSize: '15px', fontWeight: '600', marginBottom: '4px' }));
    box.appendChild(el('div', '格式：容器端口:宿主机端口，例如 8082:19109。改完会重建容器（服务短暂中断）。',
      { color: '#8b93a3', fontSize: '12px', marginBottom: '12px' }));

    var list = el('div', '', { display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '12px' });
    box.appendChild(list);

    function row(mapping, deletable, note) {
      var r = el('div', '', {
        display: 'flex', alignItems: 'center', gap: '8px',
        background: '#10141b', border: '1px solid #232a37', borderRadius: '8px', padding: '7px 10px',
      });
      r.appendChild(el('code', mapping, { color: '#5eead4', fontFamily: 'ui-monospace, Consolas, monospace' }));
      if (note) r.appendChild(el('span', note, { color: '#7d8494', fontSize: '11px' }));
      var spacer = el('div', '', { flex: '1' });
      r.appendChild(spacer);
      if (deletable) {
        var del = el('button', '删除', {
          background: '#2a1518', color: '#ff8f8f', border: '1px solid #4a2026',
          borderRadius: '6px', padding: '3px 10px', cursor: 'pointer', fontSize: '12px',
        });
        del.onclick = function () {
          extras = extras.filter(function (x) { return x !== mapping; });
          render();
        };
        r.appendChild(del);
      } else {
        r.appendChild(el('span', '主端口 · 不可删除', { color: '#5b6472', fontSize: '11px' }));
      }
      return r;
    }

    function render() {
      list.textContent = '';
      if (primary && primary.mapping) list.appendChild(row(primary.mapping, false, '页面/默认服务'));
      if (!extras.length) {
        list.appendChild(el('div', '（暂无附加端口）', { color: '#5b6472', fontSize: '12px', padding: '2px 2px' }));
      } else {
        extras.forEach(function (m) { list.appendChild(row(m, true)); });
      }
    }
    render();

    var addRow = el('div', '', { display: 'flex', gap: '8px', marginBottom: '14px' });
    var input = el('input', '', {
      flex: '1', background: '#0d1117', border: '1px solid #232a37', borderRadius: '8px',
      color: '#e6e6e6', padding: '7px 10px', font: '12px ui-monospace, Consolas, monospace', outline: 'none',
    });
    input.placeholder = '8080:19112';
    var addBtn = el('button', '添加', {
      background: '#16233a', color: '#8fc2ff', border: '1px solid #2b3d5c',
      borderRadius: '8px', padding: '7px 14px', cursor: 'pointer',
    });
    var hint = el('div', '', { color: '#ff8f8f', fontSize: '12px', minHeight: '16px', marginBottom: '6px' });

    addBtn.onclick = function () {
      var v = input.value.trim().replace(/\s+/g, '');
      if (!RE.test(v)) { hint.textContent = '格式不对，应为 容器端口:宿主机端口'; return; }
      var parts = v.split(':');
      if (parts[0] === String(state.service_port) && primary) { hint.textContent = '主端口 ' + state.service_port + ' 已存在，不能重复添加'; return; }
      if (extras.indexOf(v) >= 0) { hint.textContent = '该映射已存在'; return; }
      if (state.bindings && state.bindings.indexOf(v) >= 0) { hint.textContent = '该映射已在容器上，无需重复'; return; }
      extras.push(v);
      input.value = '';
      hint.textContent = '';
      render();
    };
    input.onkeydown = function (e) { if (e.key === 'Enter') { e.preventDefault(); addBtn.onclick(); } };
    addRow.appendChild(input);
    addRow.appendChild(addBtn);
    box.appendChild(addRow);
    box.appendChild(hint);

    var foot = el('div', '', { display: 'flex', justifyContent: 'flex-end', gap: '8px' });
    var cancel = el('button', '取消', {
      background: '#1b2230', color: '#c9d1de', border: '1px solid #2a3343',
      borderRadius: '8px', padding: '7px 16px', cursor: 'pointer',
    });
    var save = el('button', '保存并重建', {
      background: '#2f6feb', color: '#fff', border: '1px solid #2f6feb',
      borderRadius: '8px', padding: '7px 16px', cursor: 'pointer', fontWeight: '600',
    });
    cancel.onclick = function () { document.body.removeChild(overlay); };
    save.onclick = function () {
      save.disabled = true;
      save.textContent = '保存中…';
      api('/api/agents/' + encodeURIComponent(container) + '/ports', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ports: extras }),
      }).then(function (d) {
        document.body.removeChild(overlay);
        if (onSaved) onSaved(d);
        var tip = el('div', '端口已更新：' + ((d.mappings || []).join('  ') || '（无附加端口）') + '，容器重建中…', {
          position: 'fixed', right: '18px', bottom: '18px', background: '#16233a', color: '#cfe7ff',
          border: '1px solid #2b3d5c', borderRadius: '8px', padding: '10px 14px', zIndex: '100000',
          font: '13px system-ui, sans-serif',
        });
        document.body.appendChild(tip);
        setTimeout(function () { location.reload(); }, 1500);
      }).catch(function (e) {
        save.disabled = false;
        save.textContent = '保存并重建';
        hint.textContent = '保存失败：' + e.message;
      });
    };
    foot.appendChild(cancel);
    foot.appendChild(save);
    box.appendChild(foot);

    overlay.appendChild(box);
    overlay.onclick = function (e) { if (e.target === overlay) document.body.removeChild(overlay); };
    document.body.appendChild(overlay);
    setTimeout(function () { input.focus(); }, 30);
  }

  window.openPortModal = function (container, onSaved) {
    api('/api/agents/' + encodeURIComponent(container) + '/ports')
      .then(function (state) { build(container, state, onSaved); })
      .catch(function (e) { alert('读取端口配置失败：' + e.message); });
  };
})();
