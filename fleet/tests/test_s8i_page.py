"""S8I-ONE-PAGER, page side (criterion C5, C6, C7): DOM-free checks of docs/replay/index.html, replay.js and
docs/replay/README.md. No browser, no jsdom: the HTML is read with html.parser, the JavaScript with a small tokenizer that
finds string and template literals (comments skipped) and the span of a named const. The page itself is NOT run here; what
the page writes into visible elements at runtime is checked on the diff (every visible write goes through VISIBLE_COPY).

Rules for replay.js that make the tokenizer sound: no regular-expression literals, no template literals with ${...} (plain
backticks would still be read as literals).
"""
import html as htmllib
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "replay"

BANNED = re.compile(r"\b(cost|publish|grade|horizon|stream|rank|stall|episode|zone|coverage)\w*", re.I)
VOID = {"meta", "link", "input", "br", "img", "hr", "source", "wbr"}
HEADINGS = ["1. The floor", "2. The log", "3. What the analyser figured out", "4. What it would tell your operators",
            "5. What is it worth?"]  # S8J: a fifth panel
OLD_HEADINGS = ["The extractor: is the log usable?", "The analyser and the fleet memory"]
# S8J: three strings are superseded and removed here (the funnel arrow label, the log sentence under the funnel and the footer
# sentence about persistence); fleet/tests/test_s8j_page.py holds their replacements. "Dropped" joins the funnel labels.
STRINGS = ["Arrived", "Usable", "Kept", "Dropped",
           "nothing is dropped silently, every rejected line is stored with its reason",
           "Written by rules over the counts, not by a language model. Each line is checked against what happened next.",
           "gets better as it watches", "Synthetic data from a simulator."]
LESSON_KEYS = ["hot_cell", "hot_robot", "recurring_pair", "fallback"]
# Literals that may stand outside VISIBLE_COPY / HOVER_COPY / DETAILS_COPY although they contain whitespace or an uppercase
# letter: units and separators, key names, CSS classes and ids, canvas fonts, media queries, HTTP plumbing. None is a sentence.
ALLOWED_OUTSIDE_COPY = {
    "use strict", " B", " KB", " MB", " s", " %", "\n", ", ", "; ", ". ", " ", " / ", " (", "  ", "Escape", "Enter", "ArrowLeft",
    "ArrowRight", "ArrowUp", "ArrowDown", "INPUT", "SELECT", "TEXTAREA", "BUTTON", "lineTo", "moveTo", "les ", "livebar bad",
    "cap small", "btn primary", "routerBox", "#lrow-planted ul", "600 13px system-ui, sans-serif", "bold 11px system-ui, sans-serif",
    "bold 13px system-ui, sans-serif", "bold ", "px system-ui, sans-serif", "(prefers-color-scheme: dark)",
    "(prefers-reduced-motion: reduce)", "en-US", "POST", "Content-Type", "HTTP ",
}


# ------------------------------------------------------------------------------------------------ html
class VisibleText(HTMLParser):
    """The text a reader sees without opening anything: no script / style, no element marked data-details (with all it
    contains), no attribute values."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.skip, self.chunks = [], 0, []

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        skip = tag in ("script", "style") or any(k == "data-details" for k, _ in attrs)
        self.stack.append(skip)
        self.skip += skip

    def handle_endtag(self, tag):
        if tag in VOID or not self.stack:
            return
        self.skip -= self.stack.pop()

    def handle_data(self, data):
        if not self.skip:
            self.chunks.append(data)


def visible_html_text(html_text):
    p = VisibleText()
    p.feed(html_text)
    p.close()
    return " ".join(" ".join(p.chunks).split())


def banned_in_html(html_text):
    return sorted({m.group(0) for m in BANNED.finditer(visible_html_text(html_text))})


class BigElements(HTMLParser):
    """Text of every element whose class list has `big`."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.cur, self.found = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        classes = dict(attrs).get("class", "").split()
        self.depth.append(tag)
        if "big" in classes and self.cur is None:
            self.cur = [len(self.depth), []]

    def handle_endtag(self, tag):
        if tag in VOID or not self.depth:
            return
        if self.cur is not None and self.cur[0] == len(self.depth):
            self.found.append("".join(self.cur[1]))
            self.cur = None
        self.depth.pop()

    def handle_data(self, data):
        if self.cur is not None:
            self.cur[1].append(data)


def big_texts(html_text):
    p = BigElements()
    p.feed(html_text)
    return p.found


def panel(html_text, label):
    """The source of the <section> whose aria-labelledby is `label`."""
    i = html_text.index(f'aria-labelledby="{label}"')
    start = html_text.rfind("<section", 0, i)
    return html_text[start:html_text.index("</section>", i) + len("</section>")]


# ------------------------------------------------------------------------------------------------ javascript
def scan_js(js):
    """(literals, code): literals = [(start, end, value)] for every '...', "..." and `...` literal outside comments; code =
    the source with comments blanked (same length), string contents kept."""
    lits, out, i, n = [], list(js), 0, len(js)
    while i < n:
        c = js[i]
        if c in "'\"`":
            j = i + 1
            while j < n and js[j] != c:
                j += 2 if js[j] == "\\" else 1
            lits.append((i, j, unescape_js(js[i + 1:j])))
            i = j + 1
        elif js.startswith("//", i):
            j = js.find("\n", i)
            j = n if j < 0 else j
            out[i:j] = " " * (j - i)
            i = j
        elif js.startswith("/*", i):
            j = js.index("*/", i) + 2
            out[i:j] = [" " if ch != "\n" else "\n" for ch in js[i:j]]
            i = j
        else:
            i += 1
    return lits, "".join(out)


def unescape_js(s):
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)


def const_span(js, name):
    """(start, end) of the {...} initialiser of `const NAME = {...}` or None."""
    lits, code = scan_js(js)
    m = re.search(rf"\bconst\s+{name}\s*=\s*\{{", code)
    if not m:
        return None
    inside = {k for a, b, _ in lits for k in range(a, b + 1)}
    depth, i = 0, m.end() - 1
    while i < len(code):
        if i not in inside:
            depth += code[i] == "{"
            depth -= code[i] == "}"
            if depth == 0:
                return m.end() - 1, i
        i += 1
    raise ValueError(f"unbalanced braces in {name}")


def visible_literals(js):
    """Literals outside the HOVER_COPY / DETAILS_COPY initialisers that a reader could see: they contain whitespace or an
    uppercase letter. Raises when VISIBLE_COPY is missing or lacks a lesson-kind key."""
    spans = {n: const_span(js, n) for n in ("VISIBLE_COPY", "HOVER_COPY", "DETAILS_COPY")}
    if spans["VISIBLE_COPY"] is None:
        raise ValueError("replay.js has no const VISIBLE_COPY")
    body = js[spans["VISIBLE_COPY"][0]:spans["VISIBLE_COPY"][1]]
    missing = [k for k in LESSON_KEYS if not re.search(rf"\b{k}\s*:", body)]
    if missing:
        raise ValueError(f"VISIBLE_COPY lacks the lesson-kind keys {missing}")
    lits, _ = scan_js(js)
    hidden = [spans[n] for n in ("HOVER_COPY", "DETAILS_COPY") if spans[n] is not None]
    return [v for a, b, v in lits
            if not any(s <= a <= e for s, e in hidden) and (re.search(r"\s", v) or re.search(r"[A-Z]", v))]


def VISIBLE_TABLE_TEXT(js):
    """The literals inside the VISIBLE_COPY initialiser (visible text belongs there)."""
    a, b = const_span(js, "VISIBLE_COPY")
    return {v for s, e, v in scan_js(js)[0] if a <= s <= b}


def banned_in_js(js):
    return sorted({m.group(0) for v in visible_literals(js) for m in BANNED.finditer(v)})


def norm(s):
    return " ".join(s.split())


# ------------------------------------------------------------------------------------------------ tests
class TestPageText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (DOCS / "index.html").read_text(encoding="utf-8")
        cls.js = (DOCS / "replay.js").read_text(encoding="utf-8")

    def test_headings_and_the_old_ones_are_gone(self):
        text = norm(htmllib.unescape(self.html))
        for h in HEADINGS:
            self.assertIn(f">{h}</h2>", self.html, h)
        for h in OLD_HEADINGS:
            self.assertNotIn(h, text)
        self.assertEqual(re.findall(r"<h2[^>]*>([^<]*)</h2>", self.html), HEADINGS)

    def test_the_required_strings_are_in_the_html_or_in_replay_js(self):
        html_text = norm(htmllib.unescape(self.html))
        js_text = norm(" ".join(v for _, _, v in scan_js(self.js)[0]))
        where = {}
        for s in STRINGS:
            where[s] = "index.html" if norm(s) in html_text else ("replay.js" if norm(s) in js_text else None)
        self.assertEqual([s for s, w in where.items() if w is None], [], where)

    def test_big_numbers_hold_no_digits_in_the_html_and_panel_3_has_at_least_three(self):
        bigs = big_texts(self.html)
        self.assertTrue(bigs)
        self.assertEqual([t for t in bigs if re.search(r"[0-9]", t)], [])
        self.assertGreaterEqual(len(big_texts(panel(self.html, "h-ana"))), 3)

    def test_panel_3_has_exactly_one_closed_details_marked_data_details(self):
        p3 = panel(self.html, "h-ana")
        tags = re.findall(r"<details\b[^>]*>", p3)
        self.assertEqual(len(tags), 1, tags)
        self.assertNotRegex(tags[0], r"\bopen\b")
        self.assertIn("data-details", tags[0])
        for tag in re.findall(r"<details\b[^>]*>", self.html):
            self.assertNotRegex(tag, r"\bopen\b")

    def test_the_footer_sources_list_is_inside_a_closed_data_details(self):
        foot = self.html[self.html.index('<footer'):self.html.index("</footer>")]
        d = re.search(r"<details\b[^>]*data-details[^>]*>(.*?)</details>", foot, re.S)
        self.assertIsNotNone(d)
        self.assertIn('id="sources"', d.group(1))
        self.assertNotIn('id="sources"', foot.replace(d.group(0), ""))


class TestBannedWords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (DOCS / "index.html").read_text(encoding="utf-8")
        cls.js = (DOCS / "replay.js").read_text(encoding="utf-8")

    def test_html_visible_text_has_no_banned_word(self):
        self.assertEqual(banned_in_html(self.html), [], visible_html_text(self.html))

    def test_replay_js_visible_literals_have_no_banned_word(self):
        self.assertEqual(banned_in_js(self.js), [])

    def test_visible_copy_exists_with_the_lesson_kind_keys_and_hover_and_details_consts_exist(self):
        visible_literals(self.js)  # raises when VISIBLE_COPY is missing or lacks a lesson-kind key
        self.assertIsNotNone(const_span(self.js, "HOVER_COPY"))
        self.assertIsNotNone(const_span(self.js, "DETAILS_COPY"))

    def test_no_readable_text_outside_the_copy_tables(self):
        """Every literal with whitespace or an uppercase letter outside the three copy tables is on the short allowlist of units,
        separators and code tokens. A new sentence added next to the code fails here, which keeps C6(b) honest."""
        extra = sorted({v for v in visible_literals(self.js)} - ALLOWED_OUTSIDE_COPY)
        extra = [v for v in extra if v not in VISIBLE_TABLE_TEXT(self.js)]
        self.assertEqual(extra, [])

    def test_the_checkers_are_red_on_what_they_should_catch(self):
        self.assertEqual(banned_in_html("<p>Robots stalled in zone 3</p>"), ["stalled", "zone"])
        self.assertEqual(banned_in_html('<p>ok</p><details data-details><p>a cost map</p></details><script>var cost</script>'
                                        '<p title="cost">fine</p>'), [])
        self.assertEqual(banned_in_html('<details data-details><details><p>zone</p></details><p>stream</p></details><p>x</p>'), [])
        js = ("const VISIBLE_COPY = { lesson: { hot_cell: 'a', hot_robot: 'b', recurring_pair: 'c', fallback: 'd' }, "
              "x: 'ok text' };\nconst HOVER_COPY = { a: 'a stalled robot' };\nconst DETAILS_COPY = { b: 'the zone' };\n"
              "el.textContent = 'Robots stalled in zone ' + z; var k = 'stalled'; // a stream\n")
        self.assertEqual(banned_in_js(js), ["stalled", "zone"])
        with self.assertRaises(ValueError):
            banned_in_js("const HOVER_COPY = {};")
        with self.assertRaises(ValueError):
            banned_in_js("const VISIBLE_COPY = { lesson: { hot_cell: 'a' } };")


class TestPagesReady(unittest.TestCase):
    def test_no_absolute_or_remote_asset_paths(self):
        html_text = (DOCS / "index.html").read_text(encoding="utf-8")

        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.bad = []

            def handle_starttag(self, tag, attrs):
                for k, v in attrs:
                    if k in ("src", "href") and v and v.startswith(("http:", "https:", "//", "/")):
                        self.bad.append((tag, k, v))

        p = Links()
        p.feed(html_text)
        self.assertEqual(p.bad, [])
        js = (DOCS / "replay.js").read_text(encoding="utf-8")
        self.assertEqual([v for _, _, v in scan_js(js)[0] if "http://" in v or "https://" in v], [])

    def test_readme_has_the_chain(self):
        readme = (DOCS / "README.md").read_text(encoding="utf-8")
        lines = readme.splitlines()
        # S8J: the --carry-lessons check is replaced by --lessons-long (the lessons are this run's own now)
        export = [ln for ln in lines if "replay_export.py" in ln and "--lessons-long" in ln]
        self.assertTrue(export, "no replay_export.py line with --lessons-long")
        for flag in ("--hotspot results/fleet/hotspot_s8i-demo-noise.json",
                     "--closed-loop-summary results/closed_loop_sticky/summary.json",
                     "--benchmark results/fleet/benchmark.json"):
            self.assertTrue(any(flag in ln for ln in export), flag)
        self.assertTrue(any("emit.py" in ln and "--demo --demo-noise" in ln for ln in lines))
        self.assertTrue((ROOT / "results" / "fleet" / "hotspot_s8i-demo-noise.json").is_file())


if __name__ == "__main__":
    sys.exit(unittest.main())
