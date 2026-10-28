"""
Rich text for Desk Notes.

Notes are saved as simple Markdown-style text, so they stay readable as a
plain file and old plain-text notes still load:

    # Big heading            ## Small heading
    - bullet                 1. numbered item
    - [ ] to do              - [x] done
    **bold**  *italic*  ~~strikethrough~~
    two spaces before a list item = one indent level

Inside the note window the markers are hidden and shown as real
formatting (RichEditor below).
"""

import re

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

LIST_KINDS = ("bullet", "check", "num")
INLINE = ("bold", "italic", "strike")
HEADINGS = ("h1", "h2")
MAX_LEVEL = 4
BULLETS = ["•", "◦", "▪", "•", "◦"]
UNCHECKED, CHECKED = "☐", "☑"

_MARK = {"bold": "**", "italic": "*", "strike": "~~"}
_RE_LIST = re.compile(r"^( *)(?:(- \[( |x|X)\] )|([-*] )|(\d+)\. )")
_RE_HEAD = re.compile(r"^(#{1,2}) ")
_RE_LOOKS_LIKE_MARKER = re.compile(r"^\s*([-*] |\d+\. |#{1,2} |- \[)")
RE_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"']+[^\s<>\"'.,;:!?)\]]")


# ------------------------------------------------------------ text format --

def parse_inline(s):
    """'a **b** c' -> [('a ', {}), ('b', {'bold'}), (' c', {})]"""
    segs, cur, tags, i = [], [], set(), 0

    def flush():
        if cur:
            segs.append(("".join(cur), frozenset(tags)))
            cur.clear()

    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            cur.append(s[i + 1])
            i += 2
        elif s.startswith("**", i):
            flush(); tags ^= {"bold"}; i += 2
        elif s.startswith("~~", i):
            flush(); tags ^= {"strike"}; i += 2
        elif c == "*":
            flush(); tags ^= {"italic"}; i += 1
        else:
            cur.append(c)
            i += 1
    flush()
    return segs


_RE_PASTE_INLINE = re.compile(
    r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__"
    r"|~~(?=\S)(.+?)(?<=\S)~~"
    r"|(?<![\w*])\*(?=\S)([^*]+?)(?<=\S)\*(?![\w*])"
    r"|(?<![\w_])_(?=\S)([^_]+?)(?<=\S)_(?![\w_])")


def parse_inline_pasted(s):
    """Like parse_inline, but only *matched* pairs count as formatting, so
    pasted text such as '5*3' or 'file_name' stays exactly as it was."""
    segs, pos = [], 0
    for m in _RE_PASTE_INLINE.finditer(s):
        if m.start() > pos:
            segs.append((s[pos:m.start()], frozenset()))
        if m.group(1) or m.group(2):
            inner, tag = m.group(1) or m.group(2), "bold"
        elif m.group(3):
            inner, tag = m.group(3), "strike"
        else:
            inner, tag = m.group(4) or m.group(5), "italic"
        for text, tags in parse_inline_pasted(inner):   # e.g. bold inside strike
            segs.append((text, tags | {tag}))
        pos = m.end()
    if pos < len(s):
        segs.append((s[pos:], frozenset()))
    return segs


def parse_pasted_line(raw):
    """A pasted line (Markdown from Notion, ChatGPT, etc.) -> line info."""
    raw = raw.replace("\t", "  ").rstrip("\r")
    m = re.match(r"^( *)(?:[-*+] \[( |x|X)\] +|[-*+•] +|(\d+)[.)] +|(#{1,6}) +)", raw)
    info = {"kind": None, "level": 0, "checked": False, "num": 1, "heading": 0}
    rest = raw
    if m:
        lead = len(m.group(1))
        if m.group(4):
            info["heading"] = 1 if len(m.group(4)) == 1 else 2
        else:
            info["level"] = min(lead // 2, MAX_LEVEL)
            if m.group(2) is not None:
                info["kind"], info["checked"] = "check", m.group(2) in "xX"
            elif m.group(3):
                info["kind"], info["num"] = "num", int(m.group(3))
            else:
                info["kind"] = "bullet"
        rest = raw[m.end():]
    info["segs"] = parse_inline_pasted(rest)
    return info


def parse_line(raw):
    info = {"kind": None, "level": 0, "checked": False, "num": 1, "heading": 0}
    m = _RE_LIST.match(raw)
    if m:
        info["level"] = min(len(m.group(1)) // 2, MAX_LEVEL)
        if m.group(2):
            info["kind"] = "check"
            info["checked"] = m.group(3) in "xX"
        elif m.group(4):
            info["kind"] = "bullet"
        else:
            info["kind"] = "num"
            info["num"] = int(m.group(5))
        rest = raw[m.end():]
    else:
        h = _RE_HEAD.match(raw)
        if h:
            info["heading"] = len(h.group(1))
            rest = raw[h.end():]
        else:
            rest = raw
    info["segs"] = parse_inline(rest)
    return info


def _escape(text):
    return text.replace("\\", "\\\\").replace("*", "\\*").replace("~", "\\~")


def serialize_inline(runs):
    """runs: [(text, set_of_inline_tags)] -> 'a **b** c'"""
    out, open_ = [], set()
    for text, tags in runs:
        want = {t for t in INLINE if t in tags}
        for t in INLINE:                       # fixed order keeps it parseable
            if (t in open_) != (t in want):
                out.append(_MARK[t])
        open_ = want
        out.append(_escape(text))
    for t in INLINE:
        if t in open_:
            out.append(_MARK[t])
    return "".join(out)


def serialize_line(kind, level, checked, num, heading, runs):
    body = serialize_inline(runs)
    if kind:
        pre = "  " * level + {"bullet": "- ",
                              "check": "- [x] " if checked else "- [ ] ",
                              "num": f"{num}. "}[kind]
        return pre + body
    if heading:
        return "#" * heading + " " + body
    if _RE_LOOKS_LIKE_MARKER.match(body):
        body = "\\" + body                     # keep it a plain line
    return body


def md_to_plain(md, whatsapp=False):
    """Formatted note -> plain text. whatsapp=True keeps bold/italic/strike
    using WhatsApp's *bold* _italic_ ~strike~ style."""
    lines = []
    for raw in md.split("\n"):
        info = parse_line(raw)
        if whatsapp:
            body = ""
            for text, tags in info["segs"]:
                w = text
                if "bold" in tags: w = f"*{w}*"
                if "italic" in tags: w = f"_{w}_"
                if "strike" in tags: w = f"~{w}~"
                body += w
        else:
            body = "".join(t for t, _ in info["segs"])
        if info["kind"]:
            pre = "    " * info["level"] + {
                "bullet": "• ",
                "check": "☑ " if info["checked"] else "☐ ",
                "num": f"{info['num']}. "}[info["kind"]]
            lines.append(pre + body)
        elif info["heading"] and whatsapp and body.strip():
            lines.append(f"*{body}*" if "*" not in body else body)
        else:
            lines.append(body)
    return "\n".join(lines)


def plain_to_md(text):
    """Old plain-text notes: keep every character exactly as typed."""
    return "\n".join(serialize_line(None, 0, False, 1, 0, [(ln, set())])
                     for ln in text.split("\n"))


def make_prefix(kind, level, checked=False, num=1):
    if kind == "bullet":
        return BULLETS[level] + " "
    if kind == "check":
        return (CHECKED if checked else UNCHECKED) + " "
    return f"{num}. "


# ----------------------------------------------------------------- editor --

class _Busy:
    def __init__(self, ed): self.ed = ed
    def __enter__(self): self.ed._busy += 1
    def __exit__(self, *a): self.ed._busy -= 1


class RichEditor:
    """Wraps a Gtk.TextView and turns it into a small rich-text editor.

    on_commit(markdown) is called (debounced) whenever content or
    formatting changes.
    """

    BASE_PT = 11.0

    def __init__(self, textview, markdown, on_commit, zoom=1.0):
        self.tv = textview
        self.buf = textview.get_buffer()
        self.on_commit = on_commit
        self._busy = 0
        self._restoring = False
        self._active = None          # pending inline tags typed at _active_pos
        self._active_pos = None
        self._dirty = set()
        self._norm_id = None
        self._commit_id = None
        self.history, self.hidx = [], -1
        self.zoom = zoom
        self._css = Gtk.CssProvider()
        textview.get_style_context().add_provider(
            self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.set_zoom(zoom, notify=False)

        self._make_tags()
        self.load(markdown)
        self._snapshot(force=True)

        b = self.buf
        b.connect_after("insert-text", self._after_insert)
        b.connect_after("delete-range", self._after_delete)
        b.connect("changed", lambda *_: self._schedule_commit())
        b.connect("mark-set", self._on_mark_set)
        tv = self.tv
        tv.connect("key-press-event", self._on_key)
        tv.connect("paste-clipboard", self._on_paste_signal)   # right-click > Paste
        tv.connect("button-press-event", self._on_click)
        tv.connect("motion-notify-event", self._on_motion)
        tv.add_events(Gdk.EventMask.POINTER_MOTION_MASK)

    # ---------------------------------------------------------- tags --
    def _make_tags(self):
        b = self.buf
        T = self.t = {}
        for lvl in range(MAX_LEVEL + 1):
            T[f"m{lvl}"] = b.create_tag(f"m{lvl}", left_margin=16 + 16 * lvl,
                                        indent=-13)
        T["h1"] = b.create_tag("h1", scale=1.45, weight=Pango.Weight.HEAVY,
                               pixels_above_lines=2, pixels_below_lines=2)
        T["h2"] = b.create_tag("h2", scale=1.2, weight=Pango.Weight.BOLD,
                               pixels_above_lines=2)
        T["bold"] = b.create_tag("bold", weight=Pango.Weight.BOLD)
        T["italic"] = b.create_tag("italic", style=Pango.Style.ITALIC)
        T["strike"] = b.create_tag("strike", strikethrough=True)
        T["prefix"] = b.create_tag("prefix", foreground="#555555")
        for k in LIST_KINDS:
            T["pfx-" + k] = b.create_tag("pfx-" + k)
        for lvl in range(MAX_LEVEL + 1):
            T[f"lvl{lvl}"] = b.create_tag(f"lvl{lvl}")
        T["done"] = b.create_tag("done", strikethrough=True, foreground="#8a8a8a")
        T["link"] = b.create_tag("link", foreground="#1a5fb4",
                                 underline=Pango.Underline.SINGLE)

    # ------------------------------------------------------ iter help --
    def _it(self, off):
        return self.buf.get_iter_at_offset(off)

    def _line_start(self, n):
        it = self.buf.get_iter_at_line(n)
        return it[1] if isinstance(it, tuple) else it

    def _line_end(self, n):
        it = self._line_start(n)
        if not it.ends_line():
            it.forward_to_line_end()
        return it

    def _prefix_len(self, n):
        it, count = self._line_start(n), 0
        while not it.ends_line() and it.has_tag(self.t["prefix"]):
            count += 1
            it.forward_char()
        return count

    def _content_start(self, n):
        it = self._line_start(n)
        it.forward_chars(self._prefix_len(n))
        return it

    def line_info(self, n):
        s = self._line_start(n)
        plen = self._prefix_len(n)
        info = {"kind": None, "level": 0, "checked": False, "heading": 0,
                "plen": plen}
        if plen:
            for k in LIST_KINDS:
                if s.has_tag(self.t["pfx-" + k]):
                    info["kind"] = k
            for lvl in range(MAX_LEVEL + 1):
                if s.has_tag(self.t[f"lvl{lvl}"]):
                    info["level"] = lvl
            info["checked"] = info["kind"] == "check" and s.get_char() == CHECKED
        else:
            if not s.ends_line():
                if s.has_tag(self.t["h1"]):
                    info["heading"] = 1
                elif s.has_tag(self.t["h2"]):
                    info["heading"] = 2
        return info

    def _cursor(self):
        return self.buf.get_iter_at_mark(self.buf.get_insert())

    def _sel_lines(self):
        sel = self.buf.get_selection_bounds()
        if sel:
            return range(sel[0].get_line(), sel[1].get_line() + 1)
        n = self._cursor().get_line()
        return range(n, n + 1)

    # ----------------------------------------------------- load / save --
    def load(self, md):
        with _Busy(self):
            b = self.buf
            b.set_text("")
            lines = md.split("\n")
            for i, raw in enumerate(lines):
                info = parse_line(raw)
                end = b.get_end_iter()
                if info["kind"]:
                    b.insert_with_tags_by_name(
                        end, make_prefix(info["kind"], info["level"],
                                         info["checked"], info["num"]),
                        "prefix", "pfx-" + info["kind"], f"lvl{info['level']}")
                for text, tags in info["segs"]:
                    names = list(tags)
                    if info["heading"]:
                        names.append(f"h{info['heading']}")
                    end = b.get_end_iter()
                    if names:
                        b.insert_with_tags_by_name(end, text, *names)
                    else:
                        b.insert(end, text)
                if i < len(lines) - 1:
                    b.insert(b.get_end_iter(), "\n")
            for n in range(b.get_line_count()):
                self._normalize_line(n)
            self._renumber()
            b.place_cursor(b.get_end_iter())

    def to_markdown(self):
        out = []
        for n in range(self.buf.get_line_count()):
            info = self.line_info(n)
            it, end = self._content_start(n), self._line_end(n)
            runs, cur_tags, cur = [], None, []
            while it.compare(end) < 0:
                tags = frozenset(t for t in INLINE if it.has_tag(self.t[t]))
                if tags != cur_tags and cur:
                    runs.append(("".join(cur), cur_tags))
                    cur = []
                cur_tags = tags
                cur.append(it.get_char())
                it.forward_char()
            if cur:
                runs.append(("".join(cur), cur_tags))
            num = 1
            if info["kind"] == "num":
                pre = self.buf.get_text(self._line_start(n),
                                        self._content_start(n), True)
                num = int(re.sub(r"\D", "", pre) or 1)
            out.append(serialize_line(info["kind"], info["level"],
                                      info["checked"], num, info["heading"], runs))
        return "\n".join(out)

    # ---------------------------------------------------- normalizing --
    def _queue_normalize(self, lines):
        self._dirty.update(lines)
        if self._norm_id is None:
            self._norm_id = GLib.idle_add(self._run_normalize)

    def _run_normalize(self):
        self._norm_id = None
        dirty, self._dirty = self._dirty, set()
        with _Busy(self):
            count = self.buf.get_line_count()
            for n in sorted(dirty):
                if 0 <= n < count:
                    self._normalize_line(n)
            self._renumber()
        self._schedule_commit()
        return False

    def _set_prefix(self, n, kind, level=0, checked=False, num=1):
        """Replace line n's list marker (kind=None removes it)."""
        with _Busy(self):
            plen = self._prefix_len(n)
            if plen:
                s = self._line_start(n)
                e = s.copy(); e.forward_chars(plen)
                self.buf.delete(s, e)
            if kind:
                s = self._line_start(n)
                self.buf.remove_tag(self.t["h1"], s, self._line_end(n))
                s = self._line_start(n)
                self.buf.remove_tag(self.t["h2"], s, self._line_end(n))
                s = self._line_start(n)
                self.buf.insert_with_tags_by_name(
                    s, make_prefix(kind, level, checked, num),
                    "prefix", "pfx-" + kind, f"lvl{level}")
            self._normalize_line(n)

    def _normalize_line(self, n):
        b, T = self.buf, self.t
        with _Busy(self):
            # 1. list markers that ended up in the middle of a line: drop them
            while True:
                it, end = self._content_start(n), self._line_end(n)
                stray = None
                while it.compare(end) < 0:
                    if it.has_tag(T["prefix"]):
                        stray = it.get_offset()
                        break
                    it.forward_char()
                if stray is None:
                    break
                b.delete(self._it(stray), self._it(stray + 1))

            info = self.line_info(n)
            # 2. marker damaged (e.g. its space deleted): rebuild it
            if info["kind"]:
                cur = b.get_text(self._line_start(n), self._content_start(n), True)
                num = int(re.sub(r"\D", "", cur) or 1)
                want = make_prefix(info["kind"], info["level"], info["checked"], num)
                if cur != want:
                    s = self._line_start(n)
                    e = s.copy(); e.forward_chars(info["plen"])
                    b.delete(s, e)
                    b.insert_with_tags_by_name(
                        self._line_start(n), want, "prefix",
                        "pfx-" + info["kind"], f"lvl{info['level']}")
                    info = self.line_info(n)

            ls, le = self._line_start(n), self._line_end(n)
            for lvl in range(MAX_LEVEL + 1):
                b.remove_tag(T[f"m{lvl}"], self._line_start(n), self._line_end(n))
            for name in ("done", "link"):
                b.remove_tag(T[name], self._line_start(n), self._line_end(n))
            cs = self._content_start(n)
            if info["kind"]:
                # 3. hanging indent for list items
                b.apply_tag(T[f"m{info['level']}"], self._line_start(n),
                            self._line_end(n))
                for name in INLINE + HEADINGS:
                    b.remove_tag(T[name], self._line_start(n),
                                 self._content_start(n))
                for name in HEADINGS:
                    b.remove_tag(T[name], self._line_start(n), self._line_end(n))
                if info["checked"]:
                    b.apply_tag(T["done"], self._content_start(n), self._line_end(n))
            else:
                # 4. a heading covers its whole line
                h = info["heading"]
                for name in HEADINGS:
                    b.remove_tag(T[name], self._line_start(n), self._line_end(n))
                if h:
                    b.apply_tag(T[f"h{h}"], self._line_start(n), self._line_end(n))
            # 5. web links
            cs = self._content_start(n)
            text = b.get_text(cs, self._line_end(n), True)
            base = cs.get_offset()
            for m in RE_URL.finditer(text):
                b.apply_tag(T["link"], self._it(base + m.start()),
                            self._it(base + m.end()))

    def _renumber(self):
        b = self.buf
        counters = {}
        with _Busy(self):
            for n in range(b.get_line_count()):
                info = self.line_info(n)
                lvl = info["level"]
                if info["kind"] == "num":
                    for k in [k for k in counters if k > lvl]:
                        del counters[k]
                    counters[lvl] = counters.get(lvl, 0) + 1
                    want = f"{counters[lvl]}. "
                    cur = b.get_text(self._line_start(n), self._content_start(n), True)
                    if cur != want:
                        s = self._line_start(n)
                        e = s.copy(); e.forward_chars(info["plen"])
                        b.delete(s, e)
                        b.insert_with_tags_by_name(self._line_start(n), want,
                                                   "prefix", "pfx-num", f"lvl{lvl}")
                elif info["kind"]:
                    for k in [k for k in counters if k >= lvl]:
                        del counters[k]
                else:
                    counters.clear()

    # ------------------------------------------------- buffer signals --
    def _inherited(self, it):
        """Inline formatting of the character just before `it`."""
        if it.starts_line():
            return set()
        prev = it.copy(); prev.backward_char()
        if prev.has_tag(self.t["prefix"]):
            return set()
        return {t for t in INLINE + HEADINGS if prev.has_tag(self.t[t])}

    def _after_insert(self, buf, end, text, length):
        if self._busy:
            return
        end_off = end.get_offset()
        start_off = end_off - len(text)
        if self._active is not None and self._active_pos == start_off:
            tags = set(self._active)
            self._active_pos = end_off
        else:
            self._active = None
            tags = self._inherited(self._it(start_off))
        with _Busy(self):
            for name in INLINE + HEADINGS + ("prefix",):
                buf.remove_tag(self.t[name], self._it(start_off), self._it(end_off))
            for name in tags:
                buf.apply_tag(self.t[name], self._it(start_off), self._it(end_off))
        first = self._it(start_off).get_line()
        last = self._it(end_off).get_line()
        self._queue_normalize(range(first, last + 1))

    def _after_delete(self, buf, start, end):
        if self._busy:
            return
        self._queue_normalize([start.get_line()])

    def _on_mark_set(self, buf, it, mark):
        # Keep the cursor out of list markers. Checked a moment later, so a
        # selection being made (Ctrl+A, mouse drag) is never cut short.
        if self._busy or mark != buf.get_insert():
            return
        if getattr(self, "_cursor_check", None) is None:
            self._cursor_check = GLib.idle_add(self._fix_cursor)

    def _fix_cursor(self):
        self._cursor_check = None
        buf = self.buf
        if buf.get_has_selection():
            return False
        it = self._cursor()
        n = it.get_line()
        plen = self._prefix_len(n)
        if plen and it.get_line_offset() < plen:
            with _Busy(self):
                buf.place_cursor(self._content_start(n))
        return False

    # ------------------------------------------------------ actions --
    def toggle_inline(self, name):
        b = self.buf
        sel = b.get_selection_bounds()
        if sel:
            so, eo = sel[0].get_offset(), sel[1].get_offset()
            it, has_all = self._it(so), True
            while it.get_offset() < eo:
                if (not it.has_tag(self.t["prefix"]) and it.get_char() != "\n"
                        and not it.has_tag(self.t[name])):
                    has_all = False
                    break
                it.forward_char()
            with _Busy(self):
                if has_all:
                    b.remove_tag(self.t[name], self._it(so), self._it(eo))
                else:
                    b.apply_tag(self.t[name], self._it(so), self._it(eo))
            self._queue_normalize(range(self._it(so).get_line(),
                                        self._it(eo).get_line() + 1))
        else:
            cur = self._cursor()
            off = cur.get_offset()
            base = (self._active if self._active is not None
                    and self._active_pos == off else self._inherited(cur))
            self._active = set(base) ^ {name}
            self._active_pos = off
        self._schedule_commit()

    def cycle_heading(self):
        self.flush()
        b = self.buf
        lines = list(self._sel_lines())
        first = self.line_info(lines[0])
        new = {0: 1, 1: 2, 2: 0}[first["heading"] if not first["kind"] else 0]
        with _Busy(self):
            for n in lines:
                if self.line_info(n)["kind"]:
                    self._set_prefix(n, None)
                for name in HEADINGS:
                    b.remove_tag(self.t[name], self._line_start(n), self._line_end(n))
                if new and not self._line_start(n).ends_line():
                    b.apply_tag(self.t[f"h{new}"], self._line_start(n),
                                self._line_end(n))
        cur = self._cursor()
        if cur.starts_line() and cur.ends_line():
            # empty line: the heading applies to what is typed next
            self._active = {f"h{new}"} if new else set()
            self._active_pos = cur.get_offset()
        self._queue_normalize(lines)
        self._schedule_commit()

    def toggle_list(self, kind):
        self.flush()
        lines = list(self._sel_lines())
        all_same = all(self.line_info(n)["kind"] == kind for n in lines)
        for n in lines:
            info = self.line_info(n)
            if all_same:
                self._set_prefix(n, None)
            else:
                self._set_prefix(n, kind, info["level"])
        with _Busy(self):
            self._renumber()
        self._place_at_content(self._cursor().get_line())
        self._schedule_commit()

    def change_indent(self, n, delta):
        info = self.line_info(n)
        if not info["kind"]:
            return False
        new = max(0, min(MAX_LEVEL, info["level"] + delta))
        if new != info["level"]:
            self._set_prefix(n, info["kind"], new, info["checked"])
            with _Busy(self):
                self._renumber()
            self._place_at_content(n)
            self._schedule_commit()
        return True

    def move_item(self, n, direction):
        """Move list item n (with its sub-items) up (-1) or down (+1),
        swapping it with the neighbouring item at the same level.
        Returns False when line n is not a list item."""
        if not self.line_info(n)["kind"]:
            return False
        self.flush()
        lines = self.to_markdown().split("\n")
        info = [parse_line(l) for l in lines]
        lvl = info[n]["level"]

        def block_end(i):
            j = i + 1
            while j < len(lines) and info[j]["kind"] and info[j]["level"] > info[i]["level"]:
                j += 1
            return j

        end = block_end(n)
        if direction < 0:
            p = n - 1
            while p >= 0 and info[p]["kind"] and info[p]["level"] > lvl:
                p -= 1
            if p < 0 or not info[p]["kind"] or info[p]["level"] != lvl:
                return True                      # already first in its list
            a, b, c = p, n, end                  # [a,b) above, [b,c) us
            new = lines[:a] + lines[b:c] + lines[a:b] + lines[c:]
            new_n = a
        else:
            if end >= len(lines) or not info[end]["kind"] or info[end]["level"] != lvl:
                return True                      # already last in its list
            c = block_end(end)
            new = lines[:n] + lines[end:c] + lines[n:end] + lines[c:]
            new_n = n + (c - end)
        col = self._cursor().get_line_offset() - self._prefix_len(n)
        self.load("\n".join(new))
        with _Busy(self):
            it = self._content_start(new_n)
            room = self._line_end(new_n).get_offset() - it.get_offset()
            it.forward_chars(max(0, min(col, room)))
            self.buf.place_cursor(it)
        self.tv.scroll_mark_onscreen(self.buf.get_insert())
        self._schedule_commit(now=True)
        return True

    def toggle_check(self, n):
        info = self.line_info(n)
        if info["kind"] != "check":
            return
        self._set_prefix(n, "check", info["level"], not info["checked"])
        self._schedule_commit()

    def _place_at_content(self, n):
        cur = self._cursor()
        if cur.get_line() == n and cur.get_line_offset() >= self._prefix_len(n):
            return
        with _Busy(self):
            self.buf.place_cursor(self._content_start(n))

    def _enter(self):
        b = self.buf
        b.delete_selection(True, True)
        cur = self._cursor()
        n = cur.get_line()
        info = self.line_info(n)
        if self._active is not None and self._active_pos == cur.get_offset():
            carry = set(self._active) - set(HEADINGS)
        else:
            carry = self._inherited(cur) - set(HEADINGS)
        if info["kind"]:
            empty = self._content_start(n).ends_line()
            if empty:                          # Enter on an empty item ends the list
                if info["level"] > 0:
                    self.change_indent(n, -1)
                else:
                    self._set_prefix(n, None)
                    self._place_at_content(n)
                self._schedule_commit()
                return
            with _Busy(self):
                b.insert(self._cursor(), "\n")
            self._set_prefix(n + 1, info["kind"], info["level"], False)
            with _Busy(self):
                self._renumber()
                b.place_cursor(self._content_start(n + 1))
        else:
            with _Busy(self):
                b.insert(self._cursor(), "\n")
        self._active = carry
        self._active_pos = self._cursor().get_offset()
        self._queue_normalize([n, n + 1])
        self.tv.scroll_mark_onscreen(b.get_insert())

    # ----------------------------------------------------- auto arrows --
    def _auto_arrow(self, key):
        """Typing -> gives → and <- gives ← (Ctrl+Z brings back the plain text)."""
        b = self.buf
        if b.get_has_selection():
            return False
        cur = self._cursor()
        if cur.starts_line():
            return False
        prev = cur.copy(); prev.backward_char()
        if prev.has_tag(self.t["prefix"]):
            return False
        pair = {(Gdk.KEY_greater, "-"): "→", (Gdk.KEY_minus, "<"): "←"}
        arrow = pair.get((key, prev.get_char()))
        if not arrow:
            return False
        self.flush()                     # so Ctrl+Z can undo just the arrow
        b.begin_user_action()
        b.delete(prev, cur)
        b.insert(self._cursor(), arrow)   # takes the formatting around it
        b.end_user_action()
        # remember it, so an immediate Ctrl+Z turns → back into ->
        self._last_arrow = (self._cursor().get_offset(), arrow,
                            "->" if arrow == "→" else "<-")
        return True

    def _undo_arrow(self):
        info = getattr(self, "_last_arrow", None)
        self._last_arrow = None
        if not info:
            return False
        pos, arrow, original = info
        cur = self._cursor()
        if self.buf.get_has_selection() or cur.get_offset() != pos:
            return False
        prev = cur.copy(); prev.backward_char()
        if prev.get_char() != arrow:
            return False
        self.buf.delete(prev, cur)
        self.buf.insert(self._cursor(), original)
        self._last_arrow = None
        return True

    # ----------------------------------------------------------- paste --
    def _on_paste_signal(self, tv):
        tv.stop_emission_by_name("paste-clipboard")
        self.paste()

    def _clipboard_text(self):
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        return cb.wait_for_text()

    def paste(self, plain=False):
        """Ctrl+V: Markdown in the pasted text becomes real formatting.
        Ctrl+Shift+V (plain=True): text only, no formatting, no symbols."""
        text = self._clipboard_text()
        if not text:
            return
        self.flush()
        b = self.buf
        b.delete_selection(True, True)
        raw_lines = text.replace("\r\n", "\n").split("\n")
        if raw_lines and raw_lines[-1] == "" and len(raw_lines) > 1:
            raw_lines.pop()                      # ignore the final line break
        lines = []
        for raw in raw_lines:
            info = parse_pasted_line(raw)
            prev = lines[-1] if lines else None
            # a plain line right under a list item continues that item
            if (not plain and prev and prev["kind"] and not info["kind"]
                    and not info["heading"] and raw.strip()):
                prev["segs"] = prev["segs"] + [(" ", frozenset())] + \
                    parse_inline_pasted(raw.strip())
                continue
            lines.append(info)
        if plain:
            for info in lines:
                info.update(kind=None, heading=0, level=0)
                info["segs"] = [("".join(t for t, _ in info["segs"]), frozenset())]
        start_line = self._cursor().get_line()
        with _Busy(self):
            for i, info in enumerate(lines):
                if i > 0:
                    b.insert(self._cursor(), "\n")
                n = self._cursor().get_line()
                line_empty = self._content_start(n).ends_line() and \
                    self._cursor().equal(self._content_start(n))
                if info["kind"] and (i > 0 or line_empty):
                    self._set_prefix(n, info["kind"], info["level"], info["checked"],
                                     info["num"])
                    b.place_cursor(self._content_start(n))
                elif i > 0 and not plain:
                    self._set_prefix(n, None)       # new line: no list carried over
                    b.place_cursor(self._content_start(n))
                for t, tags in info["segs"]:
                    if not t:
                        continue
                    names = [x for x in tags if x in INLINE]
                    if info["heading"] and not info["kind"]:
                        names.append(f"h{info['heading']}")
                    cur = self._cursor()
                    if names:
                        b.insert_with_tags_by_name(cur, t, *names)
                    else:
                        b.insert(cur, t)
            end_line = self._cursor().get_line()
            for n in range(start_line, end_line + 1):
                self._normalize_line(n)
            self._renumber()
        self._active = None
        self.tv.scroll_mark_onscreen(b.get_insert())
        self._schedule_commit(now=True)

    def _try_shortcut(self):
        """Typing '- ', '[] ', '1. ', '# ' at the start of a line."""
        b = self.buf
        if b.get_has_selection():
            return False
        cur = self._cursor()
        n = cur.get_line()
        if self._prefix_len(n):
            return False
        typed = b.get_text(self._line_start(n), cur, True)
        m = re.fullmatch(r"( *)(-|\*|\[ ?\]|\[[xX]\]|\d+\.|#{1,2})", typed)
        if not m:
            return False
        level = min(len(m.group(1)) // 2, MAX_LEVEL)
        tok = m.group(2)
        with _Busy(self):
            b.delete(self._line_start(n), self._cursor())
        if tok.startswith("#"):
            rest_empty = self._line_start(n).ends_line()
            if rest_empty:
                self._active = {f"h{len(tok)}"}
                self._active_pos = self._cursor().get_offset()
            else:
                with _Busy(self):
                    b.apply_tag(self.t[f"h{len(tok)}"], self._line_start(n),
                                self._line_end(n))
        elif tok in ("-", "*"):
            self._set_prefix(n, "bullet", level)
        elif tok.startswith("["):
            self._set_prefix(n, "check", level, "x" in tok.lower())
        else:
            self._set_prefix(n, "num", level, num=int(tok[:-1]))
        with _Busy(self):
            self._renumber()
        self._place_at_content(n)
        self._queue_normalize([n])
        self._schedule_commit()
        return True

    # ----------------------------------------------------- key / mouse --
    def _on_key(self, tv, ev):
        k = ev.keyval
        ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
        shift = ev.state & Gdk.ModifierType.SHIFT_MASK
        b = self.buf
        if ctrl:
            low = Gdk.keyval_to_lower(k)
            if low == Gdk.KEY_v:
                self.paste(plain=bool(shift)); return True
            if low == Gdk.KEY_b: self.toggle_inline("bold"); return True
            if low == Gdk.KEY_i: self.toggle_inline("italic"); return True
            if low == Gdk.KEY_d: self.toggle_inline("strike"); return True
            if low == Gdk.KEY_h: self.cycle_heading(); return True
            if k in (Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_KP_Up, Gdk.KEY_KP_Down) and not shift:
                if self.buf.get_has_selection():
                    return False
                d = -1 if k in (Gdk.KEY_Up, Gdk.KEY_KP_Up) else 1
                return self.move_item(self._cursor().get_line(), d)
            if low == Gdk.KEY_l: self.toggle_list("check"); return True
            if low == Gdk.KEY_z and not shift:
                if not self._undo_arrow():
                    self.undo()
                return True
            if (low == Gdk.KEY_z and shift) or low == Gdk.KEY_y:
                self.redo(); return True
            if k in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
                self.set_zoom(self.zoom + 0.1); return True
            if k in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract, Gdk.KEY_underscore):
                self.set_zoom(self.zoom - 0.1); return True
            if k in (Gdk.KEY_0, Gdk.KEY_KP_0):
                self.set_zoom(1.0); return True
            return False
        if not (ctrl or k in (Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Control_L,
                              Gdk.KEY_Control_R)):
            self._last_arrow = None
        if k in (Gdk.KEY_greater, Gdk.KEY_minus) and self._auto_arrow(k):
            return True
        if k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not shift:
            self._enter(); return True
        if k == Gdk.KEY_space and self._try_shortcut():
            return True
        if k in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            n = self._cursor().get_line()
            delta = -1 if (shift or k == Gdk.KEY_ISO_Left_Tab) else 1
            if self.change_indent(n, delta) or k == Gdk.KEY_ISO_Left_Tab:
                return True
            return False
        if not b.get_has_selection():
            cur = self._cursor()
            n = cur.get_line()
            plen = self._prefix_len(n)
            at_content_start = plen and cur.get_line_offset() == plen
            if k == Gdk.KEY_BackSpace and at_content_start:
                info = self.line_info(n)
                if info["level"] > 0:
                    self.change_indent(n, -1)
                else:
                    self._set_prefix(n, None)
                    self._schedule_commit()
                return True
            if k in (Gdk.KEY_Left, Gdk.KEY_KP_Left) and at_content_start and not shift:
                if n > 0:
                    b.place_cursor(self._line_end(n - 1))
                return True
        return False

    def _iter_at_event(self, ev):
        bx, by = self.tv.window_to_buffer_coords(Gtk.TextWindowType.TEXT,
                                                 int(ev.x), int(ev.y))
        res = self.tv.get_iter_at_location(bx, by)
        if isinstance(res, tuple):
            ok, it = res
            return it if ok else None
        return res

    def _on_click(self, tv, ev):
        if ev.button != 1 or ev.type != Gdk.EventType.BUTTON_PRESS:
            return False
        it = self._iter_at_event(ev)
        if it is None:
            return False
        if it.has_tag(self.t["pfx-check"]):
            self.toggle_check(it.get_line())
            return True
        if it.has_tag(self.t["link"]) and ev.state & Gdk.ModifierType.CONTROL_MASK:
            s, e = it.copy(), it.copy()
            if not s.starts_tag(self.t["link"]):
                s.backward_to_tag_toggle(self.t["link"])
            e.forward_to_tag_toggle(self.t["link"])
            url = self.buf.get_text(s, e, True)
            if url.startswith("www."):
                url = "https://" + url
            try:
                Gtk.show_uri_on_window(self.tv.get_toplevel(), url, ev.time)
            except GLib.Error:
                pass
            return True
        return False

    def _on_motion(self, tv, ev):
        it = self._iter_at_event(ev)
        hand = it is not None and (
            it.has_tag(self.t["pfx-check"]) or
            (it.has_tag(self.t["link"]) and ev.state & Gdk.ModifierType.CONTROL_MASK))
        win = tv.get_window(Gtk.TextWindowType.TEXT)
        if win:
            win.set_cursor(Gdk.Cursor.new_from_name(
                tv.get_display(), "pointer" if hand else "text"))
        return False

    # ------------------------------------------------------------ zoom --
    def set_zoom(self, z, notify=True):
        self.zoom = round(max(0.6, min(2.5, z)), 2)
        self._css.load_from_data(
            f"textview, textview text {{ font-size: {self.BASE_PT * self.zoom:.1f}pt; }}"
            .encode())
        if notify:
            self._schedule_commit(now=True)

    # ------------------------------------------------- commit / undo --
    def _schedule_commit(self, now=False):
        if self._busy and not now:
            return
        if self._commit_id:
            GLib.source_remove(self._commit_id)
            self._commit_id = None
        if now:
            self._commit()
        else:
            self._commit_id = GLib.timeout_add(700, self._commit)

    def flush(self):
        """Finish any pending work right now (before undo, formatting, ...)."""
        if self._norm_id is not None:
            GLib.source_remove(self._norm_id)
            self._run_normalize()
        if self._commit_id:
            GLib.source_remove(self._commit_id)
            self._commit_id = None
            self._commit()

    def _commit(self):
        self._commit_id = None
        md = self.to_markdown()
        if not self._restoring:
            self._snapshot()
        self.on_commit(md)
        return False

    def _snapshot(self, force=False):
        md = self.to_markdown()
        pos = self._cursor().get_offset()
        if not force and self.hidx >= 0 and self.history[self.hidx][0] == md:
            self.history[self.hidx] = (md, pos)
            return
        del self.history[self.hidx + 1:]
        self.history.append((md, pos))
        if len(self.history) > 200:
            self.history.pop(0)
        self.hidx = len(self.history) - 1

    def _restore(self, idx):
        md, pos = self.history[idx]
        self.hidx = idx
        self._restoring = True
        self.load(md)
        with _Busy(self):
            self.buf.place_cursor(self._it(min(pos, self.buf.get_char_count())))
        self._active = None
        self.on_commit(md)
        self._restoring = False
        self.tv.scroll_mark_onscreen(self.buf.get_insert())

    def undo(self):
        self.flush()
        if self.hidx > 0:
            self._restore(self.hidx - 1)

    def redo(self):
        self.flush()
        if self.hidx < len(self.history) - 1:
            self._restore(self.hidx + 1)

    def plain_text(self, whatsapp=True):
        self.flush()
        return md_to_plain(self.to_markdown(), whatsapp=whatsapp)
