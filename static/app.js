'use strict';
const $ = s => document.querySelector(s);
const bar = $('#bar'), listEl = $('#list');
const LB = {queued:'排队', running:'识别中', done:'完成', failed:'失败'};
const esc = s => String(s==null?'':s).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let timer = null;
console.log('[boot] part1');
async function api(p, o) {
  const r = await fetch(p, o || {});
  if (r.status === 401) { $('#login').classList.remove('hide'); throw new Error('401'); }
  return r;
}
async function login() {
  const r = await fetch('/api/login', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({password: $('#pw').value})
  });
  if (r.ok) { $('#login').classList.add('hide'); $('#le').textContent=''; refresh(); }
  else $('#le').textContent = '密码错误 HTTP ' + r.status;
}
async function shrink(f) {
  try {
    const b = await createImageBitmap(f);
    const s = Math.min(1, 1800 / Math.max(b.width, b.height));
    const c = document.createElement('canvas');
    c.width = Math.round(b.width * s);
    c.height = Math.round(b.height * s);
    c.getContext('2d').drawImage(b, 0, 0, c.width, c.height);
    return await new Promise(r => c.toBlob(r, 'image/jpeg', 0.9));
  } catch (e) { return f; }
}
async function up(files) {
  const a = Array.from(files);
  for (let i = 0; i < a.length; i++) {
    bar.textContent = '上传中 ' + (i+1) + '/' + a.length;
    const fd = new FormData();
    fd.append('file', await shrink(a[i]), 'p.jpg');
    try {
      const r = await api('/api/uploads', {method:'POST', body:fd});
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || '上传失败');
    } catch (e) { bar.textContent = '失败: ' + e.message; return; }
  }
  bar.textContent = '已提交，等待识别…';
  refresh();
}
console.log('[boot] part2');
function card(x) {
  const w = new Date(x.created_at * 1000).toLocaleString('zh-CN', {hour12:false});
  let h = '<div class="c"><img src="/api/tasks/' + x.id + '/thumb" alt="">';
  h += '<div class="s">' + (LB[x.status]||x.status) + ' · ' + w + '</div>';
  if (x.error) h += '<div class="s" style="color:#f85149">' + esc(x.error) + '</div>';
  if (x.status === 'done') {
    h += '<textarea id="t' + x.id + '">' + esc(x.latex) + '</textarea>';
    h += '<div class="ops">';
    h += '<button data-a="copy" data-i="' + x.id + '">复制</button>';
    h += '<button data-a="save" data-i="' + x.id + '">保存</button>';
    h += '<button data-a="del"  data-i="' + x.id + '">删除</button>';
    h += '</div>';
  }
  return h + '</div>';
}
async function refresh() {
  try {
    const r = await api('/api/tasks');
    if (r.status === 401) return;
    const a = await r.json();
    listEl.innerHTML = a.length ? a.map(card).join('')
      : '<div class="s">还没有记录，拍照开始吧</div>';
    const busy = a.some(x => x.status==='queued' || x.status==='running');
    clearTimeout(timer);
    if (busy) timer = setTimeout(refresh, 2500);
    else if (a.length) bar.textContent = '共 ' + a.length + ' 条';
  } catch (e) {}
}
console.log('[boot] part3');
listEl.onclick = async e => {
  const b = e.target.closest('button[data-a]');
  if (!b) return;
  const id = b.dataset.i, ta = document.getElementById('t' + id);
  if (b.dataset.a === 'copy') {
    try { await navigator.clipboard.writeText(ta.value); bar.textContent='已复制'; }
    catch (err) { ta.select(); document.execCommand('copy'); bar.textContent='已复制'; }
  } else if (b.dataset.a === 'save') {
    const r = await api('/api/tasks/' + id, {
      method:'PATCH', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({latex: ta.value})
    });
    bar.textContent = r.ok ? '已保存' : '保存失败';
  } else if (b.dataset.a === 'del') {
    if (!confirm('删除？')) return;
    await api('/api/tasks/' + id, {method:'DELETE'});
    refresh();
  }
};
$('#btnLogin').onclick = login;
$('#pw').onkeydown = e => { if (e.key === 'Enter') login(); };
$('#cam').onchange = e => { up(e.target.files); e.target.value=''; };
$('#gal').onchange = e => { up(e.target.files); e.target.value=''; };
console.log('[boot] part4 ready');
refresh();