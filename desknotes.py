#!/usr/bin/env python3
"""
Desk Notes - a small sticky-notes app for Ubuntu.

It runs through XWayland ("old mode") on purpose, so that notes can
remember exactly where they were on the screen and stay on top.

Windows:
  * Notes Manager - lists every note; show/hide/delete them. Closing it
    only hides it (Desk Notes leaves the dock), open notes stay on screen.
  * Note windows  - the sticky notes themselves. Their x button hides the
    note; it is not deleted.
"""

import os

# Must happen before GTK loads: ask for the X11 (XWayland) backend.
os.environ["GDK_BACKEND"] = "x11"

import json
import sys
import time
import uuid

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gio, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from richtext import RichEditor, md_to_plain, plain_to_md  # noqa: E402
from icons import icon_image  # noqa: E402

APP_ID = "io.anit.DeskNotes"
DATA_DIR = os.path.join(GLib.get_user_data_dir(), "desknotes")
DATA_FILE = os.path.join(DATA_DIR, "notes.json")

# name: (note background, header strip)
COLORS = {
    "yellow": ("#fff7b1", "#f5e57a"),
    "pink":   ("#ffd6e5", "#f7b3cc"),
    "green":  ("#d6f5d6", "#b0e3b0"),
    "blue":   ("#d6e9ff", "#b0d0f5"),
    "purple": ("#e8dcff", "#cfbdf5"),
    "orange": ("#ffe2c2", "#f7c795"),
    "white":  ("#fafafa", "#e3e3e3"),
}
DEFAULT_COLOR = "yellow"

SECTIONS = [("work", "Work", "💼"), ("personal", "Personal", "🏠")]
SECTION_NAMES = {k: name for k, name, _ in SECTIONS}

CSS = """
.dn-header { padding: 2px 4px; }
.dn-header button {
    padding: 0px 4px; min-height: 20px; min-width: 20px;
    border: none; background: transparent; box-shadow: none;
    color: #333333;
}
.dn-header button:hover { background: rgba(0,0,0,0.10); }
.dn-text, .dn-text text {
    color: #222222;
    font-size: 11pt;
    caret-color: #222222;
}
.dn-text { padding: 0; }
.dn-grip { color: #333333; padding: 0 2px 1px 0; }
.dn-toolbar { padding: 1px 4px; }
.dn-toolbar button {
    padding: 0px 3px; min-height: 22px; min-width: 22px;
    border: none; background: transparent; box-shadow: none; color: #333333;
}
.dn-toolbar button:hover { background: rgba(0,0,0,0.10); }
.dn-swatch { min-width: 22px; min-height: 22px; border-radius: 11px;
             border: 1px solid rgba(0,0,0,0.25); }
.dn-dot { min-width: 14px; min-height: 14px; border-radius: 7px;
          border: 1px solid rgba(0,0,0,0.25); }
.dn-row { padding: 6px 10px 6px 26px; }
.dn-section { padding: 8px 10px; font-weight: bold; background: rgba(127,127,127,0.10); }
.dn-section-count { opacity: 0.55; font-weight: normal; font-size: 9pt; }
.dn-row-title { font-weight: bold; }
.dn-row-sub { opacity: 0.6; font-size: 9pt; }
.dn-empty { opacity: 0.6; padding: 30px; }
.dn-flat { border: none; background: transparent; box-shadow: none; padding: 2px 6px; }
.dn-flat:hover { background: rgba(127,127,127,0.18); }
"""
for _name, (_bg, _hd) in COLORS.items():
    CSS += f"""
.dn-{_name} .dn-header, .dn-{_name} .dn-toolbar {{ background: {_hd}; }}
.dn-{_name} .dn-body, .dn-{_name} .dn-body scrolledwindow, .dn-{_name} .dn-body viewport, .dn-{_name} .dn-text, .dn-{_name} .dn-text text, .dn-{_name} .dn-text border {{ background: {_bg}; background-color: {_bg}; }}
.dn-swatch-{_name} {{ background: {_bg}; }}
.dn-dot-{_name} {{ background: {_hd}; }}
"""


def note_plain(note):
    """The note's text without formatting marks."""
    text = note.get("text", "")
    return md_to_plain(text) if note.get("format") == "md" else text


def flat_button(label, tip):
    """A small borderless button that shows text/emoji (always renders,
    unlike theme icons that may be missing)."""
    b = Gtk.Button(label=label)
    b.set_relief(Gtk.ReliefStyle.NONE)
    b.set_tooltip_text(tip)
    b.set_can_focus(False)
    b.get_style_context().add_class("dn-flat")
    return b


# ---------------------------------------------------------------- storage --

class Store:
    def __init__(self):
        self.notes = {}           # id -> note dict (kept in creation order)
        self.ui = {"collapsed": []}   # manager settings (collapsed sections)
        self._save_pending = None
        self.on_change = None     # called after any change (manager refresh)
        self.load()

    def load(self):
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                data = json.load(f)
            self.ui.update(data.get("ui", {}))
            for n in data.get("notes", []):
                n.setdefault("hidden", False)
                n.setdefault("all_workspaces", False)
                n.setdefault("created", time.time())
                if n.get("section") not in SECTION_NAMES:
                    n["section"] = "work"
                self.notes[n["id"]] = n
        except FileNotFoundError:
            pass
        except Exception as e:  # damaged file: keep a copy, start fresh
            print("Could not read notes:", e, file=sys.stderr)
            try:
                os.replace(DATA_FILE, DATA_FILE + f".broken-{int(time.time())}")
            except OSError:
                pass

    def save_now(self):
        if self._save_pending:
            GLib.source_remove(self._save_pending)
            self._save_pending = None
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 3, "ui": self.ui,
                       "notes": list(self.notes.values())}, f,
                      indent=2, ensure_ascii=False)
        os.replace(tmp, DATA_FILE)  # never leaves a half-written file
        return False

    def changed(self):
        """Something changed: save a moment later and tell the manager."""
        if self._save_pending:
            GLib.source_remove(self._save_pending)
        self._save_pending = GLib.timeout_add(600, self._timer_save)
        if self.on_change:
            self.on_change()

    def _timer_save(self):
        self._save_pending = None
        self.save_now()
        return False

    def new_note(self, x=None, y=None, color=DEFAULT_COLOR, section="work"):
        nid = uuid.uuid4().hex[:12]
        note = {"id": nid, "text": "", "color": color,
                "x": x, "y": y, "w": 260, "h": 240,
                "on_top": False, "all_workspaces": False,
                "hidden": False, "created": time.time(),
                "format": "md", "zoom": 1.0, "toolbar": True,
                "section": section}
        self.notes[nid] = note
        self.changed()
        return note

    def delete(self, nid):
        self.notes.pop(nid, None)
        self.changed()
        self.save_now()


# ------------------------------------------------------------- note window --

class NoteWindow(Gtk.Window):
    def __init__(self, app, note):
        super().__init__()
        self.app = app
        self.note = note

        self._update_title()
        self.set_icon_name("desknotes")
        self.set_decorated(False)            # we draw our own small header
        # Notes are normal windows: they show in Alt+Tab, the overview
        # and under the Desk Notes icon in the dock.
        self.set_skip_taskbar_hint(False)
        self.set_skip_pager_hint(False)
        self.set_default_size(note["w"], note["h"])
        self.restore_place()
        self.apply_pin_settings()

        self.get_style_context().add_class("dn-note")
        self._apply_color(note.get("color", DEFAULT_COLOR))

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)

        # ---- header strip (drag handle + buttons)
        header_ev = Gtk.EventBox()
        header_ev.connect("button-press-event", self._on_header_press)
        header = Gtk.Box(spacing=2)
        header.get_style_context().add_class("dn-header")
        header_ev.add(header)
        outer.pack_start(header_ev, False, False, 0)

        add_btn = flat_button("➕", "New note  (Ctrl+N)")
        add_btn.connect("clicked", lambda *_: self.app.create_note(near=self))
        header.pack_start(add_btn, False, False, 0)

        color_btn = flat_button("🎨", "Change color")
        color_btn.connect("clicked", self._show_color_popover)
        header.pack_start(color_btn, False, False, 0)

        self.pin_btn = Gtk.Button()
        self.pin_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.pin_btn.get_style_context().add_class("dn-flat")
        self.pin_label = Gtk.Label(label="📌")
        self.pin_btn.add(self.pin_label)
        self.pin_btn.set_can_focus(False)
        self.pin_btn.set_tooltip_text("Always on top / on every workspace")
        self.pin_btn.connect("clicked", self._show_pin_popover)
        header.pack_start(self.pin_btn, False, False, 0)
        self._update_pin_look()

        fmt_btn = flat_button("Aa", "Show / hide the formatting bar")
        fmt_btn.connect("clicked", self._toggle_toolbar)
        header.pack_start(fmt_btn, False, False, 0)

        hide_btn = flat_button("✕", "Hide this note (it stays in the Notes Manager)")
        hide_btn.connect("clicked", lambda *_: self.app.hide_note(self.note["id"]))
        header.pack_end(hide_btn, False, False, 0)

        mgr_btn = flat_button("☰", "Open Notes Manager")
        mgr_btn.connect("clicked", lambda *_: self.app.show_manager())
        header.pack_end(mgr_btn, False, False, 0)

        # ---- formatting bar
        self.toolbar = Gtk.Box(spacing=0)
        self.toolbar.get_style_context().add_class("dn-toolbar")
        outer.pack_start(self.toolbar, False, False, 0)

        # ---- text area
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.get_style_context().add_class("dn-body")
        outer.pack_start(body, True, True, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.overlay = Gtk.Overlay()
        self.overlay.add(scroller)
        body.pack_start(self.overlay, True, True, 0)

        self.textview = Gtk.TextView()
        self.textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.textview.get_style_context().add_class("dn-text")
        scroller.add(self.textview)
        md = note.get("text", "")
        if note.get("format") != "md":
            md = plain_to_md(md)          # older plain-text note
        self.editor = RichEditor(self.textview, md, self._on_commit,
                                 zoom=note.get("zoom", 1.0))
        self._build_toolbar()

        # ---- resize grip, floating in the bottom-right corner
        grip_ev = Gtk.EventBox()
        grip_ev.set_visible_window(False)
        grip_ev.set_halign(Gtk.Align.END)
        grip_ev.set_valign(Gtk.Align.END)
        grip_ev.set_tooltip_text("Drag to resize")
        grip_lbl = Gtk.Label(label="◢")
        grip_lbl.set_opacity(0.45)
        grip_lbl.get_style_context().add_class("dn-grip")
        grip_ev.add(grip_lbl)
        grip_ev.connect("button-press-event", self._on_grip_press)
        grip_ev.connect("realize", lambda w: w.get_window().set_cursor(
            Gdk.Cursor.new_from_name(w.get_display(), "se-resize")))
        self.overlay.add_overlay(grip_ev)
        # inner spacing (set here, not in CSS: CSS padding leaves an
        # unpainted strip on the left with dark themes)
        self.textview.set_left_margin(8)
        self.textview.set_right_margin(8)
        self.textview.set_top_margin(6)
        self.textview.set_bottom_margin(14)   # last line never hides under the grip

        self.connect("configure-event", self._on_configure)
        self.connect("key-press-event", self._on_key)
        # Alt+F4 or similar: hide instead of destroying
        self.connect("delete-event", self._on_delete_event)

        outer.show_all()

    # -- placement and pin settings (re-applied every time it is shown)
    def restore_place(self):
        if self.note.get("x") is not None and self.note.get("y") is not None:
            self.move(self.note["x"], self.note["y"])  # works because of XWayland

    def apply_pin_settings(self):
        self.set_keep_above(bool(self.note.get("on_top")))
        if self.note.get("all_workspaces"):
            self.stick()
        else:
            self.unstick()

    def reveal(self):
        self.restore_place()
        self.apply_pin_settings()
        self.show()
        self.present()

    # -- helpers
    def _apply_color(self, name):
        ctx = self.get_style_context()
        for c in COLORS:
            ctx.remove_class(f"dn-{c}")
        if name not in COLORS:
            name = DEFAULT_COLOR
        ctx.add_class(f"dn-{name}")

    def _update_pin_look(self):
        on = self.note.get("on_top") or self.note.get("all_workspaces")
        self.pin_label.set_opacity(1.0 if on else 0.35)

    # -- events
    def _on_header_press(self, widget, event):
        if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
            self.begin_move_drag(event.button, int(event.x_root),
                                 int(event.y_root), event.time)
            return True
        return False

    def _on_grip_press(self, widget, event):
        if event.button == 1:
            self.begin_resize_drag(Gdk.WindowEdge.SOUTH_EAST, event.button,
                                   int(event.x_root), int(event.y_root), event.time)
            return True
        return False

    def _on_configure(self, widget, event):
        if not self.get_visible():
            return False
        x, y = self.get_position()
        w, h = self.get_size()
        if (self.note.get("x"), self.note.get("y"),
                self.note.get("w"), self.note.get("h")) != (x, y, w, h):
            self.note.update({"x": x, "y": y, "w": w, "h": h})
            self.app.store.changed()
        return False

    def _update_title(self):
        """Name the window after the note's first line, so notes are
        easy to tell apart in Alt+Tab."""
        first = next((ln.strip(" •◦▪☐☑") for ln in note_plain(self.note).splitlines()
                      if ln.strip()), "")
        if len(first) > 40:
            first = first[:40] + "…"
        self.set_title(first or "Empty note")

    def _on_commit(self, md):
        changed = (self.note.get("text") != md or self.note.get("format") != "md"
                   or self.note.get("zoom") != self.editor.zoom)
        self.note["text"] = md
        self.note["format"] = "md"
        self.note["zoom"] = self.editor.zoom
        self._update_title()
        if changed:
            self.app.store.changed()

    def _build_toolbar(self):
        ed = self.editor

        def btn(markup, tip, cb):
            b = Gtk.Button()
            lbl = Gtk.Label()
            lbl.set_markup(markup)
            b.add(lbl)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_tooltip_text(tip)
            b.set_can_focus(False)          # keep the cursor/selection in the note
            b.connect("clicked", lambda *_: (cb(), self.textview.grab_focus()))
            self.toolbar.pack_start(b, False, False, 0)
            return b

        btn("<b>B</b>", "Bold  (Ctrl+B)", lambda: ed.toggle_inline("bold"))
        btn("<i>I</i>", "Italic  (Ctrl+I)", lambda: ed.toggle_inline("italic"))
        btn("<s>S</s>", "Strikethrough  (Ctrl+D)", lambda: ed.toggle_inline("strike"))
        btn("<b>H</b>", "Heading: big, small, off  (Ctrl+H, or type # )",
            ed.cycle_heading)
        btn("•", "Bullet list  (type - then space)", lambda: ed.toggle_list("bullet"))
        btn("☐", "Checkbox  (Ctrl+L, or type [] then space)",
            lambda: ed.toggle_list("check"))
        btn("1.", "Numbered list  (type 1. then space)", lambda: ed.toggle_list("num"))
        self.copy_btn = btn("📋", "Copy note as plain text (keeps WhatsApp formatting)",
                            self._copy_plain)
        self.toolbar.show_all()
        self.toolbar.set_no_show_all(True)
        self.toolbar.set_visible(self.note.get("toolbar", True))

    def _toggle_toolbar(self, *_):
        self.note["toolbar"] = not self.note.get("toolbar", True)
        self.toolbar.set_visible(self.note["toolbar"])
        self.app.store.changed()

    def _copy_plain(self):
        text = self.editor.plain_text(whatsapp=True)
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        lbl = self.copy_btn.get_child()
        lbl.set_text("✔")
        GLib.timeout_add(1200, lambda: (lbl.set_text("📋"), False)[1])

    def _show_pin_popover(self, btn):
        pop = Gtk.Popover.new(btn)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(10)

        top = Gtk.CheckButton(label="Always on Top")
        top.set_active(bool(self.note.get("on_top")))
        top.connect("toggled", self._set_on_top)
        box.pack_start(top, False, False, 0)

        allws = Gtk.CheckButton(label="Always on Visible Workspace")
        allws.set_tooltip_text("Show this note on every workspace")
        allws.set_active(bool(self.note.get("all_workspaces")))
        allws.connect("toggled", self._set_all_workspaces)
        box.pack_start(allws, False, False, 0)

        pop.add(box)
        pop.show_all()
        pop.popup()

    def _set_on_top(self, check):
        self.note["on_top"] = check.get_active()
        self.set_keep_above(self.note["on_top"])
        self._update_pin_look()
        self.app.store.changed()

    def _set_all_workspaces(self, check):
        self.note["all_workspaces"] = check.get_active()
        if self.note["all_workspaces"]:
            self.stick()
        else:
            self.unstick()
        self._update_pin_look()
        self.app.store.changed()

    def _show_color_popover(self, btn):
        pop = Gtk.Popover.new(btn)
        row = Gtk.Box(spacing=6)
        row.set_border_width(8)
        for name in COLORS:
            sw = Gtk.Button()
            sw.set_tooltip_text(name.capitalize())
            sw.get_style_context().add_class("dn-swatch")
            sw.get_style_context().add_class(f"dn-swatch-{name}")
            sw.connect("clicked", self._pick_color, name, pop)
            row.pack_start(sw, False, False, 0)
        pop.add(row)
        pop.show_all()
        pop.popup()

    def _pick_color(self, _btn, name, pop):
        self.note["color"] = name
        self._apply_color(name)
        self.app.store.changed()
        pop.popdown()

    def _on_key(self, widget, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and event.keyval in (Gdk.KEY_n, Gdk.KEY_N):
            self.app.create_note(near=self)
            return True
        return False

    def _on_delete_event(self, *_):
        self.app.hide_note(self.note["id"])
        return True  # don't destroy


# ------------------------------------------------------------ notes manager --

# palettes for the Notes Manager (follows Ubuntu's light / dark setting)
MGR_PALETTES = {
    "dark": {"bg": "#262624", "fg": "#f5f4ef", "muted": "#a3a29c",
             "line": "rgba(255,255,255,0.10)", "btn": "rgba(255,255,255,0.22)",
             "hover": "rgba(255,255,255,0.05)", "field": "#1f1e1d",
             "icon": "#c2c0b6"},
    "light": {"bg": "#faf9f5", "fg": "#1f1e1d", "muted": "#73726c",
              "line": "rgba(0,0,0,0.09)", "btn": "rgba(0,0,0,0.22)",
              "hover": "rgba(0,0,0,0.04)", "field": "#ffffff",
              "icon": "#5f5e5a"},
}

MGR_CSS = """
.dn-mgr, .dn-mgr .dn-mgr-body {{ background: {bg}; color: {fg}; }}
.dn-mgr label {{ color: {fg}; }}
.dn-mgr .dn-btn {{
    background: transparent; background-image: none; box-shadow: none;
    border: 1px solid {btn}; border-radius: 8px; color: {fg};
    padding: 6px 10px; min-height: 22px;
}}
.dn-mgr .dn-btn:hover {{ background: {hover}; }}
.dn-mgr .dn-btn label {{ color: {fg}; }}
.dn-mgr entry.dn-search {{
    background: {field}; color: {fg}; box-shadow: none;
    border: 1px solid {line}; border-radius: 8px; padding: 4px 10px; min-height: 30px;
}}
.dn-mgr entry.dn-search image {{ color: {muted}; }}
.dn-mgr list {{ background: transparent; }}
.dn-mgr list row {{ padding: 0; background: transparent; border: none; box-shadow: none; }}
.dn-mgr list row:hover {{ background: {hover}; }}
.dn-mgr .dn-sec {{ padding: 10px 14px; border-top: 1px solid {line}; }}
.dn-mgr .dn-sec-name {{ font-weight: 500; font-size: 11.5pt; }}
.dn-mgr .dn-muted, .dn-mgr .dn-muted label {{ color: {muted}; }}
.dn-mgr .dn-small {{ font-size: 9pt; }}
.dn-mgr .dn-note {{ padding: 6px 10px 6px 46px; }}
.dn-mgr .dn-note-title {{ font-weight: normal; }}
.dn-mgr .dn-icon-btn {{
    background: transparent; background-image: none; border: none; box-shadow: none;
    padding: 3px; min-height: 0; min-width: 0; border-radius: 6px; opacity: 0.65;
}}
.dn-mgr .dn-icon-btn:hover {{ opacity: 1; background: {hover}; }}
.dn-mgr .dn-hint {{ color: {muted}; font-size: 9pt; padding: 8px; border-top: 1px solid {line}; }}
.dn-mgr .dn-dot {{ min-width: 10px; min-height: 10px; border-radius: 5px; border: none; }}
.dn-mgr .dn-hidden-note .dn-note-title, .dn-mgr .dn-hidden-note .dn-dot {{ opacity: 0.5; }}
"""

SECTION_ICONS = {"work": "briefcase", "personal": "home"}


def system_prefers_dark():
    try:
        s = Gio.Settings.new("org.gnome.desktop.interface")
        if s.get_string("color-scheme") == "prefer-dark":
            return True
        if "dark" in s.get_string("gtk-theme").lower():
            return True
    except Exception:
        pass
    return "dark" in os.environ.get("GTK_THEME", "").lower()


class ManagerWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.app = app
        self.set_title("Notes Manager")
        self.set_icon_name("desknotes")
        self.set_default_size(400, 520)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.get_style_context().add_class("dn-mgr")

        self._css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self._css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)
        self._apply_palette()
        try:   # follow Ubuntu if you switch between light and dark
            self._iface = Gio.Settings.new("org.gnome.desktop.interface")
            self._iface.connect("changed::color-scheme",
                                lambda *_: (self._apply_palette(), self.refresh()))
        except Exception:
            self._iface = None

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.get_style_context().add_class("dn-mgr-body")
        self.add(box)

        bar = Gtk.Box(spacing=8)
        bar.set_margin_start(14); bar.set_margin_end(14)
        bar.set_margin_top(14); bar.set_margin_bottom(10)
        bar.set_homogeneous(True)
        for label, cb in (("New note", self._new_note_menu),
                          ("Show all", lambda *_: self.app.show_all_notes()),
                          ("Hide all", lambda *_: self.app.hide_all_notes())):
            b = Gtk.Button(label=label)
            b.get_style_context().add_class("dn-btn")
            b.connect("clicked", cb)
            bar.pack_start(b, True, True, 0)
        box.pack_start(bar, False, False, 0)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search notes")
        self.search.get_style_context().add_class("dn-search")
        self.search.set_margin_start(14); self.search.set_margin_end(14)
        self.search.set_margin_bottom(12)
        self.search.connect("search-changed", lambda *_: self.refresh())
        box.pack_start(self.search, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box.pack_start(scroller, True, True, 0)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.connect("row-activated", self._on_row_activated)
        empty = self.empty_label = Gtk.Label(label="No notes match your search.")
        empty.get_style_context().add_class("dn-muted")
        empty.set_margin_top(30)
        empty.show()
        self.listbox.set_placeholder(empty)
        scroller.add(self.listbox)

        hint = Gtk.Label(label="Closing this window keeps your open notes on screen.")
        hint.get_style_context().add_class("dn-hint")
        box.pack_start(hint, False, False, 0)

        self.connect("delete-event", self._on_close)   # closing only hides
        self._refresh_pending = None
        self.refresh()
        box.show_all()

    # ---------------------------------------------------------- styling --
    def _apply_palette(self):
        self.palette = MGR_PALETTES["dark" if system_prefers_dark() else "light"]
        self._css.load_from_data(MGR_CSS.format(**self.palette).encode())

    def _icon(self, name, size=16, color=None):
        return icon_image(name, color or self.palette["icon"], size,
                          max(1, self.get_scale_factor()))

    def _icon_button(self, name, tip, cb, *args):
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.set_can_focus(False)
        b.set_tooltip_text(tip)
        b.add(self._icon(name))
        b.get_style_context().add_class("dn-icon-btn")
        b.set_valign(Gtk.Align.CENTER)
        b.connect("clicked", cb, *args)
        return b

    # ----------------------------------------------------------- basics --
    def _on_close(self, *_):
        self.app.hide_manager()
        return True

    def schedule_refresh(self):
        if self._refresh_pending:
            return
        self._refresh_pending = GLib.timeout_add(250, self._do_refresh)

    def _do_refresh(self):
        self._refresh_pending = None
        self.refresh()
        return False

    def refresh(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        query = self.search.get_text().strip().lower() if hasattr(self, "search") else ""
        collapsed = self.app.store.ui["collapsed"]
        for key, name, _emoji in SECTIONS:
            notes = [n for n in self.app.store.notes.values()
                     if n.get("section") == key
                     and (not query or query in note_plain(n).lower())]
            if query and not notes:
                continue                     # searching: hide empty sections
            is_open = bool(query) or key not in collapsed
            self.listbox.add(self._make_section_row(key, name, len(notes), is_open))
            if is_open:
                for note in notes:
                    self.listbox.add(self._make_row(note))
        self.listbox.show_all()

    # -------------------------------------------------------------- rows --
    def _make_section_row(self, key, name, count, is_open):
        row = Gtk.ListBoxRow()
        row.note_id = None
        row.section = key
        row.set_tooltip_text("Click to collapse or expand")
        h = Gtk.Box(spacing=10)
        h.get_style_context().add_class("dn-sec")
        row.add(h)
        h.pack_start(self._icon("chevron-down" if is_open else "chevron-right"),
                     False, False, 0)
        h.pack_start(self._icon(SECTION_ICONS[key], 17, self.palette["fg"]),
                     False, False, 0)
        lbl = Gtk.Label(label=name)
        lbl.get_style_context().add_class("dn-sec-name")
        h.pack_start(lbl, False, False, 0)

        add = self._icon_button("plus", f"New {name.lower()} note",
                                lambda *_: self.app.create_note(section=key))
        h.pack_end(add, False, False, 0)
        c = Gtk.Label(label=f"{count} note" + ("" if count == 1 else "s"))
        c.get_style_context().add_class("dn-muted")
        c.get_style_context().add_class("dn-small")
        h.pack_end(c, False, False, 0)
        return row

    def _make_row(self, note):
        row = Gtk.ListBoxRow()
        row.note_id = note["id"]
        row.set_tooltip_text("Click to show this note")
        if note.get("hidden"):
            row.get_style_context().add_class("dn-hidden-note")
        h = Gtk.Box(spacing=10)
        h.get_style_context().add_class("dn-note")
        row.add(h)

        dot = Gtk.Box()
        dot.set_valign(Gtk.Align.CENTER)
        dot.get_style_context().add_class("dn-dot")
        dot.get_style_context().add_class(f"dn-dot-{note.get('color', DEFAULT_COLOR)}")
        h.pack_start(dot, False, False, 0)

        lines = [ln.strip(" •◦▪☐☑") for ln in note_plain(note).splitlines() if ln.strip()]
        title = lines[0] if lines else "Empty note"
        sub = lines[1] if len(lines) > 1 else ""
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        texts.set_valign(Gtk.Align.CENTER)
        t = Gtk.Label(label=title, xalign=0)
        t.set_ellipsize(3)  # Pango.EllipsizeMode.END
        t.get_style_context().add_class("dn-note-title")
        texts.pack_start(t, False, False, 0)
        if sub:
            s = Gtk.Label(label=sub, xalign=0)
            s.set_ellipsize(3)
            s.get_style_context().add_class("dn-muted")
            s.get_style_context().add_class("dn-small")
            texts.pack_start(s, False, False, 0)
        h.pack_start(texts, True, True, 0)

        hidden = note.get("hidden")
        h.pack_start(self._icon_button(
            "eye-off" if hidden else "eye",
            "Hidden. Click to show" if hidden else "On screen. Click to hide",
            self._on_toggle_visible, note["id"]), False, False, 0)
        other = "personal" if note.get("section") == "work" else "work"
        h.pack_start(self._icon_button("arrows-exchange", f"Move to {SECTION_NAMES[other]}",
                                       self._on_move, note["id"], other), False, False, 0)
        h.pack_start(self._icon_button("trash", "Delete this note",
                                       self._on_delete, note["id"]), False, False, 0)
        return row

    def _new_note_menu(self, btn):
        pop = Gtk.Popover.new(btn)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_border_width(6)
        for key, name, _emoji in SECTIONS:
            b = Gtk.ModelButton(text=f"{name} note")
            b.connect("clicked", lambda _b, k=key: self.app.create_note(section=k))
            box.pack_start(b, False, False, 0)
        pop.add(box)
        pop.show_all()
        pop.popup()

    # ----------------------------------------------------------- actions --
    def _on_row_activated(self, listbox, row):
        if row.note_id is None:              # section header: collapse/expand
            if self.search.get_text().strip():
                return
            col = self.app.store.ui["collapsed"]
            if row.section in col:
                col.remove(row.section)
            else:
                col.append(row.section)
            self.app.store.changed()
            self.refresh()
            return
        self.app.show_note(row.note_id)

    def _on_toggle_visible(self, _btn, nid):
        note = self.app.store.notes.get(nid)
        if note is None:
            return
        if note.get("hidden"):
            self.app.show_note(nid, focus=False)
        else:
            self.app.hide_note(nid)
        self.refresh()

    def _on_move(self, _btn, nid, section):
        note = self.app.store.notes.get(nid)
        if note is not None:
            note["section"] = section
            self.app.store.changed()
            self.refresh()

    def _on_delete(self, _btn, nid):
        note = self.app.store.notes.get(nid)
        if note is None:
            return
        if note.get("text", "").strip():
            dlg = Gtk.MessageDialog(
                transient_for=self, modal=True,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.NONE,
                text="Delete this note?")
            dlg.format_secondary_text("This can't be undone.")
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                            "Delete", Gtk.ResponseType.OK)
            dlg.get_widget_for_response(Gtk.ResponseType.OK) \
               .get_style_context().add_class("destructive-action")
            resp = dlg.run()
            dlg.destroy()
            if resp != Gtk.ResponseType.OK:
                return
        self.app.delete_note(nid)


# ------------------------------------------------------------- application --

class DeskNotesApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.store = None
        self.windows = {}     # note id -> NoteWindow (created when first shown)
        self.manager = None
        self._started = False
        self._quitting = False

    def do_startup(self):
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.store = Store()
        self.store.on_change = self._store_changed
        # Keep running while notes are on screen, even with no manager.
        self.hold()

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        background = "--background" in args   # used when starting at login
        new_note = "--new-note" in args        # dock right-click: New Note
        show_all = "--show-all" in args        # dock right-click: Show All Notes

        if not self._started:
            self._started = True
            for note in list(self.store.notes.values()):
                if not note.get("hidden"):
                    self._window_for(note["id"]).reveal()
            if new_note:
                self.create_note()
            elif show_all:
                self.show_all_notes()
            elif not background or not self.store.notes:
                self.show_manager()
            if background:
                self.maybe_quit()
        elif new_note:
            self.create_note()
        elif show_all:
            self.show_all_notes(raise_them=True)
        else:
            # Opened again from the app menu while running: show the manager.
            self.show_manager()
        return 0

    def do_activate(self):
        self.show_manager()

    # -- windows
    def _window_for(self, nid):
        win = self.windows.get(nid)
        if win is None:
            win = NoteWindow(self, self.store.notes[nid])
            self.windows[nid] = win
        return win

    def _store_changed(self):
        if self.manager is not None:
            self.manager.schedule_refresh()

    def show_manager(self):
        if self.manager is None:
            self.manager = ManagerWindow(self)
        self.manager.refresh()
        self.manager.show()
        self.manager.present()

    def hide_manager(self):
        if self.manager is not None:
            self.manager.hide()
        self.maybe_quit()

    def create_note(self, near=None, section="work"):
        x = y = None
        color = DEFAULT_COLOR
        if near is not None:
            nx, ny = near.get_position()
            x, y = nx + 30, ny + 30
            color = near.note.get("color", DEFAULT_COLOR)
            section = near.note.get("section", section)
        note = self.store.new_note(x, y, color, section)
        if section in self.store.ui["collapsed"]:      # make sure it's visible
            self.store.ui["collapsed"].remove(section)
            self.store.changed()
        win = self._window_for(note["id"])
        win.reveal()
        win.textview.grab_focus()

    def show_note(self, nid, focus=True):
        note = self.store.notes.get(nid)
        if note is None:
            return
        note["hidden"] = False
        win = self._window_for(nid)
        if focus or not win.get_visible():
            win.reveal()
        self.store.changed()

    def hide_note(self, nid):
        note = self.store.notes.get(nid)
        if note is None:
            return
        note["hidden"] = True
        win = self.windows.get(nid)
        if win is not None:
            win.hide()
        self.store.changed()
        self.maybe_quit()

    def show_all_notes(self, raise_them=False):
        for nid in list(self.store.notes):
            self.show_note(nid, focus=raise_them)

    def hide_all_notes(self):
        for nid in list(self.store.notes):
            note = self.store.notes[nid]
            note["hidden"] = True
            win = self.windows.get(nid)
            if win is not None:
                win.hide()
        self.store.changed()
        self.maybe_quit()

    def delete_note(self, nid):
        win = self.windows.pop(nid, None)
        if win is not None:
            win.destroy()
        self.store.delete(nid)
        self.maybe_quit()

    def maybe_quit(self):
        """Stop running only when nothing at all is on screen."""
        manager_open = self.manager is not None and self.manager.get_visible()
        notes_open = any(w.get_visible() for w in self.windows.values())
        if not manager_open and not notes_open and not self._quitting:
            self._quitting = True
            self.store.save_now()
            self.release()
            self.quit()

    def do_shutdown(self):
        for w in self.windows.values():
            w.editor.flush()
        if self.store:
            self.store.save_now()
        Gtk.Application.do_shutdown(self)


def main():
    Gdk.set_allowed_backends("x11")
    GLib.set_prgname("desknotes")          # lets the dock match our icon
    GLib.set_application_name("Desk Notes")
    app = DeskNotesApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
