#!/usr/bin/env bash
# Removes Desk Notes. Your saved notes are kept unless you add --delete-notes.
pkill -f "desknotes/desknotes.py" 2>/dev/null || true
rm -rf "$HOME/.local/lib/desknotes"
rm -f "$HOME/.local/share/applications/desknotes.desktop"
rm -f "$HOME/.config/autostart/desknotes.desktop"
rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/desknotes.svg"

if [ "$1" = "--delete-notes" ]; then
    rm -rf "$HOME/.local/share/desknotes"
    echo "Desk Notes and all your notes were removed."
else
    echo "Desk Notes was removed. Your notes are still saved in ~/.local/share/desknotes"
fi
