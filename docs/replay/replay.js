(function () {
  'use strict';
  var R = window.REPLAY;
  var $ = function (id) { return document.getElementById(id); };

  // ---- theme (works without data) ----
  var root = document.documentElement;
  var themeBtn = $('theme');
  var userTheme = null; // null = auto, else 'light' or 'dark'
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  function applyTheme() {
    var t = userTheme || (mq && mq.matches ? 'dark' : 'light');
    root.setAttribute('data-theme', t);
    themeBtn.textContent = 'Theme: ' + (userTheme ? t : 'auto (' + t + ')');
    drawLegends();
    if (R && ready) draw();
  }
  var ready = false;
  themeBtn.addEventListener('click', function () {
    userTheme = userTheme === null ? 'light' : (userTheme === 'light' ? 'dark' : null);
    applyTheme();
  });
  if (mq && mq.addEventListener) mq.addEventListener('change', function () { if (!userTheme) applyTheme(); });

  // ---- shared drawing (replay and live): display states, robots, marks, legend icons, tooltip ----
  // Four display states (live_state.DISPLAY_STATES). The raw state is kept only for the tooltip.
  var DISPLAY = ['moving', 'working', 'waiting', 'down'];
  var RAW_TEXT = { moving: 'changed cell', loading: 'at a shelf or station', stalled: 'tried to move and did not',
                   stuck: 'inside a stuck call', frozen: 'reported an error', idle: 'no job, not moving' };
  var showPickers = false, redrawHook = null, tipProvider = null, tipAt = null;

  function robotPath(c, kind, cx, cy, r) {
    c.beginPath();
    if (kind === 'agv') c.arc(cx, cy, r, 0, 6.2832); else c.rect(cx - r, cy - r, 2 * r, 2 * r);
  }
  // Colour is never the only channel: moving = filled, working = filled with a centre dot, waiting = hollow,
  // down = filled with a cross. Pickers are a muted grey unless "show pickers in colour" is ticked; the shapes stay.
  function drawRobot(c, kind, cx, cy, disp, r) {
    var grey = kind === 'picker' && !showPickers;
    var col = grey ? css('--picker') : css('--' + disp), bg = css('--bg'), panel = css('--panel');
    c.save();
    c.lineWidth = 1.5; c.strokeStyle = bg; c.fillStyle = col;
    if (disp === 'waiting') {
      robotPath(c, kind, cx, cy, r); c.fillStyle = panel; c.fill();
      c.strokeStyle = col; c.lineWidth = 2.5; c.stroke();
    } else {
      robotPath(c, kind, cx, cy, r); c.fill(); c.stroke();
    }
    c.strokeStyle = bg; c.fillStyle = bg; c.lineWidth = 2.2;
    if (disp === 'down') {
      var d = r * 0.55;
      c.beginPath(); c.moveTo(cx - d, cy - d); c.lineTo(cx + d, cy + d); c.moveTo(cx + d, cy - d); c.lineTo(cx - d, cy + d); c.stroke();
    } else if (disp === 'working') {
      c.beginPath(); c.arc(cx, cy, r * 0.3, 0, 6.2832); c.fill();
    }
    c.restore();
  }
  // breakdown moment: a four-point star
  function drawStar(c, cx, cy, r, col) {
    c.save();
    c.beginPath();
    for (var k = 0; k < 8; k++) {
      var a = k * Math.PI / 4, rr = k % 2 ? r * 0.35 : r;
      c[k ? 'lineTo' : 'moveTo'](cx + Math.sin(a) * rr, cy - Math.cos(a) * rr);
    }
    c.closePath();
    c.lineWidth = 3.5; c.strokeStyle = css('--bg'); c.stroke();
    c.fillStyle = col; c.fill();
    c.lineWidth = 1; c.strokeStyle = col; c.stroke();
    c.restore();
  }
  // stuck call: a ring around the cell
  function drawRing(c, cx, cy, rr, alpha) {
    c.save();
    c.globalAlpha = alpha;
    c.beginPath(); c.arc(cx, cy, rr, 0, 6.2832); c.strokeStyle = css('--bg'); c.lineWidth = 4; c.stroke();
    c.beginPath(); c.arc(cx, cy, rr, 0, 6.2832); c.strokeStyle = css('--ring'); c.lineWidth = 2; c.stroke();
    c.restore();
  }
  // grade mark: check = the call was graded right, cross = wrong
  function drawMark(c, cx, cy, verdict, size) {
    var ok = verdict === 'confirmed';
    c.save();
    c.font = 'bold ' + size + 'px system-ui, sans-serif'; c.textAlign = 'center'; c.textBaseline = 'middle';
    c.lineWidth = 4; c.strokeStyle = css('--bg'); c.strokeText(ok ? '✓' : '✗', cx, cy);
    c.fillStyle = css(ok ? '--ok' : '--off'); c.fillText(ok ? '✓' : '✗', cx, cy);
    c.restore();
  }
  function drawIcon(c, ico) {
    var bg = css('--bg');
    if (ico === 'agv') {
      c.beginPath(); c.arc(12, 12, 7, 0, 6.2832); c.fillStyle = css('--muted'); c.fill(); c.strokeStyle = bg; c.lineWidth = 1.5; c.stroke();
    } else if (ico === 'picker') {
      drawRobot(c, 'picker', 12, 12, 'moving', 6.5);
    } else if (ico === 'moving' || ico === 'working' || ico === 'waiting' || ico === 'down') {
      drawRobot(c, 'agv', 12, 12, ico, 7);
    } else if (ico === 'floor') {
      c.strokeStyle = css('--obst'); c.lineWidth = 2; c.setLineDash([4, 3]); c.strokeRect(4, 4, 16, 16); c.setLineDash([]);
    } else if (ico === 'breakdown') {
      drawStar(c, 12, 12, 8, css('--down'));
    } else if (ico === 'shade') {
      c.fillStyle = 'rgba(' + css('--cost') + ',.6)'; c.fillRect(4, 4, 16, 16);
      c.strokeStyle = css('--line'); c.lineWidth = 1; c.strokeRect(4.5, 4.5, 15, 15);
    } else if (ico === 'call') {
      drawRing(c, 12, 12, 8, 1);
    } else if (ico === 'marks') {
      drawMark(c, 9, 12, 'confirmed', 15); drawMark(c, 29, 12, 'refuted', 15);
    } else if (ico === 'placed') {
      c.strokeStyle = css('--accent'); c.lineWidth = 3; c.strokeRect(4, 4, 16, 16); c.fillStyle = css('--accent'); c.fillRect(4, 4, 6, 6);
    }
  }
  function drawLegends() {
    Array.prototype.forEach.call(document.querySelectorAll('canvas[data-ico]'), function (cv) {
      var d = Math.max(1, window.devicePixelRatio || 1), w = cv.getAttribute('data-ico') === 'marks' ? 38 : 24;
      if (cv.width !== Math.round(w * d)) { cv.width = Math.round(w * d); cv.height = Math.round(24 * d); cv.style.width = w + 'px'; cv.style.height = '24px'; }
      var c = cv.getContext('2d');
      c.setTransform(d, 0, 0, d, 0, 0);
      c.clearRect(0, 0, w, 24);
      drawIcon(c, cv.getAttribute('data-ico'));
    });
  }
  var pickBox = $('pickcol');
  pickBox.addEventListener('change', function () { showPickers = pickBox.checked; drawLegends(); if (redrawHook) redrawHook(); });

  // tooltip: hover (mouse) or tap (touch) on a robot. provider(cx, cy) -> [{id, kind, raw, disp, job, waitS}].
  function tipLines(i) {
    return [i.id + ', ' + (i.kind === 'agv' ? 'AGV' : 'picker'), 'State: ' + i.disp + ' (' + (RAW_TEXT[i.raw] || 'no further detail') + ')',
            'Job: ' + (i.job || 'none'), (i.job ? 'Waiting: ' : 'Not moving: ') + i.waitS + ' s'];
  }
  function refreshTip() {
    var tip = $('tip');
    var list = tipAt && tipProvider ? tipProvider(tipAt.cell[0], tipAt.cell[1]) : [];
    if (!list.length) { tip.hidden = true; return; }
    tip.textContent = '';
    list.forEach(function (i, k) {
      var box = document.createElement('div');
      if (k) box.className = 'tipsep';
      tipLines(i).forEach(function (t, j) { var line = document.createElement('div'); if (!j) line.className = 'tiphead'; line.textContent = t; box.appendChild(line); });
      tip.appendChild(box);
    });
    tip.hidden = false;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(4, Math.min(window.innerWidth - w - 4, tipAt.x + 12)) + 'px';
    tip.style.top = Math.max(4, Math.min(window.innerHeight - h - 4, tipAt.y + 12)) + 'px';
  }
  function wireTips(cv, dims) {
    function cellOf(ev) {
      var r = cv.getBoundingClientRect(), g = dims();
      if (!g) return null;
      var cx = Math.floor((ev.clientX - r.left) / r.width * g.width), cy = Math.floor((ev.clientY - r.top) / r.height * g.height);
      return cx < 0 || cy < 0 || cx >= g.width || cy >= g.height ? null : [cx, cy];
    }
    cv.addEventListener('pointermove', function (ev) {
      if (ev.pointerType === 'touch') return;
      var c = cellOf(ev);
      tipAt = c ? { cell: c, x: ev.clientX, y: ev.clientY } : null;
      refreshTip();
    });
    cv.addEventListener('pointerleave', function (ev) { if (ev.pointerType !== 'touch') { tipAt = null; refreshTip(); } });
    cv.addEventListener('pointerdown', function (ev) {
      if (ev.pointerType !== 'touch') return;
      var c = cellOf(ev);
      var same = tipAt && c && tipAt.cell[0] === c[0] && tipAt.cell[1] === c[1];
      // only a tap on a robot opens a tooltip, so a tap on an empty cell leaves tipAt null (the live prompt relies on it)
      tipAt = c && !same && tipProvider && tipProvider(c[0], c[1]).length ? { cell: c, x: ev.clientX, y: ev.clientY } : null;
      refreshTip();
    });
    function clear() { if (tipAt) { tipAt = null; refreshTip(); } }
    document.addEventListener('pointerdown', function (ev) { if (ev.target !== cv) clear(); });
    window.addEventListener('scroll', clear, { passive: true });
    document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') clear(); });
  }

  // ---- live mode (S8G): ?live=<url on localhost> polls the analyser's /state at 2 Hz; without the param nothing below runs ----
  var POLL_MS = 500; // 2 Hz
  var httpGet = function (url, opts) { return window.fetch.call(window, url, opts); }; // live mode is the only caller
  var LIVE_HOSTS = ['localhost', '127.0.0.1'];
  var liveParam = new URLSearchParams(window.location.search).get('live');
  if (liveParam !== null) {
    var liveBase = liveBaseOf(liveParam);
    if (liveBase) { startLive(liveBase); return; }
    var bad = document.createElement('p');
    bad.className = 'livebar bad';
    bad.setAttribute('role', 'alert');
    bad.textContent = 'The live parameter was ignored: it must be an http URL on localhost or 127.0.0.1 (the page sends injections to it). Showing the offline replay.';
    document.querySelector('.head').insertAdjacentElement('afterend', bad);
  }

  if (!R || !R.frames || !R.meta) {
    $('nodata').hidden = false;
    applyTheme();
    return;
  }
  $('app').hidden = false;

  var M = R.meta, G = R.grid, STEPS = M.steps, SEC = M.step_seconds;
  // raw state -> display state, as exported (meta.state_display); a raw value missing from it is drawn as waiting
  function dispOf(raw) { var m = M.state_display; return (m && m[raw]) || 'waiting'; }
  var CELL = 22;
  var hasMap = !!R.with_map;
  var layer = 'without';
  var lastTxt = '', pos = 0, playing = false, speed = 1, lastTs = 0, lastLive = 0, lastErr = '', scrubTimer = null;
  var rmq = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  var reduceMotion = !!(rmq && rmq.matches);
  if (rmq && rmq.addEventListener) rmq.addEventListener('change', function () { reduceMotion = rmq.matches; });

  function css(name) { return getComputedStyle(root).getPropertyValue(name).trim(); }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function clock(step) {
    var d = new Date((M.t0_ts + step * SEC) * 1000);
    return pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ':' + pad(d.getUTCSeconds());
  }
  function clockAt(t) { return clock((t - M.t0_ts) / SEC); }
  function fmt(n) { return Number(n).toLocaleString('en-US'); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  // ---- static look-ups ----
  var obstacleSet = {};
  R.obstacles.forEach(function (o) { obstacleSet[o.cell] = true; });
  var shelfSet = {};
  G.shelves.forEach(function (s) { shelfSet[s[0] + ',' + s[1]] = true; });
  var goalSet = {};
  G.goals.forEach(function (s) { goalSet[s[0] + ',' + s[1]] = true; });
  function usable(list) { return (list || []).filter(function (e) { return !e.left_censored && e.resolution !== 'interrupted'; }); }
  var episodesMain = usable(R.episodes);
  var episodesWith = hasMap ? usable(R.with_map.episodes) : [];
  var pubs = R.publishes;

  // ---- legend ----
  function legendItem(parent, color, text, shape) {
    var li = el('li');
    var sw = el('span', 'sw');
    sw.style.background = color;
    if (shape === 'circle') sw.style.borderRadius = '50%';
    li.appendChild(sw);
    li.appendChild(document.createTextNode(text));
    parent.appendChild(li);
  }
  // ---- canvases ----
  var floor = $('floor'), fctx = floor.getContext('2d');
  var prec = $('prec'), pctx = prec.getContext('2d');
  var dpr = Math.max(1, window.devicePixelRatio || 1);
  var PW = 460, PH = 220;
  // Only the CSS width is set; height:auto keeps the aspect ratio of the width/height attributes.
  function size(canvas, ctx, w, h) {
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    canvas.style.width = w + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  function sizeAll() {
    dpr = Math.max(1, window.devicePixelRatio || 1);
    size(floor, fctx, G.width * CELL, G.height * CELL);
    size(prec, pctx, PW, PH);
  }
  sizeAll();
  window.addEventListener('resize', function () { sizeAll(); if (ready) draw(); });

  // ---- helpers over time ----
  function latestPublish(step) {
    var p = null;
    for (var i = 0; i < pubs.length; i++) { if (pubs[i].step <= step) p = pubs[i]; else break; }
    return p;
  }
  function frames() { return layer === 'with' ? R.with_map.frames : R.frames; }

  // ---- panel 1: floor ----
  function drawFloor(step) {
    var c = fctx;
    c.clearRect(0, 0, G.width * CELL, G.height * CELL);
    var hw = css('--hw'), shelf = css('--shelf'), goal = css('--goal');
    var pub = layer === 'with' ? null : latestPublish(step);
    var cost = {};
    if (pub) pub.cells.forEach(function (r) { cost[r[0]] = r[1]; });
    for (var y = 0; y < G.height; y++) {
      for (var x = 0; x < G.width; x++) {
        var key = x + ',' + y;
        c.fillStyle = goalSet[key] ? goal : (G.highway[y].charAt(x) === '1' ? hw : shelf);
        c.fillRect(x * CELL, y * CELL, CELL, CELL);
        if (cost[key]) {
          c.fillStyle = 'rgba(' + css('--cost') + ',' + Math.min(0.5, 0.15 + 0.7 * cost[key]).toFixed(3) + ')';
          c.fillRect(x * CELL, y * CELL, CELL, CELL);
        }
      }
    }
    c.strokeStyle = css('--line'); c.lineWidth = 0.5;
    for (var gx = 0; gx <= G.width; gx++) { c.beginPath(); c.moveTo(gx * CELL, 0); c.lineTo(gx * CELL, G.height * CELL); c.stroke(); }
    for (var gy = 0; gy <= G.height; gy++) { c.beginPath(); c.moveTo(0, gy * CELL); c.lineTo(G.width * CELL, gy * CELL); c.stroke(); }
    // hidden floor problems: dashed outlined boxes
    c.strokeStyle = css('--obst'); c.lineWidth = 2; c.setLineDash([4, 3]);
    R.obstacles.forEach(function (o) {
      var xy = o.cell.split(',');
      c.strokeRect(+xy[0] * CELL + 2, +xy[1] * CELL + 2, CELL - 4, CELL - 4);
    });
    c.setLineDash([]);
    // stuck calls of the shown layer: a pulse at the cell while the call is open (still at paused or reduced motion)
    var phase = (!playing || reduceMotion) ? 0.5 : ((performance.now() / 700) % 1);
    var calls = layer === 'with' ? episodesWith : episodesMain;
    calls.forEach(function (e) {
      if (e.start_step <= step && (e.end_step === null || step <= e.end_step)) {
        drawRing(c, e.cell[0] * CELL + CELL / 2, e.cell[1] * CELL + CELL / 2, CELL * (0.45 + 0.4 * phase), 1 - 0.7 * phase);
      }
    });
    // robots; a flash on the step a robot goes down
    var fr = frames()[step], prev = step > 0 ? frames()[step - 1] : null;
    R.robots.forEach(function (r, i) {
      var e = fr[i], cx = e[0] * CELL + CELL / 2, cy = e[1] * CELL + CELL / 2;
      drawRobot(c, r.kind, cx, cy, dispOf(e[2]), r.kind === 'agv' ? CELL * 0.33 : CELL * 0.3);
      if (prev && dispOf(e[2]) === 'down' && dispOf(prev[i][2]) !== 'down') drawStar(c, cx, cy - CELL * 0.45, CELL * 0.55, css('--down'));
    });
    // grade marks, anchored to end_step: how the call ended decides the grade, and a batch run stamps graded_at with the
    // run's last timestamp, so that is no display time. Shown for max(3, 3 * speed) steps; inconclusive and ungraded draw nothing.
    var hold = Math.max(3, 3 * speed);
    calls.forEach(function (e) {
      if ((e.verdict === 'confirmed' || e.verdict === 'refuted') && e.end_step !== null && e.end_step <= step && step <= e.end_step + hold) {
        drawMark(c, e.cell[0] * CELL + CELL / 2, e.cell[1] * CELL + CELL / 2, e.verdict, CELL * 0.9);
      }
    });
  }

  // ---- panel 2: extractor ----
  var X = R.extractor, S = X.series, T = X.totals;
  var counterRows = [
    ['bytes read (uncompressed)', function (i) { return fmt(S.bytes[i]) + ' B'; }],
    ['messages (lines)', function (i) { return fmt(S.messages[i]); }],
    ['parsed', function (i) { return fmt(S.parsed[i]); }],
    ['rejected', function (i) {
      if (!S.rejected[i]) return 'none rejected';
      var top = null, best = 0;
      Object.keys(S.rejected_by_reason).forEach(function (k) { var v = S.rejected_by_reason[k][i]; if (v > best) { best = v; top = k; } });
      return fmt(S.rejected[i]) + (top ? ' (top reason: ' + top + ')' : '');
    }],
    ['duplicates', function (i) { return fmt(S.duplicates[i]); }],
    ['sequence gaps', function (i) { return fmt(S.sequence_gaps[i]) + ' (' + fmt(S.missing_messages[i]) + ' messages missing)'; }],
    ['accepted', function (i) { return fmt(S.accepted[i]); }],
    ['coverage', function (i) { return S.coverage[i] === null ? 'unknown (no message count from the run)' : (S.coverage[i] * 100).toFixed(1) + ' %'; }]
  ];
  var counterEls = counterRows.map(function (r) {
    var dt = el('dt', null, r[0]), dd = el('dd', null, '');
    $('counters').appendChild(dt); $('counters').appendChild(dd);
    return dd;
  });
  (function () {
    var chk = X.check;
    $('match').textContent = chk
      ? 'The replay matches the import step\'s checkpoint: ' + fmt(T.bytes) + ' bytes, ' + fmt(chk.messages_parsed) + ' parsed, ' +
        fmt(chk.messages_accepted) + ' accepted, ' + fmt(chk.messages_rejected) + ' rejected, ' + fmt(chk.duplicates) +
        ' duplicates, ' + fmt(chk.sequence_gaps) + ' sequence gaps.'
      : 'The store has no import checkpoint for this file, so the replay could not be compared with it.';
  })();
  function drawExtractor(step) {
    counterRows.forEach(function (r, k) { counterEls[k].textContent = r[1](step); });
    var cov = S.coverage[step];
    $('covbar').style.width = (cov === null ? 0 : Math.min(1, cov) * 100) + '%';
    $('covlabel').textContent = cov === null ? 'Coverage is unknown because the run has no message count of its own.'
      : 'Coverage ' + (cov * 100).toFixed(1) + ' % of the ' + fmt(T.expected_messages) + ' messages the run itself counted (full bar = 100 %).';
  }

  // ---- panel 3: analyser ----
  var PAD = { l: 40, r: 14, t: 12, b: 26 };
  function drawPrecision(step) {
    var c = pctx;
    c.clearRect(0, 0, PW, PH);
    var ink = css('--ink'), muted = css('--muted'), line = css('--line'), acc = css('--accent');
    var w = PW - PAD.l - PAD.r, h = PH - PAD.t - PAD.b;
    function px(s) { return PAD.l + (s / Math.max(1, STEPS - 1)) * w; }
    function py(v) { return PAD.t + (1 - v) * h; }
    c.font = '12px system-ui, sans-serif'; c.fillStyle = muted; c.strokeStyle = line; c.lineWidth = 1;
    [0, 0.25, 0.5, 0.75, 1].forEach(function (v) {
      c.beginPath(); c.moveTo(PAD.l, py(v)); c.lineTo(PW - PAD.r, py(v)); c.stroke();
      c.textAlign = 'right'; c.fillText(v.toFixed(2), PAD.l - 5, py(v) + 4);
    });
    c.textAlign = 'center';
    [0, 0.25, 0.5, 0.75, 1].forEach(function (f) {
      var s = Math.round(f * Math.max(1, STEPS - 1));
      c.fillText(clock(s), px(s), PH - 8);
    });
    c.strokeStyle = muted; c.setLineDash([2, 3]);
    c.beginPath(); c.moveTo(px(step), PAD.t); c.lineTo(px(step), PAD.t + h); c.stroke(); c.setLineDash([]);
    var shown = pubs.filter(function (p) { return p.step <= step; });
    shown.forEach(function (p) {
      c.fillStyle = acc; c.beginPath(); c.arc(px(p.step), py(p.precision_at_20), 5, 0, 6.2832); c.fill();
      c.fillStyle = ink; c.textAlign = p.step > STEPS * 0.8 ? 'right' : 'left';
      c.fillText(p.precision_at_20.toFixed(2) + ' (' + p.hits_at_20 + '/20)', px(p.step) + (p.step > STEPS * 0.8 ? -9 : 9), py(p.precision_at_20) - 8);
    });
    var st = $('precstate');
    if (!pubs.length) st.textContent = 'The analyser published no cost map in this run.';
    else if (!shown.length) st.textContent = 'No map published yet (the first publish is at ' + clock(pubs[0].step) + ').';
    else st.textContent = '';
  }

  var gradeKey = null;
  // The words of the "outcome" grade depend on what it measured: rank wording only for a rank grade.
  function wording(kind) {
    if (kind === 'rank') return { lab: 'rank grade', ok: 'still in top 20 after the horizon', off: 'dropped out' };
    if (kind === 'count') return { lab: 'count grade', ok: 'stall count about as claimed', off: 'stall count off' };
    return { lab: 'outcome grade', ok: 'outcome as claimed', off: 'outcome not as claimed' };
  }
  function seg(parent, n, total, color) {
    if (!n) return;
    var s = el('span', null, String(n));
    s.style.width = (100 * n / total) + '%'; s.style.background = color;
    parent.appendChild(s);
  }
  function drawGradeLegend(kinds) {
    var g = $('glegend');
    g.textContent = '';
    var oks = [], offs = [];
    ['rank', 'count', 'mixed'].forEach(function (k) {
      if (kinds[k]) { oks.push(wording(k).ok); offs.push(wording(k).off); }
    });
    oks.push('on a hidden problem'); offs.push('not on one');
    legendItem(g, 'var(--ok)', oks.join(' / '));
    legendItem(g, 'var(--off)', offs.join(' / '));
    legendItem(g, 'var(--open)', 'open or pending');
  }
  function drawGrades(step) {
    var shown = pubs.filter(function (p) { return p.step <= step; });
    var graded = shown.map(function (p) { return R.grades.per_publish[pubs.indexOf(p)]; });
    var key = graded.map(function (g) {
      return g.t + ':' + (g.window_end_step !== null && g.window_end_step <= step ? 1 : 0);
    }).join('|');
    if (key === gradeKey) return;
    gradeKey = key;
    var host = $('grades');
    host.textContent = '';
    var kinds = {};
    graded.forEach(function (g) { if (g.outcome_kind) kinds[g.outcome_kind] = true; });
    drawGradeLegend(kinds);
    if (!pubs.length) { host.appendChild(el('p', 'state', 'No publishes, so nothing to grade.')); return; }
    if (!shown.length) { host.appendChild(el('p', 'state', 'No map published yet, so nothing to grade.')); return; }
    graded.forEach(function (g) {
      var box = el('div', 'pub');
      var pr = pubs[R.grades.per_publish.indexOf(g)];
      box.appendChild(el('div', 'name', 'Publish at ' + clockAt(g.t) + ': ' + g.forecasts + ' calls, top-20 hit rate ' +
        pr.precision_at_20.toFixed(2) + ' (' + pr.hits_at_20 + '/20)'));
      var outcomeKnown = g.window_end_step !== null && g.window_end_step <= step;
      var w = wording(g.outcome_kind);
      var r1 = el('div', 'row');
      r1.appendChild(el('span', 'lab', w.lab));
      var b1 = el('div', 'bar');
      b1.setAttribute('aria-hidden', 'true');
      if (g.window_end_step === null) {
        seg(b1, g.open, g.forecasts, 'var(--open)');
      } else if (!outcomeKnown) {
        seg(b1, g.forecasts, g.forecasts, 'var(--open)');
      } else {
        seg(b1, g.outcome.ok, g.forecasts, 'var(--ok)');
        seg(b1, g.outcome.off, g.forecasts, 'var(--off)');
        seg(b1, g.open, g.forecasts, 'var(--open)');
      }
      r1.appendChild(b1); box.appendChild(r1);
      var r2 = el('div', 'row');
      r2.appendChild(el('span', 'lab', 'truth grade'));
      var b2 = el('div', 'bar');
      b2.setAttribute('aria-hidden', 'true');
      seg(b2, g.truth.hit, g.forecasts, 'var(--ok)');
      seg(b2, g.truth.false_alarm, g.forecasts, 'var(--off)');
      r2.appendChild(b2); box.appendChild(r2);
      var t = el('div', 'cap small');
      var parts = [];
      if (outcomeKnown) {
        parts.push(g.outcome.ok + ' ' + w.ok + ', ' + g.outcome.off + ' ' + w.off);
      } else if (g.window_end_step === null) {
        parts.push(g.open + ' open: the horizon ends after the stream');
      } else {
        parts.push('outcome known at ' + clock(g.window_end_step));
      }
      parts.push(g.truth.hit + ' on a hidden problem, ' + g.truth.false_alarm + ' not on one');
      t.textContent = parts.join('; ');
      box.appendChild(t);
      host.appendChild(box);
    });
  }

  var topKey = null;
  function drawTop(step) {
    var p = latestPublish(step);
    var key = p ? p.t : 'none';
    if (key === topKey) return;
    topKey = key;
    var ol = $('top');
    ol.textContent = '';
    if (!p) { var li = el('li', null, 'no map published yet'); li.style.listStyle = 'none'; ol.appendChild(li); return; }
    p.cells.slice(0, 10).forEach(function (r) {
      ol.appendChild(el('li', null, r[0] + '  cost ' + r[1].toFixed(2) + '  stalls ' + r[2] + (obstacleSet[r[0]] ? '  [on a hidden problem]' : '  [not on one]')));
    });
  }

  // ---- panel 4: lessons ----
  var HAS_LESSONS = R.lessons !== undefined;
  var LESSONS = R.lessons || [];
  var lessonKey = null;
  function drawLessons(step) {
    var shown = LESSONS.filter(function (l) { return l.decided_at_step <= step; });
    var key = shown.map(function (l) {
      return (l.graded_at_step !== null && l.graded_at_step <= step) ? l.verdict : '-';
    }).join('|') + '#' + shown.length;
    if (key === lessonKey) return;
    lessonKey = key;
    var ul = $('lessons');
    ul.textContent = '';
    var state = $('lessonstate');
    if (!HAS_LESSONS) { state.textContent = 'Lesson data is not included in this file.'; return; }
    if (!LESSONS.length) { state.textContent = 'No lessons in this run, in any zone: no rule reached its threshold.'; return; }
    if (!shown.length) { state.textContent = 'No lessons yet. The first one is drawn at ' + clock(LESSONS[0].decided_at_step) + '.'; return; }
    var held = 0, failed = 0, waiting = 0, never = 0;
    shown.forEach(function (l) {
      if (l.graded_at_step === null) never++;
      else if (l.graded_at_step > step) waiting++;
      else if (l.verdict === 'ok') held++;
      else failed++;
    });
    state.textContent = 'Graded so far: ' + held + ' held, ' + failed + ' did not hold, ' + waiting + ' pending' +
      (never ? ', ' + never + ' not gradable (the shift ends before the next window).' : '.');
    shown.slice().reverse().forEach(function (l) {
      var known = l.graded_at_step !== null && l.graded_at_step <= step;
      var never = l.graded_at_step === null;
      var status = !known ? 'pending' : (l.verdict === 'ok' ? 'ok' : 'off');
      var li = el('li', 'les ' + status);
      var mark = el('span', 'mark', never ? 'not gradable' : !known ? 'pending' : (status === 'ok' ? '✓ held' : '✗ did not hold'));
      li.appendChild(mark);
      li.appendChild(el('span', 'ltxt', l.text));
      li.appendChild(el('span', 'conf', 'zone ' + l.zone + (String(l.zone) === String(R.meta.zone) ? ' (the zone shown above)' : '') +
        ', rule ' + l.lesson_kind + ', support ' + l.confidence.toFixed(2) + ', drawn at ' + clock(l.decided_at_step)));
      ul.appendChild(li);
    });
  }

  function callCounts(step) {
    // open = not ended at this step; an ended call is right (confirmed), wrong (refuted) or has no verdict (inconclusive,
    // ungraded, or a layer without a grader)
    var n = 0, open = 0, right = 0, wrong = 0;
    (layer === 'with' ? episodesWith : episodesMain).forEach(function (e) {
      if (e.start_step > step) return;
      n++;
      if (e.end_step === null || e.end_step > step) open++;
      else if (e.verdict === 'confirmed') right++;
      else if (e.verdict === 'refuted') wrong++;
    });
    return 'Stuck calls so far: ' + n + '; still open ' + open + '; graded right ' + right + ', wrong ' + wrong +
      '; no verdict ' + (n - open - right - wrong) + '.';
  }
  function mapState(step) {
    var st = $('mapstate'), t;
    if (layer === 'with') t = 'Second run with the map switched on: the red shading belongs to the first run and is hidden, the stuck-call rings come from the analyser on this run.';
    else if (!pubs.length) t = 'The analyser published no cost map in this run.';
    else if (!latestPublish(step)) t = 'No map published yet (the first publish is at ' + clock(pubs[0].step) + ').';
    else t = '';
    st.textContent = (t ? t + ' ' : '') + callCounts(step);
  }

  // ---- text for screen readers ----
  function counts(step) {
    var c = {};
    frames()[step].forEach(function (e) { var d = dispOf(e[2]); c[d] = (c[d] || 0) + 1; });
    return DISPLAY.filter(function (s) { return c[s]; }).map(function (s) { return c[s] + ' ' + s; }).join(', ');
  }
  function summary(step) {
    var pub = latestPublish(step);
    return 'Step ' + step + ' of ' + (STEPS - 1) + ', fleet time ' + clock(step) + '. Robots: ' + counts(step) + '. Extractor: ' +
      fmt(S.parsed[step]) + ' parsed, ' + fmt(S.rejected[step]) + ' rejected, ' + fmt(S.duplicates[step]) + ' duplicates. ' +
      (pub ? 'Latest cost map at ' + clock(pub.step) + ' with top-20 hit rate ' + pub.precision_at_20.toFixed(2) + '.' : 'No cost map published yet.');
  }
  function curStep() { return Math.min(STEPS - 1, Math.max(0, Math.floor(pos))); }
  // The live region is written only when playback is not running: on pause, on a step, after a scrub settles.
  function announce() {
    if (playing) return;
    var step = curStep();
    $('live').textContent = 'Step ' + step + ' of ' + (STEPS - 1) + ', fleet time ' + clock(step) + '. Robots: ' + counts(step) + '.';
  }

  // ---- main draw ----
  function draw() {
    var step = curStep();
    drawFloor(step); drawExtractor(step); drawPrecision(step); drawGrades(step); drawTop(step); drawLessons(step); mapState(step);
    $('clock').textContent = 'step ' + step + ' / ' + (STEPS - 1) + '  ' + clock(step);
    var sc = $('scrub');
    sc.value = step;
    sc.setAttribute('aria-valuetext', 'step ' + step + ' of ' + (STEPS - 1) + ', fleet time ' + clock(step));
    var now = performance.now();
    if (now - lastLive > 2000 || !playing) {
      var txt = summary(step);
      if (txt !== lastTxt) {
        lastTxt = txt;
        floor.setAttribute('aria-label', 'Warehouse floor. ' + txt);
      }
      lastLive = now;
    }
    refreshTip();
  }

  // tooltip: waiting seconds = consecutive steps up to and including this step with display state waiting, times step_seconds
  function waitSteps(i, step) {
    var n = 0, fr = frames();
    for (var k = step; k >= 0 && dispOf(fr[k][i][2]) === 'waiting'; k--) n++;
    return n;
  }
  tipProvider = function (cx, cy) {
    var step = curStep(), fr = frames()[step], out = [];
    R.robots.forEach(function (r, i) {
      var e = fr[i];
      if (e[0] === cx && e[1] === cy) out.push({ id: r.serial, kind: r.kind, raw: e[2], disp: dispOf(e[2]), job: e[3], waitS: waitSteps(i, step) * SEC });
    });
    return out;
  };
  wireTips(floor, function () { return G; });
  redrawHook = function () { draw(); };

  function setPlaying(p) {
    var was = playing;
    playing = p;
    if (p && pos >= STEPS - 1) pos = 0;
    $('play').textContent = p ? 'Pause' : 'Play';
    lastTs = 0;
    if (was && !p) announce();
  }
  function tick(ts) {
    requestAnimationFrame(tick);
    try {
      if (playing) {
        if (lastTs) pos = Math.min(STEPS - 1, pos + Math.min(0.25, (ts - lastTs) / 1000) * speed);
        lastTs = ts;
        if (pos >= STEPS - 1) setPlaying(false);
      }
      draw();
    } catch (err) {
      var msg = 'The page hit an error while drawing: ' + (err && err.message ? err.message : err);
      if (msg !== lastErr) {
        lastErr = msg;
        $('live').textContent = msg;
        $('mapstate').textContent = msg;
      }
    }
  }

  $('play').addEventListener('click', function () { setPlaying(!playing); });
  $('speed').addEventListener('change', function (e) { speed = +e.target.value; draw(); });
  $('scrub').max = STEPS - 1;
  $('scrub').addEventListener('input', function (e) {
    pos = +e.target.value; draw();
    clearTimeout(scrubTimer);
    scrubTimer = setTimeout(announce, 400);
  });
  document.addEventListener('keydown', function (e) {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    var t = e.target && e.target.tagName;
    if (t === 'INPUT' || t === 'SELECT' || t === 'TEXTAREA' || t === 'BUTTON') return;
    if (e.key === ' ') { e.preventDefault(); setPlaying(!playing); }
    else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault();
      pos = Math.min(STEPS - 1, Math.max(0, Math.floor(pos) + (e.key === 'ArrowRight' ? 1 : -1) * (e.shiftKey ? 10 : 1)));
      setPlaying(false); draw(); announce();
    }
  });

  if (hasMap) {
    $('routerBox').hidden = false;
    var note = $('mapnote');
    note.hidden = false;
    note.textContent = 'With map: ' + R.with_map.note + ' Alpha ' + R.with_map.alpha + ', ' + R.with_map.deliveries + ' deliveries (pick rate ' +
      R.with_map.pick_rate + ' per hour) in this second run.';
    Array.prototype.forEach.call(document.getElementsByName('router'), function (r) {
      r.addEventListener('change', function () { if (r.checked) { layer = r.value; draw(); announce(); } });
    });
  }

  ready = true;
  applyTheme();
  requestAnimationFrame(tick);
  // ---- live mode functions (hoisted; only called when ?live= is valid) ----
  function liveBaseOf(raw) {
    var u;
    try { u = new URL(raw); } catch (e) { return null; }
    if (u.protocol !== 'http:' || LIVE_HOSTS.indexOf(u.hostname) < 0) return null;
    return u.origin;
  }

  function startLive(base) {
    var app = $('app');
    app.hidden = false;
    document.body.classList.add('live');
    $('subtitle').textContent = 'Live: a fleet is running right now. Click a highway cell to put a roadblock there and watch the analyser find it.';
    ['.controls', '.hint', '#mapnote'].forEach(function (q) { var n = document.querySelector(q); if (n) n.hidden = true; });
    ['prec', 'precstate', 'grades', 'glegend', 'routerBox'].forEach(function (id) { var n = $(id); if (n) n.hidden = true; });
    Array.prototype.forEach.call(document.querySelectorAll('[aria-labelledby="h-ana"] .cap, [aria-labelledby="h-ana"] h3'), function (n) { n.hidden = true; });
    $('h-ana').textContent = '3. The analyser: what it flags now';
    $('h-les').textContent = '4. Lessons';
    $('lessonscope').textContent = 'Lessons appear when a time window of the run is over, and get a verdict when the next window is over.';
    var liveGrades = el('p', 'cap', '');
    $('grades').insertAdjacentElement('afterend', liveGrades);
    var topHead = document.querySelectorAll('[aria-labelledby="h-ana"] h3')[1];
    if (topHead) topHead.hidden = false;
    var bar = el('p', 'livebar', 'Connecting to ' + base + ' ...');
    bar.setAttribute('role', 'status');
    document.querySelector('.head').insertAdjacentElement('afterend', bar);

    var CELLV = 22, G = null, state = null, lastOk = 0, failing = 0, inflight = false;
    var barKey = null, lastStep = null, sameSteps = 0;
    var placed = {}; // "x,y" -> p, from this page's own successful POSTs
    var prevDisp = {}, flashUntil = {}, marked = {}, marks = []; // breakdown flashes (per robot) and grade marks, wall clock
    var cursor = null, reveal = false, promptCell = null;
    var floorEl = $('floor'), ctx = floorEl.getContext('2d');
    floorEl.tabIndex = 0;
    floorEl.setAttribute('role', 'application'); // operable in live mode (offline it stays role="img")
    floorEl.setAttribute('aria-label', 'Warehouse floor. Click or press Enter on a highway cell to place a roadblock; arrow keys move the cursor.');

    // legend for the live floor: the static legend plus the operator's own roadblocks
    var planted = document.querySelector('#lrow-planted ul');
    var li = el('li');
    var ic = el('canvas', 'icon');
    ic.setAttribute('data-ico', 'placed'); ic.setAttribute('aria-hidden', 'true');
    li.appendChild(ic); li.appendChild(el('span', null, 'placed by you (outlined roadblocks)'));
    planted.appendChild(li);
    drawLegends();
    var revealBox = el('label', 'revealbox', '');
    var revealIn = document.createElement('input');
    revealIn.type = 'checkbox';
    revealBox.appendChild(revealIn);
    revealBox.appendChild(document.createTextNode(' Reveal the hidden roadblocks'));
    revealBox.hidden = true;
    $('floorlegend').insertAdjacentElement('afterend', revealBox);
    revealIn.addEventListener('change', function () { reveal = revealIn.checked; drawLive(); });

    // counters
    var rows = ['step', 'fleet time', 'messages emitted', 'messages read (parsed)', 'rejected', 'duplicates', 'bytes read', 'messages per second',
                'roadblocks placed / applied', 'emitter'];
    var counterDd = rows.map(function (r) {
      var dt = el('dt', null, r), dd = el('dd', null, '');
      $('counters').appendChild(dt); $('counters').appendChild(dd);
      return dd;
    });
    // inline prompt
    var prompt = el('form', 'prompt', '');
    prompt.hidden = true;
    prompt.setAttribute('role', 'dialog');
    prompt.setAttribute('aria-label', 'Place a roadblock');
    var plabel = el('span', 'plabel', '');
    var pr = document.createElement('input');
    pr.type = 'range'; pr.min = '0.5'; pr.max = '1'; pr.step = '0.01'; pr.value = '0.95';
    pr.setAttribute('aria-label', 'Chance that a robot is stopped when it tries to enter the cell');
    var pval = el('output', 'pval', '0.95');
    var ok = el('button', 'btn primary', 'Place');
    ok.type = 'submit';
    var cancel = el('button', 'btn', 'Cancel');
    cancel.type = 'button';
    [plabel, pr, pval, ok, cancel].forEach(function (n) { prompt.appendChild(n); });
    floorEl.insertAdjacentElement('afterend', prompt);
    pr.addEventListener('input', function () { pval.textContent = (+pr.value).toFixed(2); });
    function closePrompt(refocus) { prompt.hidden = true; promptCell = null; if (refocus) floorEl.focus(); drawLive(); }
    cancel.addEventListener('click', function () { closePrompt(true); });
    prompt.addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.preventDefault(); closePrompt(true); } });
    prompt.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!promptCell) return;
      var key = promptCell, p = +(+pr.value).toFixed(2), body = { floor: {} };
      body.floor[key] = p;
      ok.disabled = true;
      httpGet(base + '/inject', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          ok.disabled = false;
          if (res.ok) {
            placed[key] = p;
            say('Roadblock placed at ' + key + ' (p ' + p.toFixed(2) + '). It starts at step ' + res.j.applies_at_step + '. The cell turns red when the analyser flags it.');
            closePrompt(true);
          } else say('Not placed: ' + (res.j && res.j.error ? res.j.error : 'the server said no') + '.');
        })
        .catch(function () { ok.disabled = false; say('Not placed: the live server is not reachable.'); });
    });

    function say(t) { $('mapstate').textContent = t; $('live').textContent = t; }
    function isHighway(x, y) { return G && G.highway[y] && G.highway[y].charAt(x) === '1'; }
    function isGoal(x, y) { return G.goals.some(function (g) { return g[0] === x && g[1] === y; }); }
    function whyNot(x, y) {
      if (!G || x < 0 || y < 0 || x >= G.width || y >= G.height) return 'outside the floor';
      if (!isHighway(x, y)) return 'a shelf cell: roadblocks go on highway cells only';
      if (isGoal(x, y)) return 'a goal cell: roadblocks go on plain highway cells only';
      return null;
    }
    function openPrompt(x, y) {
      var why = whyNot(x, y);
      if (why) { say('Cannot place at ' + x + ',' + y + ': ' + why + '.'); return; }
      promptCell = x + ',' + y;
      plabel.textContent = 'Roadblock at ' + promptCell + ', chance a robot is stopped: ';
      prompt.hidden = false;
      pr.focus();
      drawLive();
    }
    function cellAt(ev) {
      var r = floorEl.getBoundingClientRect();
      return [Math.floor((ev.clientX - r.left) / r.width * G.width), Math.floor((ev.clientY - r.top) / r.height * G.height)];
    }
    var lastPointer = 'mouse';
    floorEl.addEventListener('pointerdown', function (ev) { lastPointer = ev.pointerType; });
    floorEl.addEventListener('click', function (ev) {
      if (!G) return;
      var c = cellAt(ev);
      // the first tap on a robot shows its tooltip; tapping the same cell again closes it and opens the prompt
      if (lastPointer === 'touch' && tipAt && tipAt.cell[0] === c[0] && tipAt.cell[1] === c[1] && tipProvider(c[0], c[1]).length) return;
      cursor = c; openPrompt(c[0], c[1]);
    });
    floorEl.addEventListener('mousemove', function (ev) {
      if (!G) return;
      var c = cellAt(ev), why = whyNot(c[0], c[1]);
      floorEl.title = why ? 'Cell ' + c[0] + ',' + c[1] + ': ' + why : 'Click to place a roadblock at ' + c[0] + ',' + c[1];
    });
    floorEl.addEventListener('keydown', function (e) {
      if (!G) return;
      if (!cursor) cursor = [0, 0];
      var d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
      if (d) {
        e.preventDefault();
        cursor = [Math.max(0, Math.min(G.width - 1, cursor[0] + d[0])), Math.max(0, Math.min(G.height - 1, cursor[1] + d[1]))];
        var why = whyNot(cursor[0], cursor[1]);
        var here = tipProvider(cursor[0], cursor[1]).map(function (i) { return tipLines(i).join(', '); }).join('; ');
        $('live').textContent = 'Cell ' + cursor[0] + ',' + cursor[1] + (why ? ': ' + why : ': highway, press Enter to place a roadblock') + (here ? '. ' + here : '');
        drawLive();
      } else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openPrompt(cursor[0], cursor[1]); }
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !prompt.hidden) closePrompt(true); });
    themeBtn.addEventListener('click', function () { drawLive(); });

    // ---- drawing ----
    function robotKind(id) { return (parseInt(String(id).split('-')[1], 10) || 0) <= G.agvs ? 'agv' : 'picker'; }
    function drawLive() {
      if (!G) return;
      var c = ctx, W = G.width * CELLV, H = G.height * CELLV;
      var dpr = Math.max(1, window.devicePixelRatio || 1);
      if (floorEl.width !== Math.round(W * dpr)) {
        floorEl.width = Math.round(W * dpr); floorEl.height = Math.round(H * dpr); floorEl.style.width = W + 'px';
      }
      c.setTransform(dpr, 0, 0, dpr, 0, 0);
      c.clearRect(0, 0, W, H);
      var hw = css('--hw'), shelf = css('--shelf'), goal = css('--goal');
      var cells = state && state.costmap ? state.costmap.cells : {};
      for (var y = 0; y < G.height; y++) {
        for (var x = 0; x < G.width; x++) {
          var key = x + ',' + y;
          c.fillStyle = isGoal(x, y) ? goal : (isHighway(x, y) ? hw : shelf);
          c.fillRect(x * CELLV, y * CELLV, CELLV, CELLV);
          if (Object.prototype.hasOwnProperty.call(cells, key)) {
            c.fillStyle = 'rgba(' + css('--cost') + ',' + Math.min(0.55, 0.2 + 0.6 * cells[key]).toFixed(3) + ')';
            c.fillRect(x * CELLV, y * CELLV, CELLV, CELLV);
          }
        }
      }
      c.strokeStyle = css('--line'); c.lineWidth = 0.5;
      for (var gx = 0; gx <= G.width; gx++) { c.beginPath(); c.moveTo(gx * CELLV, 0); c.lineTo(gx * CELLV, H); c.stroke(); }
      for (var gy = 0; gy <= G.height; gy++) { c.beginPath(); c.moveTo(0, gy * CELLV); c.lineTo(W, gy * CELLV); c.stroke(); }
      if (reveal && state && state.truth) {
        c.strokeStyle = css('--obst'); c.lineWidth = 2; c.setLineDash([4, 3]);
        [state.truth.scheduled, state.truth.injected].forEach(function (m) {
          Object.keys(m || {}).forEach(function (k) { var xy = k.split(','); c.strokeRect(+xy[0] * CELLV + 2, +xy[1] * CELLV + 2, CELLV - 4, CELLV - 4); });
        });
        c.setLineDash([]);
      }
      // placed by you: a solid accent outline with a corner mark, never filled (the fill is the analyser's)
      var mine = {};
      Object.keys(placed).forEach(function (k) { mine[k] = true; });
      if (state) state.injections.forEach(function (i) { if (i.kind === 'floor') Object.keys(i.payload).forEach(function (k) { mine[k] = true; }); });
      c.strokeStyle = css('--accent'); c.lineWidth = 3;
      Object.keys(mine).forEach(function (k) {
        var xy = k.split(',');
        c.strokeRect(+xy[0] * CELLV + 2, +xy[1] * CELLV + 2, CELLV - 4, CELLV - 4);
        c.fillStyle = css('--accent');
        c.fillRect(+xy[0] * CELLV + 2, +xy[1] * CELLV + 2, 6, 6);
      });
      if (promptCell) {
        var pxy = promptCell.split(',');
        c.strokeStyle = css('--ink'); c.lineWidth = 2; c.setLineDash([3, 2]);
        c.strokeRect(+pxy[0] * CELLV + 1, +pxy[1] * CELLV + 1, CELLV - 2, CELLV - 2);
        c.setLineDash([]);
      }
      if (cursor && document.activeElement === floorEl) {
        c.strokeStyle = css('--ink'); c.lineWidth = 2;
        c.strokeRect(cursor[0] * CELLV + 0.5, cursor[1] * CELLV + 0.5, CELLV - 1, CELLV - 1);
      }
      if (state) {
        var now = Date.now();
        state.robots.forEach(function (r) {
          if (r.call && r.call.open) drawRing(c, r.call.cell[0] * CELLV + CELLV / 2, r.call.cell[1] * CELLV + CELLV / 2, CELLV * 0.65, 0.6);
        });
        state.robots.forEach(function (r) {
          var k = robotKind(r.id), cx = r.x * CELLV + CELLV / 2, cy = r.y * CELLV + CELLV / 2;
          drawRobot(c, k, cx, cy, DISPLAY.indexOf(r.state) < 0 ? 'waiting' : r.state, k === 'agv' ? CELLV * 0.33 : CELLV * 0.3);
          if (flashUntil[r.id] > now) drawStar(c, cx, cy - CELLV * 0.45, CELLV * 0.55, css('--down'));
        });
        marks.forEach(function (m) {
          if (m.until > now) drawMark(c, m.cell[0] * CELLV + CELLV / 2, m.cell[1] * CELLV + CELLV / 2, m.verdict, CELLV * 0.9);
        });
      }
      refreshTip();
    }
    redrawHook = function () { drawLive(); };
    tipProvider = function (cx, cy) {
      var out = [];
      if (!state) return out;
      state.robots.forEach(function (r) {
        if (r.x === cx && r.y === cy) out.push({ id: r.id, kind: robotKind(r.id), raw: r.raw, disp: r.state, job: r.job, waitS: r.waiting_s });
      });
      return out;
    };
    wireTips(floorEl, function () { return G; });
    // a state document: a robot that is down now and was not down at the previous poll flashes for 1.5 s; the first time a
    // call id shows up graded right or wrong, its mark stays for 3 s
    // On the first poll, and on the first poll after an outage, only record what is there: no flash, no mark.
    function noteChanges(j, quiet) {
      var now = Date.now();
      j.robots.forEach(function (r) {
        if (!quiet && r.state === 'down' && prevDisp[r.id] !== undefined && prevDisp[r.id] !== 'down') {
          flashUntil[r.id] = now + 1500; setTimeout(drawLive, 1600);
        }
        prevDisp[r.id] = r.state;
        if (r.call && (r.call.verdict === 'confirmed' || r.call.verdict === 'refuted') && !marked[r.call.id]) {
          marked[r.call.id] = true;
          if (!quiet) marks.push({ cell: r.call.cell, verdict: r.call.verdict, until: now + 3000 });
          setTimeout(drawLive, 3100);
        }
      });
      marks = marks.filter(function (m) { return m.until > now; });
    }

    function render() {
      var s = state;
      counterDd[0].textContent = fmt(s.step);
      counterDd[1].textContent = s.sim_time || 'not started';
      counterDd[2].textContent = fmt(s.ledger.messages_emitted) + (s.ledger.expected_messages ? ' of ' + fmt(s.ledger.expected_messages) : '');
      counterDd[3].textContent = fmt(s.ledger.messages_parsed);
      counterDd[4].textContent = s.ledger.messages_rejected ? fmt(s.ledger.messages_rejected) : 'none rejected';
      counterDd[5].textContent = fmt(s.ledger.duplicates);
      counterDd[6].textContent = fmt(s.ledger.bytes_read) + ' B';
      counterDd[7].textContent = fmt(s.ledger.messages_per_s);
      counterDd[8].textContent = fmt(s.ledger.injections_posted) + ' / ' + fmt(s.ledger.injections_applied);
      counterDd[9].textContent = s.ledger.emit_status || 'starting';
      var exp = s.ledger.expected_messages;
      $('covbar').style.width = (exp ? Math.min(1, s.ledger.messages_emitted / exp) * 100 : 0) + '%';
      $('covlabel').textContent = exp ? 'Run progress ' + (100 * s.ledger.messages_emitted / exp).toFixed(0) + ' % of the messages this run will emit.' : '';
      $('match').textContent = 'Read straight from the run\'s files as they grow; nothing here is replayed.';
      var ol = $('top');
      ol.textContent = '';
      if (!s.top10.length) { var li0 = el('li', null, s.costmap ? 'the latest map flags no cell' : 'no map published yet'); li0.style.listStyle = 'none'; ol.appendChild(li0); }
      s.top10.forEach(function (r) { ol.appendChild(el('li', null, r.cell + '  cost ' + r.cost.toFixed(2) + (placed[r.cell] !== undefined ? '  [placed by you]' : ''))); });
      var g = s.grades;
      function line(label, o) { return label + ': ' + o.ok + ' held, ' + o.off + ' did not hold, ' + o.pending + ' pending, ' + o.not_gradable + ' not gradable'; }
      liveGrades.textContent = line('Cost-map calls', g.forecasts) + '. ' + line('Lessons', g.lessons) +
        '. Graded on what the robots report next (the stream), not on the hidden roadblocks.';
      $('lessonstate').textContent = s.lessons.length ? line('Graded so far', g.lessons) + '.' : 'No lessons yet. Rules need a few events in a closed time window.';
      var ul = $('lessons');
      ul.textContent = '';
      s.lessons.forEach(function (l) {
        var st = l.state === 'ok' ? 'ok' : (l.state === 'off' ? 'off' : 'pending');
        var li = el('li', 'les ' + st);
        li.appendChild(el('span', 'mark', l.state === 'ok' ? '✓ held' : l.state === 'off' ? '✗ did not hold' : l.state === 'not_gradable' ? 'not gradable' : 'pending'));
        li.appendChild(el('span', 'ltxt', l.text));
        li.appendChild(el('span', 'conf', 'zone ' + l.zone + ', rule ' + l.lesson_kind + ', support ' + l.confidence.toFixed(2) + ', drawn at ' + l.decided_at));
        ul.appendChild(li);
      });
      revealBox.hidden = s.truth === null;
      if (s.truth === null) { reveal = false; revealIn.checked = false; }
      floorEl.setAttribute('aria-label', 'Warehouse floor, step ' + s.step + ', ' + s.robots.length + ' robots, ' + Object.keys(s.costmap ? s.costmap.cells : {}).length + ' cells flagged. Press Enter on a highway cell to place a roadblock.');
      drawLive();
    }

    function setConnected(okNow, err) {
      // "Live" needs a reachable server AND a run that advances: a finished or stalled run is said so, with the step
      var key, cls, text, stale;
      if (okNow) {
        var status = state && state.ledger ? state.ledger.emit_status : null;
        if (status && status !== 'running') {
          key = 'over:' + status; cls = 'livebar bad'; stale = false;
          text = 'Run ' + status + ' at step ' + state.step + '. Nothing is advancing; the numbers below are final.';
        } else if (sameSteps >= 6) {
          key = 'stuck:' + state.step; cls = 'livebar bad'; stale = true;
          text = 'Connected to ' + base + ', but the run has not advanced past step ' + state.step + ' for ' + Math.round(sameSteps * POLL_MS / 1000) + ' s.';
        } else {
          key = 'ok'; cls = 'livebar'; stale = false;
          text = 'Live from ' + base + ', updated every ' + (POLL_MS / 1000) + ' s.';
        }
      } else {
        var age = lastOk ? Math.round((Date.now() - lastOk) / 1000) : null;
        key = 'bad:' + err + ':' + (age === null ? '' : Math.floor(age / 5)); cls = 'livebar bad'; stale = true;
        text = 'Disconnected from ' + base + ', retrying every ' + (POLL_MS / 1000) + ' s. ' +
          (age === null ? 'No data received yet.' : 'The numbers below are from ' + age + ' s ago and are not live.') + (err ? ' (' + err + ')' : '');
      }
      if (key === barKey) return; // do not rewrite the status region on every poll (screen readers re-announce it)
      barKey = key;
      bar.className = cls;
      bar.textContent = text;
      app.classList.toggle('stale', stale);
    }

    function poll() {
      if (inflight) return;
      inflight = true;
      var ctl = typeof AbortController === 'function' ? new AbortController() : null;
      var to = setTimeout(function () { if (ctl) ctl.abort(); }, 2000);
      httpGet(base + '/state', ctl ? { signal: ctl.signal } : {})
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (j) {
          sameSteps = lastStep !== null && j.step === lastStep ? sameSteps + 1 : 0;
          lastStep = j.step;
          noteChanges(j, state === null || failing > 0);
          state = j; failing = 0; lastOk = Date.now();
          setConnected(true);
          render();
        })
        .catch(function (e) { failing++; setConnected(false, e && e.message ? e.message : ''); })
        .then(function () { clearTimeout(to); inflight = false; });
    }

    function loadGrid() {
      httpGet(base + '/grid').then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (g) { G = g; drawLive(); })
        .catch(function () { setConnected(false, 'floor layout not available yet'); setTimeout(loadGrid, 1000); });
    }
    loadGrid();
    poll();
    setInterval(poll, POLL_MS);
    applyTheme();
  }
})();
