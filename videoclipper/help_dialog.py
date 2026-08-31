"""A read-only Help dialog: keyboard shortcuts and other usage notes."""
from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

from .style import ACCENT, BORDER, MUTED, TEXT

_SHORTCUTS = [
    ("Ctrl+S", "Save project"),
    ("Ctrl+Z", "Undo"),
    ("Ctrl+Shift+Z", "Redo"),
    ("Space", "Play / pause"),
    ("I", "Set in-point (or move selected clip's in-point)"),
    ("O", "Set out-point (or move selected clip's out-point)"),
    ("Esc", "Cancel a pending in-point"),
    ("← / →", "Seek 5s back / forward"),
    ("Shift+← / →", "Seek 1s back / forward"),
    ("↑ / ↓", "Step one frame forward / back (pauses)"),
    ("Home / End", "Jump to start / end"),
    ("Del", "Delete the selected clip (no confirmation)"),
]

_HELP_HTML = f"""
<style>
  body {{ color: {TEXT}; font-size: 13px; }}
  h2 {{ color: {TEXT}; margin-bottom: 4px; }}
  h3 {{ color: {ACCENT}; margin-top: 18px; margin-bottom: 6px; }}
  p, li {{ color: {TEXT}; }}
  .muted {{ color: {MUTED}; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ text-align: left; padding: 4px 10px; border-bottom: 1px solid {BORDER}; }}
  th {{ color: {MUTED}; font-weight: 600; }}
  kbd {{
    background: {BORDER}; border-radius: 4px; padding: 1px 6px;
    font-family: Consolas, monospace;
  }}
</style>

<h2>VideoClipper</h2>
<p class="muted">Scrub a video, mark clips, trim them, and export.</p>

<h3>Basics</h3>
<ul>
  <li><b>Open Video</b> (or drag and drop a video onto the viewport)
      loads a file, paused on its first frame.</li>
  <li>Click or drag the timeline to scrub; the ruler and playhead follow.</li>
  <li>Set <b>In</b> then <b>Out</b> to create a clip - clips can't overlap.</li>
  <li>Drag a clip's edge to trim it; the viewport follows the handle.</li>
  <li>Click a clip to select it (highlights); click empty track, or
      anywhere else in the window, to deselect.</li>
  <li>Double-click a clip (or its name in the right-hand list) to rename
      it; right-click it for rename/recolor/delete.</li>
  <li>Click a clip card on the right to jump to and play that clip -
      playback auto-pauses at its end.</li>
  <li>Drag the divider to resize the clip panel - the cards scale with it,
      and thumbnails match the loaded video's real aspect ratio. It won't
      shrink past a minimum width; drag further to collapse it entirely.</li>
  <li><b>Ctrl+Z</b> / <b>Ctrl+Shift+Z</b> undo/redo in/out points, trims,
      renames, recolors, and deletes, up to 100 steps back.</li>
</ul>

<h3>Timeline zoom</h3>
<ul>
  <li>Mouse wheel over the timeline zooms in on whatever's under the
      cursor; Shift+wheel pans once zoomed in.</li>
  <li>The <b>-</b> / <b>+</b> / <b>Fit</b> buttons below the timeline zoom
      around the playhead instead.</li>
  <li>Once zoomed, a scrollbar appears for panning without a mouse - Tab
      to it, then use the arrow/Home/End keys.</li>
</ul>

<h3>Time readout</h3>
<p>The <code>current / total</code> display shows frame-accurate time,
e.g. <code>2:10.15</code> = 2 minutes 10 seconds, frame 15. Click the
current time to type a new one (same format, or plain seconds) and jump
there frame-accurately.</p>

<h3>Keyboard shortcuts</h3>
<table>
  <tr><th>Key</th><th>Action</th></tr>
  {"".join(f"<tr><td><kbd>{key}</kbd></td><td>{action}</td></tr>" for key, action in _SHORTCUTS)}
</table>

<h3>Projects</h3>
<ul>
  <li><b>File &gt; Save Project JSON...</b> (<b>Ctrl+S</b>) saves the video
      path, every clip, and the last-used export settings to a JSON file.
      The first save asks for a location; after that, Ctrl+S saves
      straight back to it.</li>
  <li><b>File &gt; Open Project JSON...</b> reopens a saved project. If its
      video has moved, the clips still load so you can relink it via
      Open Video.</li>
  <li><b>File &gt; Open Recent</b> lists the last 10 saved/opened
      projects; <b>Clear Recent Projects</b> empties that list.</li>
  <li>Opening a different video or project, or exiting, asks for
      confirmation if there are unsaved/unexported clips.</li>
</ul>

<h3>Export</h3>
<ul>
  <li><b>Copy</b> (no re-encode) is fastest, but cuts snap to the nearest
      keyframe and resolution/frame rate can't be changed.</li>
  <li>Re-encoded clips (H.264/H.265/VP9) cut frame-accurately at the exact
      in-point.</li>
  <li><b>WebM</b> can only carry Opus audio, so its audio codec is
      narrowed to Opus automatically.</li>
  <li>"Include original video name" and "Save clip metadata" control the
      output filenames and an optional JSON manifest alongside the clips.</li>
</ul>
"""


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("VideoClipper Help")
        self.resize(600, 640)

        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(_HELP_HTML)
        layout.addWidget(browser)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)
