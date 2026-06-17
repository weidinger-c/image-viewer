# Image Viewer

A lightweight GTK4 image viewer for Linux with keyboard-first navigation, smooth zooming, dark mode, and folder-based browsing.

## Features

- Fast image navigation in a folder
- Fit-to-window display by default
- Zoom controls with keyboard and Ctrl + mouse wheel
- Pan by left-drag when zoomed
- Fullscreen toggle
- Built-in keyboard shortcut help overlay
- Dark mode toggle with persistent setting
- Desktop integration support (set as default image app)

## Supported Formats

- bmp
- gif
- ico
- jpeg / jpg
- pbm / pgm / png / ppm
- tif / tiff
- webp

## Requirements

- Python 3
- GTK4 Python bindings
- GdkPixbuf bindings

On Ubuntu/Debian, these are installed by the installer script.

## Install

From the project directory:

```bash
chmod +x install.sh
./install.sh
```

The installer will:

- Install required system packages
- Create a launcher at `~/.local/bin/image_viewer`
- Register a desktop entry in `~/.local/share/applications/image-viewer.desktop`
- Set common image MIME types to open with this viewer (via xdg-mime)

## Run

Open a specific image:

```bash
image_viewer /path/to/file.jpg
```

Open a folder (viewer scans supported files in that folder):

```bash
image_viewer /path/to/folder
```

Run from current directory:

```bash
image_viewer
```

## Keyboard Shortcuts

### Navigation

- Right / Space / n / PgDn: next image
- Left / Backspace / p / PgUp: previous image
- Home: first image
- End: last image

### Zoom

- + or =: zoom in
- -: zoom out
- Ctrl + mouse wheel: zoom around cursor
- 0: reset to fit-to-window
- o: original image size (100%)

### View

- f or F11: toggle fullscreen
- d: toggle dark mode
- Left-drag: pan (when zoomed)

### Other

- ? / h: show or hide help
- q / Esc: quit

## Persistent Settings

Dark mode preference is saved in:

- `~/.config/image-viewer/settings.json`

If `XDG_CONFIG_HOME` is set, that location is used instead of `~/.config`.

## Troubleshooting

If double-click in file manager does not open this app:

1. Re-run `./install.sh`
2. Confirm default handler for a type (example png):

```bash
xdg-mime query default image/png
```

Expected result:

- `image-viewer.desktop`

## Development

Quick syntax check:

```bash
python3 -m py_compile image_viewer.py
```
