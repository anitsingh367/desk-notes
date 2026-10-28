"""Small outline icons for Desk Notes (drawn in the style of Tabler icons).

Each icon is a 24x24 SVG drawn with lines only, so it can be tinted any
colour. icon_image() turns one into a crisp Gtk.Image at any size.
"""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gtk  # noqa: E402

PATHS = {
    "chevron-down": ["M6 9l6 6l6 -6"],
    "chevron-right": ["M9 6l6 6l-6 6"],
    "briefcase": ["M5 7h14a2 2 0 0 1 2 2v9a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2v-9a2 2 0 0 1 2 -2z",
                  "M8 7v-2a2 2 0 0 1 2 -2h4a2 2 0 0 1 2 2v2",
                  "M12 12v.01", "M3 13a20 20 0 0 0 18 0"],
    "home": ["M5 12l-2 0l9 -9l9 9l-2 0",
             "M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-7",
             "M9 21v-6a2 2 0 0 1 2 -2h2a2 2 0 0 1 2 2v6"],
    "plus": ["M12 5v14", "M5 12h14"],
    "trash": ["M4 7h16", "M10 11v6", "M14 11v6",
              "M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2 -2l1 -12",
              "M9 7v-3a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v3"],
    "eye": ["M10 12a2 2 0 1 0 4 0a2 2 0 0 0 -4 0",
            "M21 12c-2.4 4 -5.4 6 -9 6c-3.6 0 -6.6 -2 -9 -6c2.4 -4 5.4 -6 9 -6c3.6 0 6.6 2 9 6"],
    "eye-off": ["M10.585 10.587a2 2 0 0 0 2.829 2.828",
                "M16.681 16.673a8.717 8.717 0 0 1 -4.681 1.327c-3.6 0 -6.6 -2 -9 -6"
                "c1.272 -2.12 2.712 -3.678 4.32 -4.674m2.86 -1.146a9.055 9.055 0 0 1 1.82 -.18"
                "c3.6 0 6.6 2 9 6c-.666 1.11 -1.379 2.067 -2.138 2.87",
                "M3 3l18 18"],
    "arrows-exchange": ["M7 10h14l-4 -4", "M17 14h-14l4 4"],
}


def _svg(name, color, stroke=1.8):
    paths = "".join(f'<path d="{d}"/>' for d in PATHS[name])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
            f'viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" '
            f'stroke-linejoin="round">{paths}</svg>').encode()


# used only if the system can't draw SVG images
FALLBACK = {"chevron-down": "⌄", "chevron-right": "›", "briefcase": "▣",
            "home": "⌂", "plus": "+", "trash": "✕", "eye": "◉", "eye-off": "○",
            "arrows-exchange": "⇄"}


def icon_image(name, color, size=16, scale=1):
    """A crisp icon widget (a Gtk.Image, or a text symbol as a fallback)."""
    try:
        px = size * scale
        loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
        loader.set_size(px, px)
        loader.write(_svg(name, color))
        loader.close()
        pixbuf = loader.get_pixbuf()
        try:
            import cairo  # noqa: F401  (needed for sharp HiDPI icons)
            surface = Gdk.cairo_surface_create_from_pixbuf(pixbuf, scale, None)
            img = Gtk.Image.new_from_surface(surface)
        except Exception:
            if scale != 1:
                pixbuf = pixbuf.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
            img = Gtk.Image.new_from_pixbuf(pixbuf)
        img.set_size_request(size, size)
        return img
    except Exception:
        lbl = Gtk.Label()
        lbl.set_markup(f'<span foreground="{color}">{FALLBACK.get(name, "•")}</span>')
        lbl.set_size_request(size, size)
        return lbl
