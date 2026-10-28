#!/usr/bin/env bash
# Installs Desk Notes for the current user.
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/.local/lib/desknotes"
DESKTOP_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"

echo "Checking that GTK 3 for Python is installed..."
if ! /usr/bin/python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk" 2>/dev/null; then
    echo "Installing two small Ubuntu packages (needs your password)..."
    sudo apt install -y python3-gi gir1.2-gtk-3.0
fi

if ! /usr/bin/python3 -c "import gi; gi.require_version('GdkPixbuf','2.0'); from gi.repository import GdkPixbuf; GdkPixbuf.PixbufLoader.new_with_type('svg')" 2>/dev/null; then
    echo "Installing the SVG image loader for the app's icons (needs your password)..."
    sudo apt install -y librsvg2-common
fi

if ! /usr/bin/python3 -c "import cairo, gi; gi.require_foreign('cairo')" 2>/dev/null; then
    echo "Installing python3-gi-cairo for sharp icons (needs your password)..."
    sudo apt install -y python3-gi-cairo
fi

echo "Copying the app..."
mkdir -p "$APP_DIR" "$DESKTOP_DIR" "$AUTOSTART_DIR"
cp "$HERE/desknotes.py" "$HERE/richtext.py" "$HERE/icons.py" "$APP_DIR/"
chmod +x "$APP_DIR/desknotes.py"

ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$ICON_DIR"
cp "$HERE/desknotes.svg" "$ICON_DIR/desknotes.svg"
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

cat > "$DESKTOP_DIR/desknotes.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Desk Notes
Comment=Sticky notes that stay where you put them
Exec=env GDK_BACKEND=x11 /usr/bin/python3 $APP_DIR/desknotes.py
Icon=desknotes
Terminal=false
Categories=Utility;
StartupWMClass=desknotes
Actions=manager;new-note;show-all;

[Desktop Action manager]
Name=Notes Manager
Exec=env GDK_BACKEND=x11 /usr/bin/python3 $APP_DIR/desknotes.py

[Desktop Action new-note]
Name=New Note
Exec=env GDK_BACKEND=x11 /usr/bin/python3 $APP_DIR/desknotes.py --new-note

[Desktop Action show-all]
Name=Show All Notes
Exec=env GDK_BACKEND=x11 /usr/bin/python3 $APP_DIR/desknotes.py --show-all
EOF

# Start automatically when you log in, so your notes come back.
sed -n '1,/^StartupWMClass/p' "$DESKTOP_DIR/desknotes.desktop" \
    | sed 's|desknotes.py$|desknotes.py --background|' > "$AUTOSTART_DIR/desknotes.desktop"
echo "X-GNOME-Autostart-enabled=true" >> "$AUTOSTART_DIR/desknotes.desktop"

update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo
echo "Done! Open 'Desk Notes' from your app menu."
echo "It will also open by itself each time you log in."
