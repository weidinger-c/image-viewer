#!/usr/bin/env bash
# Install dependencies and set up image_viewer for Ubuntu/Debian.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VIEWER="$SCRIPT_DIR/image_viewer.py"

echo "Installing system dependencies…"
sudo apt-get install -y \
  python3 \
  python3-gi \
  python3-gi-cairo \
  gir1.2-gtk-4.0 \
  gir1.2-gdkpixbuf-2.0

chmod +x "$VIEWER"

# Optional: create a launcher in ~/.local/bin
LAUNCHER="$HOME/.local/bin/image_viewer"
mkdir -p "$HOME/.local/bin"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
exec python3 "$VIEWER" "\$@"
EOF
chmod +x "$LAUNCHER"

# Register desktop entry and MIME associations for file-manager open.
APP_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$APP_DIR/image-viewer.desktop"
mkdir -p "$APP_DIR"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Image Viewer
Comment=Lightweight GTK4 image viewer
Exec=$LAUNCHER %f
Terminal=false
Categories=Graphics;Viewer;
MimeType=image/bmp;image/gif;image/jpeg;image/png;image/tiff;image/webp;image/x-icon;
StartupNotify=true
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_DIR"
fi

if command -v xdg-mime >/dev/null 2>&1; then
  mime_types=(
    image/bmp
    image/gif
    image/jpeg
    image/png
    image/tiff
    image/webp
    image/x-icon
  )
  for mime in "${mime_types[@]}"; do
    xdg-mime default image-viewer.desktop "$mime"
  done
fi

echo ""
echo "Done! Run the viewer with:"
echo "  image_viewer [path/to/image_or_folder]"
echo "Default app registration installed in: $DESKTOP_FILE"
echo ""
echo "If ~/.local/bin is not on your PATH, add this to ~/.bashrc or ~/.profile:"
echo '  export PATH="$HOME/.local/bin:$PATH"'
