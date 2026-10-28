# Desk Notes

Sticky notes for the Ubuntu desktop that stay exactly where you put them.

Built because other sticky-notes apps didn't work well on Ubuntu 26.04 (Wayland):
notes couldn't be moved, didn't remember their place, or looked broken.

## Features

- Notes remember their position, size, color and text across restarts
- **Always on top** and **Always on visible workspace** per note
- Rich text: bold, italic, strikethrough, headings, bullets, numbered lists and checkboxes
- Typing shortcuts: `- ` bullet, `[] ` checkbox, `1. ` numbered list, `# ` heading, `->` becomes →
- **Ctrl+Up / Ctrl+Down** moves a list item (with its sub-items)
- **Ctrl+V** turns Markdown (e.g. copied from Notion) into real formatting; **Ctrl+Shift+V** pastes plain text
- Undo / redo, clickable links (Ctrl+click), zoom (Ctrl + plus / minus)
- Copy a note as plain text with WhatsApp-style formatting
- **Notes Manager** with Work and Personal sections, search, show / hide and delete
- Follows Ubuntu's light / dark setting; starts automatically at login

## Install

```bash
./install.sh
```

Then open **Desk Notes** from the app menu. The installer may ask for your password
once to add small Ubuntu packages (GTK 3 for Python, SVG and cairo support).

## Uninstall

```bash
./uninstall.sh                # keeps your notes
./uninstall.sh --delete-notes # also deletes your notes
```

Notes are stored in `~/.local/share/desknotes/notes.json`.

## Keyboard shortcuts

| Action | Shortcut |
|---|---|
| New note | Ctrl+N |
| Bold / Italic / Strikethrough | Ctrl+B / Ctrl+I / Ctrl+D |
| Heading (big, small, off) | Ctrl+H |
| Checkbox | Ctrl+L |
| Move list item | Ctrl+Up / Ctrl+Down |
| Indent / outdent list item | Tab / Shift+Tab |
| Paste as plain text | Ctrl+Shift+V |
| Undo / Redo | Ctrl+Z / Ctrl+Shift+Z |
| Text size | Ctrl + plus / minus, Ctrl+0 to reset |

## How it works

Python + GTK 3. The app runs through XWayland on purpose, because that lets windows
choose their own position and stay on top, which Wayland apps can't do on GNOME.
