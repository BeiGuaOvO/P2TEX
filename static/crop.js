/* crop.js — 拍照/选图后手动裁剪（触摸 + 鼠标）
   在 index.html 里于 app.js 之前引入 */
(function () {
  'use strict';
  var MAX_EDGE = 1800, MIN = 70;
  var root = null, cv = null, g = null, box = null, tip = null;
  var src = null, W = 0, H = 0;
  var L = 0, T = 0, R = 0, B = 0;
  var drag = null, resolver = null;

  var CSS =
'#cropUI{position:fixed;inset:0;z-index:60;background:#000;display:none;' +
'flex-direction:column;color:#e6e8ec;font:15px/1.4 system-ui,sans-serif}' +
'#cropUI.on{display:flex}' +
'#cropUI .bar{flex:0 0 auto;display:flex;gap:8px;align-items:center;' +
'padding:10px 12px;background:#111317;padding-top:calc(10px + env(safe-area-inset-top))}' +
'#cropUI .bar:last-child{padding-top:10px;' +
'padding-bottom:calc(10px + env(safe-area-inset-bottom))}' +
'#cropUI .t{flex:1;font-size:13px;color:#8b93a1;min-width:0;overflow:hidden;' +
'white-space:nowrap;text-overflow:ellipsis}' +
'#cropUI button{font:inherit;padding:8px 14px;border-radius:8px;border:1px solid #2a2f38;' +
'background:#191c22;color:#e6e8ec;cursor:pointer;white-space:nowrap}' +
'#cropUI button.primary{background:#4c8dff;border-color:#4c8dff;color:#fff;font-weight:600}' +
'#cropUI .wrap{flex:1;display:flex;align-items:center;justify-content:center;' +
'padding:10px;overflow:hidden}' +
'#cropUI .stage{position:relative;touch-action:none}' +
'#cropUI canvas{display:block}' +
'#cropUI .box{position:absolute;border:1px solid #fff;' +
'box-shadow:0 0 0 9999px rgba(0,0,0,.55)}' +
'#cropUI .h{position:absolute;width:36px;height:36px;margin:-18px 0 0 -18px}' +
'#cropUI .h::after{content:"";position:absolute;left:50%;top:50%;width:14px;height:14px;' +
'margin:-7px 0 0 -7px;background:#fff;border-radius:3px;opacity:.92}' +
'#cropUI .h.nw{left:0;top:0}#cropUI .h.ne{left:100%;top:0}' +
'#cropUI .h.sw{left:0;top:100%}#cropUI .h.se{left:100%;top:100%}';
  function ensure() {
    if (root) return;
    var st = document.createElement('style');
    st.textContent = CSS;
    document.head.appendChild(st);

    root = document.createElement('div');
    root.id = 'cropUI';
    root.innerHTML =
      '<div class="bar"><div class="t" id="cropTip">裁剪</div>' +
      '<button id="cropCancel">取消</button>' +
      '<button id="cropSkip">跳过</button>' +
      '<button id="cropOk" class="primary">确定</button></div>' +
      '<div class="wrap"><div class="stage" id="cropStage">' +
      '<canvas id="cropCv"></canvas>' +
      '<div class="box" id="cropBox">' +
      '<i class="h nw" data-h="nw"></i><i class="h ne" data-h="ne"></i>' +
      '<i class="h sw" data-h="sw"></i><i class="h se" data-h="se"></i>' +
      '</div></div></div>' +
      '<div class="bar"><button id="cropRot">旋转 90°</button>' +
      '<button id="cropFull">全选</button></div>';
    document.body.appendChild(root);

    cv = root.querySelector('#cropCv');
    g = cv.getContext('2d');
    box = root.querySelector('#cropBox');
    tip = root.querySelector('#cropTip');

    root.querySelector('#cropCancel').onclick = function () { finish(null); };
    root.querySelector('#cropSkip').onclick = function () { finish(false); };
    root.querySelector('#cropOk').onclick = function () { finish(true); };
    root.querySelector('#cropFull').onclick = function () { full(); paint(); };
    root.querySelector('#cropRot').onclick = rot90;

    var stage = root.querySelector('#cropStage');
    stage.addEventListener('pointerdown', onDown);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
    window.addEventListener('resize', function () {
      if (root.classList.contains('on') && src) { layout(); full(); paint(); }
    });
  }
  function clamp(v, a, b) { return v < a ? a : (v > b ? b : v); }
  function full() { L = 0; T = 0; R = W; B = H; }

  function layout() {
    var wrap = root.querySelector('.wrap');
    var aw = Math.max(40, wrap.clientWidth - 20);
    var ah = Math.max(40, wrap.clientHeight - 20);
    var k = Math.min(aw / src.width, ah / src.height);
    W = Math.max(1, Math.round(src.width * k));
    H = Math.max(1, Math.round(src.height * k));
    cv.width = W; cv.height = H;
    cv.style.width = W + 'px'; cv.style.height = H + 'px';
    g.drawImage(src, 0, 0, W, H);
  }

  function paint() {
    box.style.left = L + 'px'; box.style.top = T + 'px';
    box.style.width = (R - L) + 'px'; box.style.height = (B - T) + 'px';
  }

  function onDown(e) {
    if (!src) return;
    var h = e.target && e.target.dataset ? e.target.dataset.h : null;
    var r = box.getBoundingClientRect();
    var inside = e.clientX >= r.left && e.clientX <= r.right &&
                 e.clientY >= r.top && e.clientY <= r.bottom;
    if (!h && !inside) return;
    e.preventDefault();
    drag = { c: h, x: e.clientX, y: e.clientY, L: L, T: T, R: R, B: B };
  }

  function onMove(e) {
    if (!drag) return;
    e.preventDefault();
    var dx = e.clientX - drag.x, dy = e.clientY - drag.y, c = drag.c;
    if (!c) {
      var w = drag.R - drag.L, hh = drag.B - drag.T;
      L = clamp(drag.L + dx, 0, W - w); T = clamp(drag.T + dy, 0, H - hh);
      R = L + w; B = T + hh;
    } else {
      L = drag.L; T = drag.T; R = drag.R; B = drag.B;
      if (c.indexOf('w') >= 0) L = clamp(drag.L + dx, 0, R - MIN);
      if (c.indexOf('e') >= 0) R = clamp(drag.R + dx, L + MIN, W);
      if (c.indexOf('n') >= 0) T = clamp(drag.T + dy, 0, B - MIN);
      if (c.indexOf('s') >= 0) B = clamp(drag.B + dy, T + MIN, H);
    }
    paint();
  }

  function onUp() { drag = null; }

  function loadImg(file) {
    return new Promise(function (res, rej) {
      function fb() {
        var im = new Image();
        im.onload = function () { res(im); };
        im.onerror = function () { rej(new Error('decode failed')); };
        im.src = URL.createObjectURL(file);
      }
      if (window.createImageBitmap) { createImageBitmap(file).then(res, fb); }
      else { fb(); }
    });
  }

  function rot90() {
    var c = document.createElement('canvas');
    c.width = src.height; c.height = src.width;
    var k = c.getContext('2d');
    k.translate(c.width / 2, c.height / 2);
    k.rotate(Math.PI / 2);
    k.drawImage(src, -src.width / 2, -src.height / 2);
    src = c; layout(); full(); paint();
  }

  function close() { root.classList.remove('on'); resolver = null; src = null; }

  function finish(ok) {
    if (!resolver) return;
    var r = resolver;
    if (ok !== true) { close(); r(ok === false ? false : null); return; }
    var sx = src.width / W, sy = src.height / H;
    var cw = Math.max(1, Math.round((R - L) * sx));
    var ch = Math.max(1, Math.round((B - T) * sy));
    var k = Math.min(1, MAX_EDGE / Math.max(cw, ch));
    var out = document.createElement('canvas');
    out.width = Math.max(1, Math.round(cw * k));
    out.height = Math.max(1, Math.round(ch * k));
    out.getContext('2d').drawImage(src, Math.round(L * sx), Math.round(T * sy),
      cw, ch, 0, 0, out.width, out.height);
    out.toBlob(function (b) { close(); r(b || false); }, 'image/jpeg', 0.9);
  }

  window.cropImage = function (file, tag) {
    ensure();
    return new Promise(function (resolve) {
      resolver = resolve;
      loadImg(file).then(function (b) {
        src = b;
        tip.textContent = tag || '拖动四角裁剪';
        root.classList.add('on');
        layout(); full(); paint();
      }, function (e) {
        resolver = null;
        alert('图片解码失败，已跳过裁剪\n' + (e && e.message ? e.message : ''));
        resolve(false);
      });
    });
  };
})();