#!/usr/bin/env python3
"""Lightweight GTK4 image viewer - navigate with arrow keys."""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('GdkPixbuf', '2.0')
import cairo
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

SUPPORTED_EXTENSIONS = frozenset({
    '.bmp', '.gif', '.ico', '.jpeg', '.jpg', '.pbm',
    '.pgm', '.png', '.ppm', '.tif', '.tiff', '.webp',
})

PRELOAD_AHEAD = 2
PRELOAD_BEHIND = 1
CONFIG_FILENAME = 'settings.json'
CONFIG_DIR_NAME = 'image-viewer'


class ImageViewer(Gtk.ApplicationWindow):
  """Main application window."""

  def __init__(self, app: Gtk.Application, start_path: str) -> None:
    super().__init__(application=app, title='Image Viewer')
    self._app = app
    self._images: list[str] = []
    self._index: int = 0
    self._cache: dict[str, GdkPixbuf.Pixbuf] = {}
    self._cache_lock = threading.Lock()
    self._fullscreen = False
    self._zoom: float = 0.0  # 0 = fit-to-window
    self._current_pixbuf: GdkPixbuf.Pixbuf | None = None
    self._cursor_x: float = 0.0
    self._cursor_y: float = 0.0
    self._drag_start_h: float = 0.0
    self._drag_start_v: float = 0.0
    self._settings_path = self._get_settings_path()
    self._dark_mode = self._load_dark_mode_setting()

    self._apply_theme()

    self.set_default_size(1200, 800)
    self._build_ui()
    self.present()

    GLib.idle_add(self._load_path, start_path)

  # ------------------------------------------------------------------ #
  # UI                                                                   #
  # ------------------------------------------------------------------ #

  def _build_ui(self) -> None:
    # Overlay lets us float the help panel over the image pane
    overlay = Gtk.Overlay()
    self.set_child(overlay)

    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    overlay.set_child(vbox)

    self._scroll = Gtk.ScrolledWindow()
    self._scroll.set_policy(
        Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
    self._scroll.set_vexpand(True)
    self._scroll.set_hexpand(True)
    vbox.append(self._scroll)

    # DrawingArea gives us pixel-accurate control for both fit and zoom
    self._da = Gtk.DrawingArea()
    self._da.set_draw_func(self._on_draw)
    self._da.set_hexpand(True)
    self._da.set_vexpand(True)
    self._scroll.set_child(self._da)

    self._status = Gtk.Label(label='Loading…')
    self._status.set_halign(Gtk.Align.START)
    self._status.set_margin_start(6)
    self._status.set_margin_top(2)
    self._status.set_margin_bottom(2)
    vbox.append(self._status)

    # ---- help overlay panel ----------------------------------------
    self._help_box = self._build_help_panel()
    self._help_box.set_halign(Gtk.Align.CENTER)
    self._help_box.set_valign(Gtk.Align.CENTER)
    self._help_box.set_visible(False)
    overlay.add_overlay(self._help_box)

    # Dismiss help on click anywhere
    click = Gtk.GestureClick.new()
    click.connect('pressed', lambda *_: self._set_help_visible(False))
    overlay.add_controller(click)
    # ----------------------------------------------------------------

    key_ctrl = Gtk.EventControllerKey()
    key_ctrl.connect('key-pressed', self._on_key_pressed)
    self.add_controller(key_ctrl)

    # Ctrl+scroll → zoom
    scroll_ctrl = Gtk.EventControllerScroll.new(
        Gtk.EventControllerScrollFlags.BOTH_AXES)
    scroll_ctrl.connect('scroll', self._on_scroll)
    self._scroll.add_controller(scroll_ctrl)

    # Track cursor position for centered zoom
    motion = Gtk.EventControllerMotion.new()
    motion.connect('motion', self._on_motion)
    self._scroll.add_controller(motion)

    # Left-click drag → pan when zoomed
    drag = Gtk.GestureDrag.new()
    drag.set_button(1)
    drag.connect('drag-begin', self._on_drag_begin)
    drag.connect('drag-update', self._on_drag_update)
    self._scroll.add_controller(drag)

  def _build_help_panel(self) -> Gtk.Widget:
    SHORTCUTS = [
        ('Navigation', [
            ('→ / Space / n / PgDn', 'Next image'),
            ('← / Backspace / p / PgUp', 'Previous image'),
            ('Home', 'First image'),
            ('End', 'Last image'),
        ]),
        ('Zoom', [
            ('+ / =', 'Zoom in'),
            ('−', 'Zoom out'),
          ('O', 'Resize to original size (100%)'),
            ('Ctrl + scroll', 'Zoom in/out at cursor'),
            ('0', 'Reset to fit-to-window'),
        ]),
        ('View', [
            ('F / F11', 'Toggle fullscreen'),
          ('D', 'Toggle dark mode'),
            ('Left-drag', 'Pan (when zoomed)'),
        ]),
        ('Other', [
            ('? / H', 'Show / hide this help'),
            ('Q / Esc', 'Quit'),
        ]),
    ]

    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    outer.add_css_class('help-panel')
    outer.set_margin_top(24)
    outer.set_margin_bottom(24)
    outer.set_margin_start(32)
    outer.set_margin_end(32)

    title = Gtk.Label(label='Keyboard Shortcuts')
    title.add_css_class('help-title')
    title.set_margin_bottom(16)
    outer.append(title)

    grid = Gtk.Grid()
    grid.set_row_spacing(4)
    grid.set_column_spacing(24)
    row = 0
    for section, entries in SHORTCUTS:
      sec_label = Gtk.Label(label=section.upper())
      sec_label.add_css_class('help-section')
      sec_label.set_halign(Gtk.Align.START)
      sec_label.set_margin_top(10 if row > 0 else 0)
      sec_label.set_margin_bottom(2)
      grid.attach(sec_label, 0, row, 2, 1)
      row += 1
      for keys, desc in entries:
        key_label = Gtk.Label(label=keys)
        key_label.add_css_class('help-key')
        key_label.set_halign(Gtk.Align.END)
        desc_label = Gtk.Label(label=desc)
        desc_label.set_halign(Gtk.Align.START)
        grid.attach(key_label, 0, row, 1, 1)
        grid.attach(desc_label, 1, row, 1, 1)
        row += 1
    outer.append(grid)

    hint = Gtk.Label(label='Press ? or click anywhere to close')
    hint.add_css_class('help-hint')
    hint.set_margin_top(16)
    outer.append(hint)

    # Apply CSS
    css = b'''
      .help-panel {
        background-color: rgba(20, 20, 20, 0.92);
        border-radius: 12px;
        color: #f0f0f0;
      }
      .help-title {
        font-size: 16px;
        font-weight: bold;
        color: #ffffff;
      }
      .help-section {
        font-size: 11px;
        font-weight: bold;
        color: #888888;
        letter-spacing: 1px;
      }
      .help-key {
        font-family: monospace;
        color: #f0c060;
      }
      .help-hint {
        font-size: 11px;
        color: #666666;
      }
    '''
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
    return outer

  def _set_help_visible(self, visible: bool) -> None:
    self._help_box.set_visible(visible)

  def _toggle_help(self) -> None:
    self._set_help_visible(not self._help_box.get_visible())


  def _load_path(self, path: str) -> bool:
    p = Path(path).resolve()
    if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
      folder, start = p.parent, str(p)
    elif p.is_dir():
      folder, start = p, None
    else:
      self._status.set_text(f'Not a valid path: {path}')
      return False

    self._status.set_text('Scanning folder…')
    threading.Thread(
        target=self._scan_folder, args=(folder, start), daemon=True
    ).start()
    return False

  def open_path(self, path: str) -> None:
    GLib.idle_add(self._load_path, path)
    self.present()

  def _scan_folder(self, folder: Path, start: str | None) -> None:
    images = sorted(
        str(f)
        for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    if not images:
      GLib.idle_add(self._status.set_text, 'No images found in folder.')
      return

    index = 0
    if start and start in images:
      index = images.index(start)

    GLib.idle_add(self._on_folder_loaded, images, index)

  def _on_folder_loaded(self, images: list[str], index: int) -> bool:
    self._images = images
    self._index = index
    self._show_current()
    return False

  def _get_settings_path(self) -> Path:
    config_home = Path(os.environ.get('XDG_CONFIG_HOME',
                                      str(Path.home() / '.config')))
    return config_home / CONFIG_DIR_NAME / CONFIG_FILENAME

  def _load_dark_mode_setting(self) -> bool:
    if not self._settings_path.exists():
      return False
    try:
      with self._settings_path.open('r', encoding='utf-8') as f:
        settings = json.load(f)
      return bool(settings.get('dark_mode', False))
    except (OSError, json.JSONDecodeError):
      return False

  def _save_settings(self) -> None:
    try:
      self._settings_path.parent.mkdir(parents=True, exist_ok=True)
      with self._settings_path.open('w', encoding='utf-8') as f:
        json.dump({'dark_mode': self._dark_mode}, f, indent=2)
        f.write('\n')
    except OSError as exc:
      print(f'Cannot save settings to {self._settings_path}: {exc}',
            file=sys.stderr)

  def _apply_theme(self) -> None:
    settings = Gtk.Settings.get_default()
    if settings is not None:
      settings.set_property('gtk-application-prefer-dark-theme',
                            self._dark_mode)

  def _toggle_dark_mode(self) -> None:
    self._dark_mode = not self._dark_mode
    self._apply_theme()
    self._save_settings()
    self._update_status()

  # ------------------------------------------------------------------ #
  # Display                                                              #
  # ------------------------------------------------------------------ #

  def _show_current(self) -> None:
    if not self._images:
      return
    path = self._images[self._index]
    pixbuf = self._get_pixbuf(path)
    if pixbuf:
      self._render(pixbuf)
    name = Path(path).name
    self.set_title(f'{name} — Image Viewer')
    self._update_status()
    self._schedule_preload()

  def _update_status(self) -> None:
    if not self._images:
      return
    name = Path(self._images[self._index]).name
    zoom_str = f'{self._zoom * 100:.0f}%' if self._zoom > 0.0 else 'fit'
    theme_str = 'dark' if self._dark_mode else 'light'
    self._status.set_text(
        f'  {self._index + 1} / {len(self._images)}   {name}   '
        f'[{zoom_str}, {theme_str}]')

  def _render(self, pixbuf: GdkPixbuf.Pixbuf) -> None:
    self._current_pixbuf = pixbuf
    if self._zoom > 0.0:
      iw = pixbuf.get_width()
      ih = pixbuf.get_height()
      # Minimum size drives scrollbars when image exceeds viewport;
      # hexpand/vexpand let the area fill leftover space for centering.
      self._da.set_size_request(max(int(iw * self._zoom), 1),
                                max(int(ih * self._zoom), 1))
      self._scroll.set_policy(
          Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    else:
      self._da.set_size_request(-1, -1)
      self._scroll.set_policy(
          Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
    # Always expand so the area fills the viewport — centering works in
    # both fit mode and zoom mode (when the image is smaller than the pane).
    self._da.set_hexpand(True)
    self._da.set_vexpand(True)
    self._da.queue_draw()

  def _on_draw(
      self, _da, cr: cairo.Context, width: int, height: int) -> None:
    pixbuf = self._current_pixbuf
    if pixbuf is None:
      return
    iw = pixbuf.get_width()
    ih = pixbuf.get_height()
    if self._zoom == 0.0:
      scale = min(width / iw, height / ih)
    else:
      scale = self._zoom
    # Center within whatever space the DrawingArea has been given.
    # When the image overflows (zoom > viewport), max() clamps to 0
    # so the image starts at the edge and scrollbars take over.
    x = max((width  - iw * scale) / 2.0, 0.0)
    y = max((height - ih * scale) / 2.0, 0.0)
    cr.save()
    cr.translate(x, y)
    cr.scale(scale, scale)
    Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_BILINEAR)
    cr.paint()
    cr.restore()

  # ------------------------------------------------------------------ #
  # Cache / preload                                                      #
  # ------------------------------------------------------------------ #

  def _get_pixbuf(self, path: str) -> GdkPixbuf.Pixbuf | None:
    with self._cache_lock:
      if path in self._cache:
        return self._cache[path]
    try:
      pb = GdkPixbuf.Pixbuf.new_from_file(path)
    except Exception as exc:
      print(f'Cannot load {path}: {exc}', file=sys.stderr)
      return None
    with self._cache_lock:
      self._cache[path] = pb
      self._evict()
    return pb

  def _get_cached(self, path: str) -> GdkPixbuf.Pixbuf | None:
    with self._cache_lock:
      return self._cache.get(path)

  def _evict(self) -> None:
    """Remove cached images far from current index. Must be called under lock."""
    keep = set()
    for delta in range(-PRELOAD_BEHIND, PRELOAD_AHEAD + 1):
      i = self._index + delta
      if 0 <= i < len(self._images):
        keep.add(self._images[i])
    for key in list(self._cache):
      if key not in keep:
        del self._cache[key]

  def _schedule_preload(self) -> None:
    for sign, limit in ((1, PRELOAD_AHEAD), (-1, PRELOAD_BEHIND)):
      for step in range(1, limit + 1):
        i = self._index + sign * step
        if 0 <= i < len(self._images):
          path = self._images[i]
          with self._cache_lock:
            if path in self._cache:
              continue
          threading.Thread(
              target=self._get_pixbuf, args=(path,), daemon=True
          ).start()

  # ------------------------------------------------------------------ #
  # Input                                                                #
  # ------------------------------------------------------------------ #

  def _on_key_pressed(
      self, _ctrl, keyval: int, _keycode: int, _state) -> bool:
    if keyval in (Gdk.KEY_Right, Gdk.KEY_space, Gdk.KEY_n, Gdk.KEY_Page_Down):
      self._navigate(1)
    elif keyval in (Gdk.KEY_Left, Gdk.KEY_BackSpace, Gdk.KEY_p, Gdk.KEY_Page_Up):
      self._navigate(-1)
    elif keyval == Gdk.KEY_Home:
      self._index = 0
      self._zoom = 0.0
      self._show_current()
    elif keyval == Gdk.KEY_End:
      self._index = len(self._images) - 1
      self._zoom = 0.0
      self._show_current()
    elif keyval in (Gdk.KEY_f, Gdk.KEY_F11):
      self._toggle_fullscreen()
    elif keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
      self._zoom_by(1.25)
    elif keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
      self._zoom_by(0.8)
    elif keyval in (Gdk.KEY_o, Gdk.KEY_O):
      self._set_original_size()
    elif keyval == Gdk.KEY_0:
      self._reset_to_fit()
    elif keyval in (Gdk.KEY_question, Gdk.KEY_h, Gdk.KEY_H):
      self._toggle_help()
    elif keyval in (Gdk.KEY_d, Gdk.KEY_D):
      self._toggle_dark_mode()
    elif keyval in (Gdk.KEY_q, Gdk.KEY_Escape):
      if self._help_box.get_visible():
        self._set_help_visible(False)
      else:
        self._app.quit()
    return True

  def _navigate(self, delta: int) -> None:
    if not self._images:
      return
    self._index = (self._index + delta) % len(self._images)
    self._show_current()

  def _toggle_fullscreen(self) -> None:
    if self._fullscreen:
      self.unfullscreen()
    else:
      self.fullscreen()
    self._fullscreen = not self._fullscreen

  def _reset_to_fit(self) -> None:
    if not self._images:
      return
    self._zoom = 0.0
    path = self._images[self._index]
    pixbuf = self._get_cached(path) or self._get_pixbuf(path)
    if pixbuf:
      self._render(pixbuf)
    # Clear pan offsets from zoom mode so fit mode always starts centered.
    GLib.idle_add(self._apply_scroll, 0.0, 0.0)
    self._update_status()

  def _set_original_size(self) -> None:
    if not self._images:
      return
    self._zoom = 1.0
    path = self._images[self._index]
    pixbuf = self._get_cached(path) or self._get_pixbuf(path)
    if pixbuf:
      self._render(pixbuf)
    self._update_status()

  def _zoom_by(self, factor: float, pivot: tuple[float, float] | None = None) -> None:
    """Zoom by factor, keeping the pivot point (widget coords) stationary."""
    if not self._images:
      return
    path = self._images[self._index]
    pixbuf = self._get_cached(path) or self._get_pixbuf(path)
    if not pixbuf:
      return

    hadj = self._scroll.get_hadjustment()
    vadj = self._scroll.get_vadjustment()

    if self._zoom == 0.0:
      pw = self._scroll.get_width()
      ph = self._scroll.get_height()
      iw = pixbuf.get_width()
      ih = pixbuf.get_height()
      self._zoom = min(pw / iw, ph / ih) if (pw > 0 and ph > 0) else 1.0
      # In fit mode the image is centered; pivot is viewport center
      cx_frac, cy_frac = 0.5, 0.5
    else:
      iw = pixbuf.get_width()
      ih = pixbuf.get_height()
      old_w = iw * self._zoom
      old_h = ih * self._zoom
      if pivot:
        # pivot is in scroll-widget coords; convert to image coords
        px = hadj.get_value() + pivot[0]
        py = vadj.get_value() + pivot[1]
      else:
        px = hadj.get_value() + hadj.get_page_size() / 2
        py = vadj.get_value() + vadj.get_page_size() / 2
      cx_frac = px / old_w if old_w > 0 else 0.5
      cy_frac = py / old_h if old_h > 0 else 0.5

    self._zoom = max(0.05, min(self._zoom * factor, 20.0))
    self._render(pixbuf)
    self._update_status()

    # Re-center scroll so the pivot stays under the cursor
    iw = pixbuf.get_width()
    ih = pixbuf.get_height()
    new_w = iw * self._zoom
    new_h = ih * self._zoom
    new_px = cx_frac * new_w
    new_py = cy_frac * new_h
    target_x = new_px - (pivot[0] if pivot else hadj.get_page_size() / 2)
    target_y = new_py - (pivot[1] if pivot else vadj.get_page_size() / 2)
    GLib.idle_add(self._apply_scroll, target_x, target_y)

  def _apply_scroll(self, x: float, y: float) -> bool:
    hadj = self._scroll.get_hadjustment()
    vadj = self._scroll.get_vadjustment()
    hadj.set_value(
        max(hadj.get_lower(),
            min(x, hadj.get_upper() - hadj.get_page_size())))
    vadj.set_value(
        max(vadj.get_lower(),
            min(y, vadj.get_upper() - vadj.get_page_size())))
    return False

  def _on_scroll(self, ctrl, _dx: float, dy: float) -> bool:
    state = ctrl.get_current_event_state()
    if not (state & Gdk.ModifierType.CONTROL_MASK):
      return False
    factor = 0.8 if dy > 0 else 1.25
    self._zoom_by(factor, pivot=(self._cursor_x, self._cursor_y))
    return True

  def _on_motion(self, _ctrl, x: float, y: float) -> None:
    self._cursor_x = x
    self._cursor_y = y

  def _on_drag_begin(self, gesture, _x: float, _y: float) -> None:
    if self._zoom == 0.0:
      gesture.set_state(Gtk.EventSequenceState.DENIED)
      return
    gesture.set_state(Gtk.EventSequenceState.CLAIMED)
    self._drag_start_h = self._scroll.get_hadjustment().get_value()
    self._drag_start_v = self._scroll.get_vadjustment().get_value()

  def _on_drag_update(self, _gesture, offset_x: float, offset_y: float) -> None:
    if self._zoom == 0.0:
      return
    hadj = self._scroll.get_hadjustment()
    vadj = self._scroll.get_vadjustment()
    hadj.set_value(
        max(hadj.get_lower(),
            min(self._drag_start_h - offset_x,
                hadj.get_upper() - hadj.get_page_size())))
    vadj.set_value(
        max(vadj.get_lower(),
            min(self._drag_start_v - offset_y,
                vadj.get_upper() - vadj.get_page_size())))


# ------------------------------------------------------------------ #
# Entry point                                                          #
# ------------------------------------------------------------------ #

def main() -> None:
  app = Gtk.Application(
      application_id='com.example.imageviewer',
      flags=Gio.ApplicationFlags.HANDLES_OPEN,
  )

  def ensure_window(application: Gtk.Application, start_path: str) -> ImageViewer:
    window = application.get_active_window()
    if isinstance(window, ImageViewer):
      return window
    return ImageViewer(application, start_path)

  def on_activate(application: Gtk.Application) -> None:
    ensure_window(application, os.getcwd()).present()

  def on_open(
      application: Gtk.Application,
      files: list[Gio.File],
      _n_files: int,
      _hint: str,
  ) -> None:
    if not files:
      ensure_window(application, os.getcwd()).present()
      return
    path = files[0].get_path()
    target = path if path else os.getcwd()
    ensure_window(application, target).open_path(target)

  app.connect('activate', on_activate)
  app.connect('open', on_open)
  sys.exit(app.run(sys.argv))


if __name__ == '__main__':
  main()
