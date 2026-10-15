"""S8J-WORDING criterion C5: a stub-DOM Node harness for docs/replay (no browser, no jsdom). `run_page` runs the real
docs/replay/replay.js in a vm context over a small DOM parsed from the real docs/replay/index.html, drives the scrub slider (or,
with a `search` of ?live=..., the live poll over a canned fetch) and returns the snapshots as parsed JSON. There is no other Node
page harness in the repo. The page is run here; it is never opened in a browser by the tests.

The tests that use it are in test_s8j_page.py. When node is missing the helper FAILS on macOS and skips elsewhere (CI)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "replay"

HARNESS = r'''
'use strict';
// Stub DOM smoke for docs/replay (S8J C5). node harness.js <index.html> <replay.js> <data.js|-> <scenario.json>
// Parses index.html into a small tree, runs replay.js in a vm context against it, drives the scrub slider, and prints a JSON
// snapshot per step. No browser, no jsdom. The page itself is run here; it is not opened in a browser.
const fs = require('fs');
const vm = require('vm');
const [, , htmlPath, jsPath, dataPath, scenarioPath] = process.argv;
const scenario = JSON.parse(fs.readFileSync(scenarioPath, 'utf8'));

const VOID = new Set(['meta', 'link', 'input', 'br', 'img', 'hr', 'source', 'wbr']);
const ENT = { rarr: '→', ldquo: '“', rdquo: '”', amp: '&', lt: '<', gt: '>', quot: '"', nbsp: ' ', mdash: '—' };
function decode(s) {
  return s.replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, function (m, name) {
    if (name[0] === '#') return String.fromCodePoint(name[1] === 'x' ? parseInt(name.slice(2), 16) : parseInt(name.slice(1), 10));
    return Object.prototype.hasOwnProperty.call(ENT, name) ? ENT[name] : m;
  });
}

class TextNode {
  constructor(data) { this.nodeType = 3; this.data = data; this.parentNode = null; }
  get textContent() { return this.data; }
}

class El {
  constructor(tag) {
    this.nodeType = 1; this.tagName = tag.toUpperCase(); this._tag = tag.toLowerCase();
    this.childNodes = []; this.parentNode = null; this.attrs = {}; this.style = {}; this.listeners = {};
    this.value = ''; this.checked = false; this.disabled = false; this.width = 300; this.height = 150; this.title = '';
  }
  get children() { return this.childNodes.filter(function (n) { return n.nodeType === 1; }); }
  get id() { return this.attrs.id || ''; }
  set id(v) { this.attrs.id = String(v); }
  get className() { return this.attrs['class'] || ''; }
  set className(v) { this.attrs['class'] = String(v); }
  get hidden() { return Object.prototype.hasOwnProperty.call(this.attrs, 'hidden'); }
  set hidden(v) { if (v) this.attrs.hidden = ''; else delete this.attrs.hidden; }
  get tabIndex() { return this.attrs.tabindex === undefined ? -1 : +this.attrs.tabindex; }
  set tabIndex(v) { this.attrs.tabindex = String(v); }
  get classList() {
    const self = this;
    const list = function () { return self.className.split(/\s+/).filter(Boolean); };
    return {
      add: function (c) { if (list().indexOf(c) < 0) self.className = list().concat([c]).join(' '); },
      remove: function (c) { self.className = list().filter(function (x) { return x !== c; }).join(' '); },
      contains: function (c) { return list().indexOf(c) >= 0; },
      toggle: function (c, force) {
        const has = list().indexOf(c) >= 0, want = force === undefined ? !has : !!force;
        if (want && !has) this.add(c); else if (!want && has) this.remove(c);
        return want;
      }
    };
  }
  get textContent() { return this.childNodes.map(function (n) { return n.textContent; }).join(''); }
  set textContent(v) {
    this.childNodes.forEach(function (n) { n.parentNode = null; });
    this.childNodes = [];
    if (v !== '' && v !== null && v !== undefined) this.appendChild(new TextNode(String(v)));
  }
  get offsetWidth() { return 100; }
  get offsetHeight() { return 20; }
  setAttribute(k, v) {
    if (k === 'class') this.className = v; else if (k === 'id') this.id = v; else this.attrs[k] = String(v);
  }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k); }
  removeAttribute(k) { delete this.attrs[k]; }
  appendChild(n) {
    if (n.parentNode) n.parentNode.removeChild(n);
    n.parentNode = this; this.childNodes.push(n); return n;
  }
  removeChild(n) {
    const i = this.childNodes.indexOf(n);
    if (i >= 0) this.childNodes.splice(i, 1);
    n.parentNode = null; return n;
  }
  insertAdjacentElement(where, n) {
    if (n.parentNode) n.parentNode.removeChild(n);
    if (where === 'afterend' || where === 'beforebegin') {
      const p = this.parentNode, i = p.childNodes.indexOf(this);
      p.childNodes.splice(where === 'afterend' ? i + 1 : i, 0, n); n.parentNode = p;
    } else if (where === 'afterbegin') { this.childNodes.unshift(n); n.parentNode = this; }
    else this.appendChild(n);
    return n;
  }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  removeEventListener() {}
  dispatch(type, ev) { (this.listeners[type] || []).forEach(function (f) { f(ev); }); }
  getBoundingClientRect() { return { left: 0, top: 0, right: 100, bottom: 20, width: 100, height: 20 }; }
  focus() { document.activeElement = this; }
  click() { this.dispatch('click', { target: this }); }
  contains(n) { for (let x = n; x; x = x.parentNode) if (x === this) return true; return false; }
  getContext() {
    if (!this._ctx) {
      const store = {};
      this._ctx = new Proxy(store, {
        get: function (t, k) { if (k === 'measureText') return function () { return { width: 10 }; }; return k in t ? t[k] : function () {}; },
        set: function (t, k, v) { t[k] = v; return true; }
      });
    }
    return this._ctx;
  }
  closest(sel) { for (let x = this; x && x.nodeType === 1; x = x.parentNode) if (matches(x, sel)) return x; return null; }
  querySelector(sel) { return query(this, sel, true)[0] || null; }
  querySelectorAll(sel) { return query(this, sel, false); }
}

// ---- selectors: comma lists of descendant chains of compounds (tag, .class, #id, [attr], [attr=value])
function matchCompound(el, comp) {
  const re = /^([a-zA-Z][\w-]*)|\.([\w-]+)|#([\w-]+)|\[([\w-]+)(?:=["']?([^\]"']*)["']?)?\]/;
  let rest = comp;
  while (rest) {
    const m = re.exec(rest);
    if (!m) return false;
    if (m[1] !== undefined && el._tag !== m[1].toLowerCase()) return false;
    if (m[2] !== undefined && el.className.split(/\s+/).indexOf(m[2]) < 0) return false;
    if (m[3] !== undefined && el.id !== m[3]) return false;
    if (m[4] !== undefined) {
      if (!el.hasAttribute(m[4])) return false;
      if (m[5] !== undefined && el.getAttribute(m[4]) !== m[5]) return false;
    }
    rest = rest.slice(m[0].length);
  }
  return true;
}
function matches(el, sel) {
  return sel.split(',').some(function (one) {
    const parts = one.trim().split(/\s+/);
    if (!matchCompound(el, parts[parts.length - 1])) return false;
    let anc = el.parentNode;
    for (let i = parts.length - 2; i >= 0; i--) {
      while (anc && anc.nodeType === 1 && !matchCompound(anc, parts[i])) anc = anc.parentNode;
      if (!anc || anc.nodeType !== 1) return false;
      anc = anc.parentNode;
    }
    return true;
  });
}
function walk(el, fn) {
  el.childNodes.forEach(function (c) { if (c.nodeType === 1) { fn(c); walk(c, fn); } });
}
function query(root, sel, first) {
  const out = [];
  walk(root, function (e) { if ((!first || !out.length) && matches(e, sel)) out.push(e); });
  return out;
}

// ---- parse index.html
function parseHtml(text) {
  const root = new El('#root');
  const stack = [root];
  const re = /<!--[\s\S]*?-->|<!doctype[^>]*>|<\/([a-zA-Z0-9]+)\s*>|<([a-zA-Z0-9]+)((?:\s+[^\s=>\/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*(\/?)>|([^<]+)/gi;
  let m;
  while ((m = re.exec(text))) {
    if (m[1]) {
      const tag = m[1].toLowerCase();
      for (let i = stack.length - 1; i > 0; i--) if (stack[i]._tag === tag) { stack.length = i; break; }
    } else if (m[2]) {
      const tag = m[2].toLowerCase(), el = new El(tag);
      const are = /([^\s=>\/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
      let a;
      while ((a = are.exec(m[3]))) {
        const v = a[2] !== undefined ? a[2] : (a[3] !== undefined ? a[3] : (a[4] !== undefined ? a[4] : ''));
        el.attrs[a[1]] = decode(v);
      }
      stack[stack.length - 1].appendChild(el);
      if (tag === 'script' || tag === 'style') {
        const end = text.indexOf('</' + tag, re.lastIndex);
        re.lastIndex = end < 0 ? text.length : text.indexOf('>', end) + 1;
      } else if (!VOID.has(tag) && !m[4]) stack.push(el);
    } else if (m[5] !== undefined) {
      stack[stack.length - 1].appendChild(new TextNode(decode(m[5])));
    }
  }
  return root;
}

const root = parseHtml(fs.readFileSync(htmlPath, 'utf8'));
const htmlEl = query(root, 'html', true)[0];
const document = {
  documentElement: htmlEl, body: query(root, 'body', true)[0], activeElement: null, listeners: {},
  getElementById: function (id) { let f = null; walk(root, function (e) { if (!f && e.id === id) f = e; }); return f; },
  createElement: function (tag) { return new El(tag); },
  createTextNode: function (t) { return new TextNode(String(t)); },
  querySelector: function (s) { return query(root, s, true)[0] || null; },
  querySelectorAll: function (s) { return query(root, s, false); },
  getElementsByName: function (n) { return query(root, '[name="' + n + '"]', false); },
  addEventListener: function (t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
};

const sandbox = {
  document: document, console: console, URL: URL, URLSearchParams: URLSearchParams,
  setTimeout: function () { return 0; }, clearTimeout: function () {}, setInterval: function () { return 0; }, clearInterval: function () {},
  requestAnimationFrame: function () { return 0; }, performance: { now: function () { return 0; } },
  getComputedStyle: function () { return { getPropertyValue: function () { return '#123456'; } }; },
  matchMedia: function () { return { matches: false, addEventListener: function () {} }; },
  innerWidth: 1200, innerHeight: 800, devicePixelRatio: 1, location: { search: scenario.search || '' },
  addEventListener: function () {}, AbortController: AbortController
};
sandbox.window = sandbox;
sandbox.fetch = function (url) {
  const doc = scenario.fetch && scenario.fetch[new URL(url).pathname];
  if (doc === undefined) return Promise.reject(new Error('no stub for ' + url));
  return Promise.resolve({ ok: true, status: 200, json: function () { return Promise.resolve(JSON.parse(JSON.stringify(doc))); } });
};
vm.createContext(sandbox);
if (dataPath !== '-') vm.runInContext(fs.readFileSync(dataPath, 'utf8'), sandbox, { filename: 'data.js' });
vm.runInContext(fs.readFileSync(jsPath, 'utf8'), sandbox, { filename: 'replay.js' });

// ---- snapshots
function visibleText(el) {
  return el.childNodes.map(function (n) {
    if (n.nodeType === 3) return n.data;
    return n.className.split(/\s+/).indexOf('sr') >= 0 ? '' : visibleText(n);
  }).join('');
}
function isHidden(el) {
  for (let x = el; x && x.nodeType === 1; x = x.parentNode) if (x.hidden) return true;
  return false;
}
function shown(root_) {
  // visible text of every shown element, leaves of the text, details blocks and the sr spans left out
  const out = [];
  (function rec(e) {
    if (e.hidden || e.hasAttribute('data-details') || e._tag === 'script' || e._tag === 'style' || e._tag === 'canvas') return;
    if (e.className.split(/\s+/).indexOf('sr') >= 0) return;
    e.childNodes.forEach(function (n) { if (n.nodeType === 3) { if (n.data.trim()) out.push(n.data.trim()); } else rec(n); });
  })(root_);
  return out;
}
function snap() {
  const s = { ids: {}, lessons: [], bars: [], shown: shown(document.body).concat(shown(query(root, 'head', true)[0] || root)) };
  (scenario.ids || []).forEach(function (id) {
    const e = document.getElementById(id);
    s.ids[id] = e ? { text: visibleText(e), hidden: isHidden(e), title: e.getAttribute('aria-describedby') } : null;
  });
  const ul = document.getElementById('lessons');
  ul.children.forEach(function (li) {
    s.lessons.push({ key: li.getAttribute('data-key'), cls: li.className, text: visibleText(li.children[0]),
      truth: query(li, '.truth', false).map(function (t) { return { truth: t.getAttribute('data-truth'), text: visibleText(t) }; }),
      pending: query(li, '.pend', false).length, full: visibleText(li) });
  });
  const wb = document.getElementById('worthbars');
  wb.children.forEach(function (b) {
    s.bars.push({ key: b.getAttribute('data-key'), label: visibleText(query(b, '.wlab', true)[0]), value: visibleText(query(b, '.wval', true)[0]) });
  });
  s.hovers = {};
  (scenario.hover_ids || []).forEach(function (id) {
    const d = document.getElementById(id + '-d');
    s.hovers[id] = d ? d.textContent : null;
  });
  return s;
}

(async function main() {
  const out = [];
  if (scenario.search) {
    for (let i = 0; i < 6; i++) await new Promise(function (r) { setImmediate(r); });
    out.push({ step: null, snap: snap() });
  } else {
    const scrub = document.getElementById('scrub');
    for (const step of scenario.steps) {
      scrub.dispatch('input', { target: { value: String(step) } });
      out.push({ step: step, snap: snap() });
    }
  }
  process.stdout.write(JSON.stringify(out));
})().catch(function (e) { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
'''


def need_node(case):
    """The node binary, or a failure on macOS / a skip where CI has no node."""
    node = shutil.which("node")
    if node is None:
        if sys.platform == "darwin" and not os.environ.get("CI"):
            case.fail("node is not on PATH; the render check (C5) must run on this machine")
        case.skipTest("node is not on PATH (CI without node)")
    return node


def run_page(case, scenario, data_path=None, html=DOCS / "index.html", js=DOCS / "replay.js"):
    """Run the harness; returns the list of {step, snap} dicts. scenario: steps / ids / hover_ids, or search + fetch (live)."""
    node = need_node(case)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "harness.js").write_text(HARNESS, encoding="utf-8")
        (tmp / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
        r = subprocess.run([node, str(tmp / "harness.js"), str(html), str(js), "-" if data_path is None else str(data_path),
                            str(tmp / "scenario.json")], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        case.fail(f"the page failed to run under the stub DOM: {r.stderr[-1500:]}")
    return json.loads(r.stdout)
