(function () {
  'use strict';
  var R = window.REPLAY;
  var $ = function (id) { return document.getElementById(id); };

  // ---- the words of the page ----
  // VISIBLE_COPY: every sentence the page writes into a visible element outside a closed details block (header strip, log
  // panel, the three sentences and the sparkline caption, the lines for the operators, the footer, live-mode messages). No
  // jargon: the banned-words test (fleet/tests/test_s8i_page.py) reads this table. {name} marks a value filled from data.js
  // or the live /state document; no number is typed here.
  const VISIBLE_COPY = {
    header: {
      replay: 'Simulated warehouse, {agvs} AGVs and {pickers} pickers, one {minutes}-minute shift, {messages} robot messages. We planted {floor} bad floor cells and {breakdowns}. The analyser was told none of it.',
      breakdownsNone: 'no breakdowns',
      breakdownsSome: '{n} breakdowns',
      breakdownsOne: '1 breakdown',
      live: 'Live: a fleet is running right now. Click a highway cell to put a roadblock there and watch the analyser find it. So far {messages} robot messages read. Roadblocks placed by you: {placed}{planted}.',
      livePlanted: ', planted by us: {n}'
    },
    floor: {
      noMap: 'The analyser drew no map in this run.',
      mapLater: 'No map yet (the first one appears at {time}).',
      withMap: 'Second run with the map switched on: the red shading belongs to the first run and is hidden, the stuck-call rings come from the analyser on this run.',
      calls: 'Stuck calls so far: {n}; still open {open}; judged right {right}, wrong {wrong}; no verdict {none}.',
      drawError: 'The page hit an error while drawing: {why}',
      summary: 'Step {step} of {last}, fleet time {time}. Robots: {robots}. Log: {usable} usable, {rejected} rejected, {dups} duplicates. {map}',
      summaryMap: 'Latest map at {time}, right {p} of the time.',
      summaryNoMap: 'No map yet.',
      announce: 'Step {step} of {last}, fleet time {time}. Robots: {robots}.',
      scrub: 'step {step} of {last}, fleet time {time}',
      withMapNote: 'With map: {note} Alpha {alpha}, {deliveries} deliveries (pick rate {rate} per hour) in this second run.'
    },
    log: {
      arrivedUnit: 'messages, {size}',
      rate: '{rate} msgs/s',
      replayed: 'replayed from file',
      lag: '{lag} s behind the robots',
      usableUnit: 'messages parsed and valid',
      setAside: 'set aside: rejected {r} (malformed), duplicates {d}; nothing is dropped silently, every rejected line is stored with its reason',
      keptUnit: 'of bytes, 100% of the events that matter',
      keptLater: 'measured on a finished shift',
      nothingLost: 'nothing lost: {c} of what the robots sent is accounted for',
      caughtUp: 'caught up: {c} of what the robots have sent so far is read',
      unknown: 'Not known: this run has no message count of its own.'
    },
    analyser: {
      none: '—',
      noMap: 'no map yet',
      needTruth: 'start live with the reveal switch to score the map',
      spark: 'Right-rate after each new map: {list}',
      sparkNone: 'No map yet.'
    },
    lesson: {
      hot_cell: 'One spot on the floor keeps holding robots up. Worth a look.',
      hot_robot: 'One robot gets stuck far more often than the others.',
      recurring_pair: "Two robots keep getting in each other's way.",
      fallback: "A pattern in the robots' waiting times.",
      support: 'support {c}',
      held: 'held up',
      failed: 'did not hold',
      none: 'Nothing to report yet.',
      noData: 'Lesson data is not included in this file.'
    },
    footer: {
      payoff: 'Routing payoff measured separately: {map} of the sticky-floor loss recovered, {oracle} with perfect knowledge ({source}).'
    },
    live: {
      ignored: 'The live parameter was ignored: it must be an http URL on localhost or 127.0.0.1 (the page sends injections to it). Showing the offline replay.',
      connecting: 'Connecting to {base} ...',
      over: 'Run {status} at step {step}. Nothing is advancing; the numbers below are final.',
      stuck: 'Connected to {base}, but the run has not advanced past step {step} for {secs} s.',
      ok: 'Live from {base}, updated every {every} s.',
      lost: 'Disconnected from {base}, retrying every {every} s. {age}{err}',
      lostNever: 'No data received yet.',
      lostAge: 'The numbers below are from {s} s ago and are not live.',
      aria: 'Warehouse floor. Click or press Enter on a highway cell to place a roadblock; arrow keys move the cursor.',
      ariaNow: 'Warehouse floor, step {step}, {robots} robots, {cells} cells flagged. Press Enter on a highway cell to place a roadblock.',
      placedBy: 'placed by you (outlined roadblocks)',
      reveal: ' Reveal the hidden roadblocks',
      promptLabel: 'Roadblock at {cell}, chance a robot is stopped: ',
      promptRange: 'Chance that a robot is stopped when it tries to enter the cell',
      promptDialog: 'Place a roadblock',
      place: 'Place',
      cancel: 'Cancel',
      placed: 'Roadblock placed at {cell} (p {p}). It starts at step {step}. The cell turns red when the analyser flags it.',
      notPlaced: 'Not placed: {why}.',
      serverNo: 'the server said no',
      unreachable: 'Not placed: the live server is not reachable.',
      cannot: 'Cannot place at {cell}: {why}.',
      outside: 'outside the floor',
      shelf: 'a shelf cell: roadblocks go on highway cells only',
      goal: 'a goal cell: roadblocks go on plain highway cells only',
      cellHere: 'Cell {cell}: {why}',
      cellClick: 'Click to place a roadblock at {cell}',
      cellKey: 'Cell {cell}: highway, press Enter to place a roadblock',
      noGrid: 'floor layout not available yet',
      noLessons: 'No lessons yet. Rules need a few events in a closed time window.',
      notStarted: 'not started'
    }
  };

  // HOVER_COPY: text that appears only on hover, focus or tap (technical wording allowed). Written by showHover/setHover into
  // the small tip box, never into a visible element.
  const HOVER_COPY = {
    raw: { moving: 'changed cell', loading: 'at a shelf or station', stalled: 'tried to move and did not',
           stuck: 'inside a stuck call', frozen: 'reported an error', idle: 'no job, not moving' },
    arrived: 'Lines read from the robots\' files so far: {lines}, {bytes} B uncompressed. Ingest speed {rate} (store:ingest_ledger).{bench}',
    arrivedBench: ' Pipeline benchmark: {rate} msgs/s ({source}).',
    arrivedLive: 'Lines read from the robots\' files so far: {lines}, {bytes} B uncompressed. Speed measured from the last polls of /state (ledger.messages_per_s). Behind the robots: ledger.steps_done minus the newest step read, times 5 s.',
    usable: 'Parsed and valid: {accepted}. Rejected {rejected}{reasons}. Duplicates {dups}. Sequence gaps {gaps}, {missing} message numbers not seen.{gapnote}',
    usableLive: 'Parsed and valid: {accepted}. Rejected {rejected}. Duplicates {dups}. Counted from the files as they grow.',
    gapNote: ' A jump in message numbers, nothing missing: the emitter skipped {ids} ids on purpose (demo noise), every message is still counted.',
    kept: 'Kept {kept} B of {arrived} B that arrived = {pct}%. Scope: the whole run (zones in the run: {zones}), not only the shift shown. By table: {tables}. Formula: {formula} Source: {source}.',
    keptNone: 'No kept figure: the store has no ingest ledger for this run.',
    right: 'Of the 20 cells flagged most strongly, how many sit on a planted bad cell. Per map: {list}.',
    rightLive: 'Of the 20 cells flagged most strongly, how many sit on a revealed roadblock. Scored only while the hidden layout is revealed.',
    found: '{share} of the planted cells saw no stall at all in this shift (run_constants.hotspot.zero_stall_share, {source}). Recall at k = {k}: {recall}.',
    foundLive: 'Revealed roadblocks that are among the most strongly flagged cells (as many cells as there are roadblocks).',
    checks: '{calls} calls were made by this map. {hits} sit on a planted bad cell (truth grade), {wrong} do not.{outcome}',
    checksOutcome: ' {label}: {ok} {okText}, {off} {offText}.',
    checksLive: 'Map calls graded on what the robots report next, not on the hidden roadblocks: {ok} held, {off} did not hold, {pending} pending, {na} not gradable.',
    lessonCap: 'Lessons come from fixed rules over stall and stuck counts, no model and no learning. They were written on run {run} (same seed and floor, without log noise) and carried into this file.',
    lessonCapOwn: 'Lessons come from fixed rules over stall and stuck counts, no model and no learning, written on this run.',
    lessonLine: 'Original text: {text}\nKind {kind}, zone {zone}, support {c}, drawn at {drawn}, {verdict}.{origin}',
    lessonLineLive: 'Original text: {text}\nKind {kind}, zone {zone}, support {c}, drawn at {drawn}, {verdict}.',
    keptLive: 'The kept share is measured on a finished shift: bytes stored divided by bytes that arrived.',
    liveVerdict: { ok: 'verdict: held', off: 'verdict: did not hold', pending: 'not graded yet', not_gradable: 'not gradable (the shift ends before the next window)' },
    verdictOpen: 'not graded yet',
    verdictNa: 'not gradable (the shift ends before the next window)',
    verdictOk: 'verdict: held, graded at {t}',
    verdictOff: 'verdict: did not hold, graded at {t}',
    origin: ' Written on run {run}.',
    close: 'Press Escape to close.'
  };

  // DETAILS_COPY: text inside the closed details blocks (panel 2 counters, panel 3 details, footer sources). Technical wording
  // is fine here; the blocks carry data-details and are closed until the reader opens them.
  const DETAILS_COPY = {
    counterRows: ['bytes read (uncompressed)', 'messages (lines)', 'parsed', 'rejected', 'duplicates', 'sequence gaps', 'accepted',
                  'coverage'],
    noneRejected: 'none rejected',
    topReason: ' ({r})',
    gaps: '{n} ({m} messages missing)',
    coverageUnknown: 'unknown (no message count from the run)',
    matchYes: 'The replay matches the import step\'s checkpoint: {bytes} bytes, {parsed} parsed, {accepted} accepted, {rejected} rejected, {dups} duplicates, {gaps} sequence gaps.',
    matchNo: 'The store has no import checkpoint for this file, so the replay could not be compared with it.',
    liveRows: ['step', 'fleet time', 'messages emitted', 'messages read (parsed)', 'rejected', 'duplicates', 'bytes read', 'messages per second',
               'roadblocks placed / applied', 'emitter'],
    liveMatch: 'Read straight from the run\'s files as they grow; nothing here is replayed.',
    liveExpected: ' of {n}',
    wording: {
      rank: { lab: 'rank grade', ok: 'still in top 20 after the horizon', off: 'dropped out' },
      count: { lab: 'count grade', ok: 'stall count about as claimed', off: 'stall count off' },
      other: { lab: 'outcome grade', ok: 'outcome as claimed', off: 'outcome not as claimed' }
    },
    truthLab: 'truth grade',
    onHidden: 'on a hidden problem',
    notOnHidden: 'not on one',
    openPending: 'open or pending',
    noMapGrade: 'No map published yet, so nothing to grade.',
    noPublish: 'No publishes, so nothing to grade.',
    noMapTop: 'no map published yet',
    noFlag: 'the latest map flags no cell',
    pubName: 'Publish at {time}: {calls} calls, top-20 hit rate {p} ({hits}/20)',
    outcomeLine: '{ok} {okText}, {off} {offText}',
    openLine: '{n} open: the horizon ends after the stream',
    knownAt: 'outcome known at {time}',
    truthLine: '{hit} on a hidden problem, {fa} not on one',
    topLine: '{cell}  cost {cost}  stalls {stalls}{flag}',
    topFlagYes: '  [on a hidden problem]',
    topFlagNo: '  [not on one]',
    topLive: '{cell}  cost {cost}{flag}',
    topLiveMine: '  [placed by you]',
    notes: ['Top-20 hit rate: of the 20 most-flagged cells, how many sit on a hidden floor problem.',
            'The map is rules plus a decayed count of stalls per cell, and nothing is trained.',
            'Every call is graded afterwards, the count and rank grades against what happened next and the truth grade against the hidden layout, which the analyser never reads.',
            'Cells nobody drives over cannot be found, because a stall needs a robot to try to enter the cell.'],
    liveLine: '{label}: {ok} held, {off} did not hold, {pending} pending, {na} not gradable',
    liveCalls: 'Cost-map calls',
    liveLessons: 'Lessons',
    liveGradedOn: 'Graded on what the robots report next (the stream), not on the hidden roadblocks.',
    sources: { runDir: 'run files: {v}', store: 'store: {v}', closedLoop: 'closed-loop layer: {v}', costmap: 'map file: {v}',
               carry: 'lessons carried from: {v} (written on run {run})', constant: '{k}: {v}' }
  };

  function fill(tpl, vars) {
    var out = tpl;
    Object.keys(vars).forEach(function (k) { out = out.split('{' + k + '}').join(String(vars[k])); });
    return out;
  }
  function pct(x) {
    var v = x * 100;
    return (v === 0 || v >= 10 ? String(Math.round(v)) : v.toFixed(1)) + '%';
  }
  function human(n) {
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1048576).toFixed(1) + ' MB';
  }

  // ---- hover: a tip box for focus, hover and tap (the title attribute is only the native fallback) ----
  var hoverText = {}, hoverFor = null;
  function placeTip(tip, anchor) {
    var r = anchor.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
    var below = r.bottom + 6 + h <= window.innerHeight;
    tip.style.left = Math.max(4, Math.min(window.innerWidth - w - 4, r.left)) + 'px';
    tip.style.top = Math.max(4, below ? r.bottom + 6 : r.top - h - 6) + 'px';
  }
  function showHover(node) {
    var text = hoverText[node.id];
    var tip = $('htip');
    if (!text) { tip.hidden = true; hoverFor = null; return; }
    tip.textContent = text + '\n' + HOVER_COPY.close;
    tip.hidden = false;
    hoverFor = node.id;
    placeTip(tip, node);
  }
  function hideHover() { $('htip').hidden = true; hoverFor = null; }
  function setHover(id, text) {
    if (hoverText[id] === text && $(id + '-d')) return; // unchanged: replay redraws every frame
    hoverText[id] = text;
    var node = $(id);
    if (!node) return;
    var d = $(id + '-d');
    if (!d) {
      d = document.createElement('span');
      d.id = id + '-d'; d.className = 'sr';
      node.appendChild(d);
      node.setAttribute('aria-describedby', d.id);
    }
    d.textContent = text;
    if (hoverFor === id) showHover(node);
  }
  function wireOne(n) {
    n.addEventListener('pointerenter', function (ev) { if (ev.pointerType !== 'touch') showHover(n); });
    n.addEventListener('pointerleave', function (ev) { if (ev.pointerType !== 'touch') hideHover(); });
    n.addEventListener('focus', function () { showHover(n); });
    n.addEventListener('blur', hideHover);
    n.addEventListener('click', function () { if (hoverFor === n.id && !$('htip').hidden) hideHover(); else showHover(n); });
    n.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') hideHover(); });
  }
  Array.prototype.forEach.call(document.querySelectorAll('[data-hover]'), wireOne);
  document.addEventListener('pointerdown', function (ev) {
    if (!ev.target.closest || !ev.target.closest('[data-hover]')) hideHover();
  });
  window.addEventListener('scroll', hideHover, { passive: true });


  // ---- shared painters (replay and live): header strip, panel 2, panel 3, panel 4, footer ----
  // The replay adapters (replayLog, replayAnalyser, replayLessons) and the live adapters (liveLog, liveAnalyser, liveLessons)
  // build the view objects these take, so both modes write exactly the same elements with exactly the same words.
  function setText(id, text) { var n = $(id); if (n) n.textContent = text; }
  var DASH = VISIBLE_COPY.analyser.none;
  var LESSON_KINDS = ['hot_cell', 'hot_robot', 'recurring_pair'];

  function paintHeader(text) { setText('subtitle', text); }

  // v = { lines, bytes, rate|null, lag|null, live, usable, rejected, dups, kept (percent 0-100)|null, cov (0-1)|null,
  //       hover: { arrived, usable, kept } }
  function paintLog(v) {
    setText('big-arrived', fmt(v.lines));
    setText('arrived-unit', fill(VISIBLE_COPY.log.arrivedUnit, { size: human(v.bytes) }));
    var parts = [];
    if (v.rate !== null) parts.push(fill(VISIBLE_COPY.log.rate, { rate: fmt(Math.round(v.rate)) }));
    if (!v.live) parts.push(VISIBLE_COPY.log.replayed);
    else if (v.lag !== null) parts.push(fill(VISIBLE_COPY.log.lag, { lag: fmt(v.lag) }));
    setText('arrived-rate', parts.join(', '));
    setText('big-usable', fmt(v.usable));
    setText('usable-unit', VISIBLE_COPY.log.usableUnit);
    setText('usable-aside', fill(VISIBLE_COPY.log.setAside, { r: pct(v.lines ? v.rejected / v.lines : 0), d: pct(v.lines ? v.dups / v.lines : 0) }));
    setText('big-kept', v.kept === null ? DASH : pct(v.kept / 100));
    setText('kept-unit', v.kept === null ? VISIBLE_COPY.log.keptLater : VISIBLE_COPY.log.keptUnit);
    var cov = $('covbar');
    if (cov) cov.style.width = (v.cov === null ? 0 : Math.min(1, v.cov) * 100) + '%';
    setText('covlabel', v.cov === null ? VISIBLE_COPY.log.unknown
      : fill(v.live ? VISIBLE_COPY.log.caughtUp : VISIBLE_COPY.log.nothingLost, { c: (Math.floor(Math.min(1, v.cov) * 1000) / 10) + '%' }));
    setHover('f-arrived', v.hover.arrived);
    setHover('f-usable', v.hover.usable);
    setHover('f-kept', v.hover.kept);
  }

  // v = { right|null, found|null, calls|null, hits|null, wrong|null, series: [{x (0-1), p}], hover: { right, found, checks } }
  function paintAnalyser(v) {
    function put(id, x, fmtFn) { setText(id, x === null ? DASH : fmtFn(x)); }
    put('big-right', v.right, pct);
    put('big-found', v.found, pct);
    put('big-calls', v.calls, fmt);
    put('big-hits', v.hits, fmt);
    put('big-wrong', v.wrong, fmt);
    setText('nomap', v.note || '');
    setHover('s-right', v.hover.right);
    setHover('s-found', v.hover.found);
    setHover('s-checks', v.hover.checks);
    drawSpark(v.series);
  }

  var sparkSig = null;
  function drawSpark(series) {
    var cv = $('spark');
    if (!cv) return;
    var d = Math.max(1, window.devicePixelRatio || 1), W = 300, H = 70;
    var sig = JSON.stringify([series, d, css('--accent'), css('--ink')]);
    if (sig === sparkSig) return;
    sparkSig = sig;
    cv.width = Math.round(W * d); cv.height = Math.round(H * d); cv.style.width = W + 'px';
    var c = cv.getContext('2d');
    c.setTransform(d, 0, 0, d, 0, 0);
    c.clearRect(0, 0, W, H);
    var padL = 8, padR = 44, padT = 8, padB = 8, w = W - padL - padR, h = H - padT - padB;
    function px(x) { return padL + x * w; }
    function py(p) { return padT + (1 - p) * h; }
    c.strokeStyle = css('--line'); c.lineWidth = 1;
    [0, 1].forEach(function (g) { c.beginPath(); c.moveTo(padL, py(g)); c.lineTo(padL + w, py(g)); c.stroke(); });
    cv.setAttribute('aria-label', series.length ? fill(VISIBLE_COPY.analyser.spark, { list: series.map(function (s) { return pct(s.p); }).join(', ') })
      : VISIBLE_COPY.analyser.sparkNone);
    if (!series.length) return;
    c.strokeStyle = css('--accent'); c.lineWidth = 2.5;
    c.beginPath();
    series.forEach(function (s, i) { c[i ? 'lineTo' : 'moveTo'](px(s.x), py(s.p)); });
    c.stroke();
    series.forEach(function (s) { c.beginPath(); c.arc(px(s.x), py(s.p), 4, 0, 6.2832); c.fillStyle = css('--accent'); c.fill(); c.lineWidth = 1.5; c.strokeStyle = css('--panel'); c.stroke(); });
    var last = series[series.length - 1];
    c.fillStyle = css('--ink'); c.font = '600 13px system-ui, sans-serif'; c.textAlign = 'left'; c.textBaseline = 'middle';
    c.fillText(pct(last.p), px(last.x) + 9, py(last.p));
  }

  var lessonSig = null;
  // items = [{ kind, conf, mark: 'ok' | 'off' | null, hover }] newest first, already cut to five
  function paintLessons(items, emptyText) {
    var sig = JSON.stringify([items, emptyText]);
    if (sig === lessonSig) return;
    lessonSig = sig;
    var ul = $('lessons');
    ul.textContent = '';
    setText('lessonstate', items.length ? '' : emptyText);
    items.forEach(function (it, i) {
      var li = el('li', 'les ' + (it.mark || 'pending'));
      var text = LESSON_KINDS.indexOf(it.kind) >= 0 ? VISIBLE_COPY.lesson[it.kind] : VISIBLE_COPY.lesson.fallback;
      li.appendChild(el('span', 'ltxt', text));
      var conf = el('span', 'conf', fill(VISIBLE_COPY.lesson.support, { c: it.conf.toFixed(2) }));
      if (it.mark) {
        var mark = el('span', 'mark', it.mark === 'ok' ? ' ✓' : ' ✗');
        mark.setAttribute('role', 'img');
        mark.setAttribute('aria-label', it.mark === 'ok' ? VISIBLE_COPY.lesson.held : VISIBLE_COPY.lesson.failed);
        conf.appendChild(mark);
      }
      li.appendChild(conf);
      li.id = 'les-' + i;
      li.tabIndex = 0;
      li.setAttribute('data-hover', '');
      wireOne(li);
      ul.appendChild(li);
      setHover(li.id, it.hover);
    });
  }

  function paintFooter() {
    var rc = (R && R.run_constants) || {}, src = (R && R.meta && R.meta.source) || {};
    var cl = rc.closed_loop;
    setText('payoff', cl ? fill(VISIBLE_COPY.footer.payoff, { map: pct(cl.map_share), oracle: pct(cl.oracle_share), source: cl.source }) : '');
    var ul = $('sources');
    if (!ul) return;
    ul.textContent = '';
    var D = DETAILS_COPY.sources;
    [['runDir', src.run_dir], ['store', src.store], ['closedLoop', src.closed_loop], ['costmap', src.costmap]].forEach(function (p) {
      if (p[1]) ul.appendChild(el('li', null, fill(D[p[0]], { v: p[1] })));
    });
    if (src.carry_lessons) ul.appendChild(el('li', null, fill(D.carry, { v: src.carry_lessons, run: src.carry_lessons_run })));
    Object.keys(rc).forEach(function (k) {
      if (rc[k] && rc[k].source) ul.appendChild(el('li', null, fill(D.constant, { k: k, v: rc[k].source })));
    });
  }
  paintFooter();
  (function lessonCaption() {
    var run = R && R.meta && R.meta.source && R.meta.source.carry_lessons_run;
    setHover('lessoncap', run ? fill(HOVER_COPY.lessonCap, { run: run }) : HOVER_COPY.lessonCapOwn);
  })();

  // the ten most suspected cells, numbered 1 to 10 in the top-left corner of the cell (floor canvas, replay and live)
  function drawTopLabels(c, cells, size) {
    c.save();
    c.font = 'bold 11px system-ui, sans-serif'; c.textAlign = 'left'; c.textBaseline = 'top';
    cells.forEach(function (key, i) {
      var xy = key.split(','), x = +xy[0] * size + 2, y = +xy[1] * size + 1;
      c.lineWidth = 3; c.strokeStyle = css('--bg'); c.strokeText(String(i + 1), x, y);
      c.fillStyle = css('--ink'); c.fillText(String(i + 1), x, y);
    });
    c.restore();
  }


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
  var RAW_TEXT = HOVER_COPY.raw;
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
    } else if (ico === 'top') {
      c.fillStyle = css('--hw'); c.fillRect(2, 2, 20, 20);
      c.font = 'bold 13px system-ui, sans-serif'; c.textAlign = 'center'; c.textBaseline = 'middle';
      c.lineWidth = 3; c.strokeStyle = css('--bg'); c.strokeText('1', 12, 12);
      c.fillStyle = css('--ink'); c.fillText('1', 12, 12);
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
    bad.textContent = VISIBLE_COPY.live.ignored;
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
  var dpr = Math.max(1, window.devicePixelRatio || 1);
  // Only the CSS width is set; height:auto keeps the aspect ratio of the width/height attributes.
  function size(canvas, ctx, w, h) {
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    canvas.style.width = w + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  function sizeAll() {
    dpr = Math.max(1, window.devicePixelRatio || 1);
    size(floor, fctx, G.width * CELL, G.height * CELL);
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
    // the ten most suspected cells of the latest map, numbered 1 to 10 in the top-left corner of the cell
    if (pub) drawTopLabels(c, pub.cells.slice(0, 10).map(function (r) { return r[0]; }), CELL);
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

  // ---- the header strip (replay) ----
  var X = R.extractor, S = X.series, T = X.totals;
  var RC = R.run_constants || {}, SRC = M.source || {};
  function replayHeaderText() {
    var floorN = R.obstacles.filter(function (o) { return o.kind === 'floor'; }).length;
    var brk = R.obstacles.filter(function (o) { return o.kind === 'breakdown'; }).length;
    var H = VISIBLE_COPY.header;
    var agvs = R.robots.filter(function (r) { return r.kind === 'agv'; }).length;
    return fill(H.replay, { agvs: agvs, pickers: R.robots.length - agvs, minutes: Math.round(STEPS * SEC / 60),
      messages: fmt(T.expected_messages || T.messages), floor: floorN,
      breakdowns: brk === 0 ? H.breakdownsNone : (brk === 1 ? H.breakdownsOne : fill(H.breakdownsSome, { n: brk })) });
  }

  // ---- panel 2: the log (replay adapter) ----
  var counterEls = DETAILS_COPY.counterRows.map(function (label) {
    var dt = el('dt', null, label), dd = el('dd', null, '');
    $('counters').appendChild(dt); $('counters').appendChild(dd);
    return dd;
  });
  (function () {
    var chk = X.check;
    $('match').textContent = chk
      ? fill(DETAILS_COPY.matchYes, { bytes: fmt(T.bytes), parsed: fmt(chk.messages_parsed), accepted: fmt(chk.messages_accepted),
          rejected: fmt(chk.messages_rejected), dups: fmt(chk.duplicates), gaps: fmt(chk.sequence_gaps) })
      : DETAILS_COPY.matchNo;
  })();
  function reasonList(i) {
    var parts = [];
    Object.keys(S.rejected_by_reason).forEach(function (k) { var v = S.rejected_by_reason[k][i]; if (v) parts.push(k + ' ' + v); });
    return parts.join(', ');
  }
  // accounted for = accepted / sent so far, the share of the run's expected messages that the clock has reached by step i
  function sentSoFar(i) {
    if (!T.expected_messages) return null;
    return S.accepted[i] / (T.expected_messages * (i + 1) / STEPS);
  }
  function replayLog(i) {
    var rate = RC.ingest_msgs_per_s ? RC.ingest_msgs_per_s.value : null;
    var bench = RC.benchmark_msgs_per_s;
    var kept = RC.kept;
    var noise = SRC.injected_noise;
    var arrived = fill(HOVER_COPY.arrived, { lines: fmt(S.messages[i]), bytes: fmt(S.bytes[i]),
      rate: rate === null ? 'unknown' : fmt(Math.round(rate)) + ' msgs/s',
      bench: bench ? fill(HOVER_COPY.arrivedBench, { rate: fmt(Math.round(bench.value)), source: bench.source }) : '' });
    var usable = fill(HOVER_COPY.usable, { accepted: fmt(S.accepted[i]), rejected: fmt(S.rejected[i]), reasons: reasonList(i) ? ' (' + reasonList(i) + ')' : '',
      dups: fmt(S.duplicates[i]), gaps: fmt(S.sequence_gaps[i]), missing: fmt(S.missing_messages[i]),
      gapnote: noise && noise.gap_ids && S.sequence_gaps[i] ? fill(HOVER_COPY.gapNote, { ids: noise.gap_ids }) : '' });
    var keptHover = kept ? fill(HOVER_COPY.kept, { kept: fmt(kept.bytes_kept), arrived: fmt(kept.bytes_arrived), pct: kept.kept_pct.toFixed(2),
      zones: kept.n_zones, tables: Object.keys(kept.bytes_by_table).map(function (k) { return k + ' ' + fmt(kept.bytes_by_table[k]); }).join(', '),
      formula: kept.formula, source: kept.source }) : HOVER_COPY.keptNone;
    return { lines: S.messages[i], bytes: S.bytes[i], rate: rate, lag: null, live: false, usable: S.accepted[i], rejected: S.rejected[i],
      dups: S.duplicates[i], kept: kept ? kept.kept_pct : null, cov: sentSoFar(i), hover: { arrived: arrived, usable: usable, kept: keptHover } };
  }
  function drawLog(step) {
    paintLog(replayLog(step));
    var rows = [
      fmt(S.bytes[step]) + ' B', fmt(S.messages[step]), fmt(S.parsed[step]),
      S.rejected[step] ? fmt(S.rejected[step]) + fill(DETAILS_COPY.topReason, { r: reasonList(step) }) : DETAILS_COPY.noneRejected,
      fmt(S.duplicates[step]), fill(DETAILS_COPY.gaps, { n: fmt(S.sequence_gaps[step]), m: fmt(S.missing_messages[step]) }), fmt(S.accepted[step]),
      S.coverage[step] === null ? DETAILS_COPY.coverageUnknown : (S.coverage[step] * 100).toFixed(1) + ' %'
    ];
    rows.forEach(function (t, k) { counterEls[k].textContent = t; });
  }

  // ---- panel 3: the analyser (replay adapter) ----
  var GRADES = R.grades.per_publish;
  function wording(kind) {
    var w = DETAILS_COPY.wording;
    return kind === 'rank' ? w.rank : (kind === 'count' ? w.count : w.other);
  }
  function replayAnalyser(step) {
    var lp = latestPublish(step), idx = pubs.indexOf(lp), g = lp ? GRADES[idx] : null;
    var shown = pubs.filter(function (p) { return p.step <= step; });
    var hot = RC.hotspot;
    var list = shown.map(function (p) { return clock(p.step) + ' ' + pct(p.precision_at_20) + ' (' + p.hits_at_20 + '/20)'; }).join('; ');
    var outcome = '';
    if (g && g.window_end_step !== null && g.window_end_step <= step) {
      [[g.outcome_kind, g.outcome], ['count', g.outcome_count]].forEach(function (pair, k) {
        if (k && g.outcome_kind === 'count') return;
        var w = wording(pair[0]);
        if (pair[1].ok + pair[1].off > 0) outcome += fill(HOVER_COPY.checksOutcome, { label: w.lab, ok: pair[1].ok, okText: w.ok, off: pair[1].off, offText: w.off });
      });
    }
    return {
      right: lp ? lp.precision_at_20 : null,
      found: lp && typeof lp.recall_at_k === 'number' ? lp.recall_at_k : null,
      calls: g ? g.forecasts : null, hits: g ? g.truth.hit : null, wrong: g ? g.truth.false_alarm : null,
      note: lp ? '' : (pubs.length ? fill(VISIBLE_COPY.floor.mapLater, { time: clock(pubs[0].step) }) : VISIBLE_COPY.analyser.noMap),
      series: shown.map(function (p) { return { x: p.step / Math.max(1, STEPS - 1), p: p.precision_at_20 }; }),
      hover: {
        right: lp ? fill(HOVER_COPY.right, { list: list }) : '',
        found: lp && hot ? fill(HOVER_COPY.found, { share: pct(hot.zero_stall_share), source: hot.source, k: hot.k, recall: pct(hot.recall_at_k) }) : '',
        checks: g ? fill(HOVER_COPY.checks, { calls: g.forecasts, hits: g.truth.hit, wrong: g.truth.false_alarm, outcome: outcome }) : ''
      }
    };
  }
  var gradeKey = null;
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
    oks.push(DETAILS_COPY.onHidden); offs.push(DETAILS_COPY.notOnHidden);
    legendItem(g, 'var(--ok)', oks.join(' / '));
    legendItem(g, 'var(--off)', offs.join(' / '));
    legendItem(g, 'var(--open)', DETAILS_COPY.openPending);
  }
  function drawGrades(step) {
    var shown = pubs.filter(function (p) { return p.step <= step; });
    var graded = shown.map(function (p) { return GRADES[pubs.indexOf(p)]; });
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
    if (!pubs.length) { host.appendChild(el('p', 'state', DETAILS_COPY.noPublish)); return; }
    if (!shown.length) { host.appendChild(el('p', 'state', DETAILS_COPY.noMapGrade)); return; }
    graded.forEach(function (g) {
      var box = el('div', 'pub');
      var pr = pubs[GRADES.indexOf(g)];
      box.appendChild(el('div', 'name', fill(DETAILS_COPY.pubName, { time: clockAt(g.t), calls: g.forecasts, p: pr.precision_at_20.toFixed(2), hits: pr.hits_at_20 })));
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
      r2.appendChild(el('span', 'lab', DETAILS_COPY.truthLab));
      var b2 = el('div', 'bar');
      b2.setAttribute('aria-hidden', 'true');
      seg(b2, g.truth.hit, g.forecasts, 'var(--ok)');
      seg(b2, g.truth.false_alarm, g.forecasts, 'var(--off)');
      r2.appendChild(b2); box.appendChild(r2);
      var t = el('div', 'cap small');
      var parts = [];
      if (outcomeKnown) {
        parts.push(fill(DETAILS_COPY.outcomeLine, { ok: g.outcome.ok, okText: w.ok, off: g.outcome.off, offText: w.off }));
      } else if (g.window_end_step === null) {
        parts.push(fill(DETAILS_COPY.openLine, { n: g.open }));
      } else {
        parts.push(fill(DETAILS_COPY.knownAt, { time: clock(g.window_end_step) }));
      }
      parts.push(fill(DETAILS_COPY.truthLine, { hit: g.truth.hit, fa: g.truth.false_alarm }));
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
    if (!p) { var li = el('li', null, DETAILS_COPY.noMapTop); li.style.listStyle = 'none'; ol.appendChild(li); return; }
    p.cells.slice(0, 10).forEach(function (r) {
      ol.appendChild(el('li', null, fill(DETAILS_COPY.topLine, { cell: r[0], cost: r[1].toFixed(2), stalls: r[2],
        flag: obstacleSet[r[0]] ? DETAILS_COPY.topFlagYes : DETAILS_COPY.topFlagNo })));
    });
  }
  $('detail-notes').textContent = DETAILS_COPY.notes.join(' ');

  // ---- panel 4: lines for the operators (replay adapter) ----
  var HAS_LESSONS = R.lessons !== undefined;
  var LESSONS = R.lessons || [];
  function replayLessons(step) {
    if (!HAS_LESSONS) return { items: [], empty: VISIBLE_COPY.lesson.noData };
    var shown = LESSONS.filter(function (l) { return l.decided_at_step <= step; }).slice().reverse().slice(0, 5);
    var items = shown.map(function (l) {
      var known = l.graded_at_step !== null && l.graded_at_step <= step;
      var verdict = known ? fill(l.verdict === 'ok' ? HOVER_COPY.verdictOk : HOVER_COPY.verdictOff, { t: clock(l.graded_at_step) })
        : (l.graded_at_step === null ? HOVER_COPY.verdictNa : HOVER_COPY.verdictOpen);
      return { kind: l.lesson_kind, conf: l.confidence, mark: known ? (l.verdict === 'ok' ? 'ok' : 'off') : null,
        hover: fill(HOVER_COPY.lessonLine, { text: l.text, kind: l.lesson_kind, zone: l.zone, c: l.confidence.toFixed(2), drawn: clock(l.decided_at_step),
          verdict: verdict, origin: SRC.carry_lessons_run ? fill(HOVER_COPY.origin, { run: SRC.carry_lessons_run }) : '' }) };
    });
    return { items: items, empty: VISIBLE_COPY.lesson.none };
  }
  function drawLessons(step) {
    var v = replayLessons(step);
    paintLessons(v.items, v.empty);
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
    return fill(VISIBLE_COPY.floor.calls, { n: n, open: open, right: right, wrong: wrong, none: n - open - right - wrong });
  }
  function mapState(step) {
    var st = $('mapstate'), t;
    if (layer === 'with') t = VISIBLE_COPY.floor.withMap;
    else if (!pubs.length) t = VISIBLE_COPY.floor.noMap;
    else if (!latestPublish(step)) t = fill(VISIBLE_COPY.floor.mapLater, { time: clock(pubs[0].step) });
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
    return fill(VISIBLE_COPY.floor.summary, { step: step, last: STEPS - 1, time: clock(step), robots: counts(step), usable: fmt(S.accepted[step]),
      rejected: fmt(S.rejected[step]), dups: fmt(S.duplicates[step]),
      map: pub ? fill(VISIBLE_COPY.floor.summaryMap, { time: clock(pub.step), p: pct(pub.precision_at_20) }) : VISIBLE_COPY.floor.summaryNoMap });
  }
  function curStep() { return Math.min(STEPS - 1, Math.max(0, Math.floor(pos))); }
  // The live region is written only when playback is not running: on pause, on a step, after a scrub settles.
  function announce() {
    if (playing) return;
    var step = curStep();
    $('live').textContent = fill(VISIBLE_COPY.floor.announce, { step: step, last: STEPS - 1, time: clock(step), robots: counts(step) });
  }

  // ---- main draw ----
  function draw() {
    var step = curStep();
    drawFloor(step); drawLog(step); paintAnalyser(replayAnalyser(step)); drawGrades(step); drawTop(step); drawLessons(step); mapState(step);
    $('clock').textContent = 'step ' + step + ' / ' + (STEPS - 1) + '  ' + clock(step);
    var sc = $('scrub');
    sc.value = step;
    sc.setAttribute('aria-valuetext', fill(VISIBLE_COPY.floor.scrub, { step: step, last: STEPS - 1, time: clock(step) }));
    var now = performance.now();
    if (now - lastLive > 2000 || !playing) {
      var txt = summary(step);
      if (txt !== lastTxt) {
        lastTxt = txt;
        floor.setAttribute('aria-label', txt);
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
      var msg = fill(VISIBLE_COPY.floor.drawError, { why: err && err.message ? err.message : err });
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
    note.textContent = fill(VISIBLE_COPY.floor.withMapNote, { note: R.with_map.note, alpha: R.with_map.alpha,
      deliveries: R.with_map.deliveries, rate: R.with_map.pick_rate });
    Array.prototype.forEach.call(document.getElementsByName('router'), function (r) {
      r.addEventListener('change', function () { if (r.checked) { layer = r.value; draw(); announce(); } });
    });
  }

  ready = true;
  paintHeader(replayHeaderText());
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
    var LV = VISIBLE_COPY.live;
    paintHeader(fill(VISIBLE_COPY.header.live, { messages: 0, placed: 0, planted: '' }));
    ['.controls', '.hint', '#mapnote'].forEach(function (q) { var n = document.querySelector(q); if (n) n.hidden = true; });
    $('routerBox').hidden = true;
    $('grades').parentNode.hidden = true; // the per-map graded bars need the recorded run; live shows the counts instead
    $('detail-notes').hidden = true;
    var liveGrades = el('p', 'cap', '');
    $('top').insertAdjacentElement('afterend', liveGrades);
    var bar = el('p', 'livebar', fill(LV.connecting, { base: base }));
    bar.setAttribute('role', 'status');
    document.querySelector('.head').insertAdjacentElement('afterend', bar);

    var CELLV = 22, G = null, state = null, lastOk = 0, failing = 0, inflight = false;
    var barKey = null, lastStep = null, sameSteps = 0;
    var placed = {}; // "x,y" -> p, from this page's own successful POSTs
    var prevDisp = {}, flashUntil = {}, marked = {}, marks = []; // breakdown flashes (per robot) and grade marks, wall clock
    var cursor = null, reveal = false, promptCell = null;
    var series = [], seriesAt = null; // right-rate after each new map, live
    var floorEl = $('floor'), ctx = floorEl.getContext('2d');
    floorEl.tabIndex = 0;
    floorEl.setAttribute('role', 'application'); // operable in live mode (offline it stays role="img")
    floorEl.setAttribute('aria-label', LV.aria);

    // legend for the live floor: the static legend plus the operator's own roadblocks
    var planted = document.querySelector('#lrow-planted ul');
    var li = el('li');
    var ic = el('canvas', 'icon');
    ic.setAttribute('data-ico', 'placed'); ic.setAttribute('aria-hidden', 'true');
    li.appendChild(ic); li.appendChild(el('span', null, LV.placedBy));
    planted.appendChild(li);
    drawLegends();
    var revealBox = el('label', 'revealbox', '');
    var revealIn = document.createElement('input');
    revealIn.type = 'checkbox';
    revealBox.appendChild(revealIn);
    revealBox.appendChild(document.createTextNode(LV.reveal));
    revealBox.hidden = true;
    $('floorlegend').insertAdjacentElement('afterend', revealBox);
    revealIn.addEventListener('change', function () { reveal = revealIn.checked; drawLive(); });

    // counters (inside the closed details block of panel 2)
    var counterDd = DETAILS_COPY.liveRows.map(function (r) {
      var dt = el('dt', null, r), dd = el('dd', null, '');
      $('counters').appendChild(dt); $('counters').appendChild(dd);
      return dd;
    });
    // inline prompt
    var prompt = el('form', 'prompt', '');
    prompt.hidden = true;
    prompt.setAttribute('role', 'dialog');
    prompt.setAttribute('aria-label', LV.promptDialog);
    var plabel = el('span', 'plabel', '');
    var pr = document.createElement('input');
    pr.type = 'range'; pr.min = '0.5'; pr.max = '1'; pr.step = '0.01'; pr.value = '0.95';
    pr.setAttribute('aria-label', LV.promptRange);
    var pval = el('output', 'pval', '0.95');
    var ok = el('button', 'btn primary', LV.place);
    ok.type = 'submit';
    var cancel = el('button', 'btn', LV.cancel);
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
            say(fill(LV.placed, { cell: key, p: p.toFixed(2), step: res.j.applies_at_step }));
            closePrompt(true);
          } else say(fill(LV.notPlaced, { why: res.j && res.j.error ? res.j.error : LV.serverNo }));
        })
        .catch(function () { ok.disabled = false; say(LV.unreachable); });
    });

    function say(t) { $('mapstate').textContent = t; $('live').textContent = t; }
    function isHighway(x, y) { return G && G.highway[y] && G.highway[y].charAt(x) === '1'; }
    function isGoal(x, y) { return G.goals.some(function (g) { return g[0] === x && g[1] === y; }); }
    function whyNot(x, y) {
      if (!G || x < 0 || y < 0 || x >= G.width || y >= G.height) return LV.outside;
      if (!isHighway(x, y)) return LV.shelf;
      if (isGoal(x, y)) return LV.goal;
      return null;
    }
    function openPrompt(x, y) {
      var why = whyNot(x, y);
      if (why) { say(fill(LV.cannot, { cell: x + ',' + y, why: why })); return; }
      promptCell = x + ',' + y;
      plabel.textContent = fill(LV.promptLabel, { cell: promptCell });
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
      var c = cellAt(ev), why = whyNot(c[0], c[1]), cell = c[0] + ',' + c[1];
      floorEl.title = why ? fill(LV.cellHere, { cell: cell, why: why }) : fill(LV.cellClick, { cell: cell });
    });
    floorEl.addEventListener('keydown', function (e) {
      if (!G) return;
      if (!cursor) cursor = [0, 0];
      var d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
      if (d) {
        e.preventDefault();
        cursor = [Math.max(0, Math.min(G.width - 1, cursor[0] + d[0])), Math.max(0, Math.min(G.height - 1, cursor[1] + d[1]))];
        var why = whyNot(cursor[0], cursor[1]), cell = cursor[0] + ',' + cursor[1];
        var here = tipProvider(cursor[0], cursor[1]).map(function (i) { return tipLines(i).join(', '); }).join('; ');
        $('live').textContent = (why ? fill(LV.cellHere, { cell: cell, why: why }) : fill(LV.cellKey, { cell: cell })) + (here ? '. ' + here : '');
        drawLive();
      } else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openPrompt(cursor[0], cursor[1]); }
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !prompt.hidden) closePrompt(true); });
    themeBtn.addEventListener('click', function () { drawLive(); });

    // ---- drawing ----
    function robotKind(id) { return (parseInt(String(id).split('-')[1], 10) || 0) <= G.agvs ? 'agv' : 'picker'; }
    function mineCells() {
      var mine = {};
      Object.keys(placed).forEach(function (k) { mine[k] = true; });
      if (state) state.injections.forEach(function (i) { if (i.kind === 'floor') Object.keys(i.payload).forEach(function (k) { mine[k] = true; }); });
      return mine;
    }
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
      if (state) drawTopLabels(c, state.top10.slice(0, 10).map(function (r) { return r.cell; }), CELLV);
      if (reveal && state && state.truth) {
        c.strokeStyle = css('--obst'); c.lineWidth = 2; c.setLineDash([4, 3]);
        [state.truth.scheduled, state.truth.injected].forEach(function (m) {
          Object.keys(m || {}).forEach(function (k) { var xy = k.split(','); c.strokeRect(+xy[0] * CELLV + 2, +xy[1] * CELLV + 2, CELLV - 4, CELLV - 4); });
        });
        c.setLineDash([]);
      }
      // placed by you: a solid accent outline with a corner mark, never filled (the fill is the analyser's)
      var mine = mineCells();
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

    // ---- live adapters: /state -> the same view objects the replay builds ----
    // panel 2: ledger.messages_parsed / _rejected / duplicates / bytes_read / messages_per_s, and the lag = (ledger.steps_done - 1 -
    // step) * 5 s, the emitter's newest step against the newest step the analyser has read
    function liveLog(s) {
      var L = s.ledger, lines = L.messages_parsed + L.messages_rejected + L.duplicates;
      var lag = L.steps_done ? Math.max(0, L.steps_done - 1 - s.step) * 5 : null;
      return { lines: lines, bytes: L.bytes_read, rate: L.messages_per_s, lag: lag, live: true, usable: L.messages_parsed,
        rejected: L.messages_rejected, dups: L.duplicates, kept: null, cov: L.messages_emitted ? L.messages_parsed / L.messages_emitted : null,
        hover: { arrived: fill(HOVER_COPY.arrivedLive, { lines: fmt(lines), bytes: fmt(L.bytes_read) }),
                 usable: fill(HOVER_COPY.usableLive, { accepted: fmt(L.messages_parsed), rejected: fmt(L.messages_rejected), dups: fmt(L.duplicates) }),
                 kept: HOVER_COPY.keptLive } };
    }
    // panel 3: precision and recall need the revealed hidden layout (state.truth, a demo switch); the call counts are grades.forecasts
    function liveAnalyser(s) {
      var cells = s.costmap ? s.costmap.cells : {};
      var ranked = Object.keys(cells).sort(function (a, b) { return cells[b] - cells[a] || (a < b ? -1 : 1); });
      var right = null, found = null;
      if (s.truth) {
        var planted = {};
        [s.truth.scheduled, s.truth.injected].forEach(function (m) { Object.keys(m || {}).forEach(function (k) { planted[k] = true; }); });
        var n = Object.keys(planted).length;
        right = ranked.slice(0, 20).filter(function (k) { return planted[k]; }).length / 20;
        found = n ? ranked.slice(0, n).filter(function (k) { return planted[k]; }).length / n : null;
      }
      var at = s.costmap ? s.costmap.generated_at : null;
      if (right !== null && at !== seriesAt) { seriesAt = at; series.push(right); }
      var g = s.grades.forecasts, total = g.ok + g.off + g.pending + g.not_gradable;
      return { right: right, found: found, calls: total ? total : null, hits: total ? g.ok : null, wrong: total ? g.off : null,
        note: !s.costmap ? VISIBLE_COPY.analyser.noMap : (s.truth === null ? VISIBLE_COPY.analyser.needTruth : ''),
        series: series.map(function (p, i) { return { x: series.length > 1 ? i / (series.length - 1) : 0, p: p }; }),
        hover: { right: s.truth ? HOVER_COPY.rightLive : '', found: s.truth ? HOVER_COPY.foundLive : '',
                 checks: fill(HOVER_COPY.checksLive, { ok: g.ok, off: g.off, pending: g.pending, na: g.not_gradable }) } };
    }
    // panel 4: state.lessons, newest first (the server sorts them)
    function liveLessons(s) {
      var V = HOVER_COPY.liveVerdict;
      return s.lessons.slice(0, 5).map(function (l) {
        return { kind: l.lesson_kind, conf: l.confidence, mark: l.state === 'ok' ? 'ok' : (l.state === 'off' ? 'off' : null),
          hover: fill(HOVER_COPY.lessonLineLive, { text: l.text, kind: l.lesson_kind, zone: l.zone, c: l.confidence.toFixed(2),
            drawn: l.decided_at, verdict: V[l.state] || V.pending }) };
      });
    }

    function render() {
      var s = state, L = s.ledger;
      var planted = s.truth ? Object.keys(s.truth.scheduled || {}).length : null;
      paintHeader(fill(VISIBLE_COPY.header.live, { messages: fmt(L.messages_parsed), placed: Object.keys(mineCells()).length,
        planted: planted === null ? '' : fill(VISIBLE_COPY.header.livePlanted, { n: planted }) }));
      paintLog(liveLog(s));
      paintAnalyser(liveAnalyser(s));
      paintLessons(liveLessons(s), LV.noLessons);
      counterDd[0].textContent = fmt(s.step);
      counterDd[1].textContent = s.sim_time || LV.notStarted;
      counterDd[2].textContent = fmt(L.messages_emitted) + (L.expected_messages ? fill(DETAILS_COPY.liveExpected, { n: fmt(L.expected_messages) }) : '');
      counterDd[3].textContent = fmt(L.messages_parsed);
      counterDd[4].textContent = L.messages_rejected ? fmt(L.messages_rejected) : DETAILS_COPY.noneRejected;
      counterDd[5].textContent = fmt(L.duplicates);
      counterDd[6].textContent = fmt(L.bytes_read) + ' B';
      counterDd[7].textContent = fmt(L.messages_per_s);
      counterDd[8].textContent = fmt(L.injections_posted) + ' / ' + fmt(L.injections_applied);
      counterDd[9].textContent = L.emit_status || 'starting';
      $('match').textContent = DETAILS_COPY.liveMatch;
      var ol = $('top');
      ol.textContent = '';
      if (!s.top10.length) { var li0 = el('li', null, s.costmap ? DETAILS_COPY.noFlag : DETAILS_COPY.noMapTop); li0.style.listStyle = 'none'; ol.appendChild(li0); }
      s.top10.forEach(function (r) {
        ol.appendChild(el('li', null, fill(DETAILS_COPY.topLive, { cell: r.cell, cost: r.cost.toFixed(2), flag: placed[r.cell] !== undefined ? DETAILS_COPY.topLiveMine : '' })));
      });
      var g = s.grades;
      function line(label, o) { return fill(DETAILS_COPY.liveLine, { label: label, ok: o.ok, off: o.off, pending: o.pending, na: o.not_gradable }); }
      liveGrades.textContent = line(DETAILS_COPY.liveCalls, g.forecasts) + '. ' + line(DETAILS_COPY.liveLessons, g.lessons) + '. ' + DETAILS_COPY.liveGradedOn;
      revealBox.hidden = s.truth === null;
      if (s.truth === null) { reveal = false; revealIn.checked = false; }
      floorEl.setAttribute('aria-label', fill(LV.ariaNow, { step: s.step, robots: s.robots.length, cells: Object.keys(s.costmap ? s.costmap.cells : {}).length }));
      drawLive();
    }

    function setConnected(okNow, err) {
      // "Live" needs a reachable server AND a run that advances: a finished or stalled run is said so, with the step
      var key, cls, text, stale;
      if (okNow) {
        var status = state && state.ledger ? state.ledger.emit_status : null;
        if (status && status !== 'running') {
          key = 'over:' + status; cls = 'livebar bad'; stale = false;
          text = fill(LV.over, { status: status, step: state.step });
        } else if (sameSteps >= 6) {
          key = 'stuck:' + state.step; cls = 'livebar bad'; stale = true;
          text = fill(LV.stuck, { base: base, step: state.step, secs: Math.round(sameSteps * POLL_MS / 1000) });
        } else {
          key = 'ok'; cls = 'livebar'; stale = false;
          text = fill(LV.ok, { base: base, every: POLL_MS / 1000 });
        }
      } else {
        var age = lastOk ? Math.round((Date.now() - lastOk) / 1000) : null;
        key = 'bad:' + err + ':' + (age === null ? '' : Math.floor(age / 5)); cls = 'livebar bad'; stale = true;
        text = fill(LV.lost, { base: base, every: POLL_MS / 1000, age: age === null ? LV.lostNever : fill(LV.lostAge, { s: age }),
          err: err ? ' (' + err + ')' : '' });
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
        .catch(function () { setConnected(false, LV.noGrid); setTimeout(loadGrid, 1000); });
    }
    loadGrid();
    poll();
    setInterval(poll, POLL_MS);
    applyTheme();
  }
})();
