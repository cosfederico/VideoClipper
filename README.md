# VideoClipper

A small desktop app for scrubbing a video and cutting it into named clips.

## Setup

```
pip install -r requirements.txt
```

That's it — no separate ffmpeg/ffprobe install or PATH setup needed.
Thumbnails, source probing, and export all go through
[PyAV](https://pyav.org/), which bundles FFmpeg's libraries statically
inside its wheel.

Video *playback* uses Qt's own multimedia backend, which is separate from
the PyAV pipeline used for thumbnails/export (on recent Qt6 builds this
backend is itself FFmpeg-based too, so MP4/MKV/AVI/MOV/WebM all preview
fine in practice). If a particular file's codec ever fails to preview in
the viewport, PyAV can usually still export clips from it — the two paths
are independent.

## Run

```
python videoclipper.py
```

## Using it

1. Click **Open Video** (top left, or the big button in the viewport), or
   drag and drop a video file onto the viewport, to load it — it loads
   paused, on the first frame. Opening another video later (via either
   method) replaces the current one — if you have clips that haven't been
   exported yet, you'll be asked to confirm first (same on quitting the app).
2. Scrub the timeline (click/drag) or press **Space** to play/pause.
3. Press **I** (or click **Set In**) at the point you want a clip to start.
4. Scrub ahead and press **O** (or click **Set Out**) to close the clip.
   A colored block appears on the timeline and a card appears in the right
   panel. Clips can't overlap.
5. Drag either edge of a clip's block to trim it — the viewport follows the
   handle so you can see exactly where you're cutting. A trim is clamped so
   it can never cross into a neighboring clip.
6. Click a clip's block on the timeline to select it (it highlights);
   press **Del** to delete it — no confirmation prompt. With a clip
   selected, **I**/**O** move its in/out point to the current playhead
   position instead of starting a new clip. Click empty track, or
   anywhere else in the window, to deselect. Double-click a block (or a
   clip's name in the right panel) to rename it; right-click a block for
   rename/recolor/delete.
7. Click a clip card on the right to jump the viewport to that clip's start
   and play it — playback auto-pauses at the clip's end. Any manual seek
   (dragging the timeline, arrow keys, Home/End) cancels that auto-stop.
8. Use the speaker button and slider next to Play to control volume/mute.
   The time readout in the middle shows `current / total` down to the
   frame (`2:10.15` = 2 minutes 10 seconds, frame 15) — click the current
   time to type a new one (same format, or plain seconds) and jump there
   frame-accurately; Escape or an unparsable value cancels without seeking.
9. Zoom the timeline with the mouse wheel (zooms in on whatever's under the
   cursor), Shift+wheel to pan left/right once zoomed in, or use the
   **−** / **+** / **Fit** buttons below the timeline (which zoom around the
   playhead instead). The zoomed view follows the playhead automatically
   during playback or a seek. Reopening a video resets the zoom.
   Once zoomed, a scrollbar appears below the timeline for panning without
   a mouse: Tab to it, then Left/Right/Home/End (or drag/click it like any
   scrollbar).
10. Click **Export Clips** (top right), choose an output folder and quality
    settings, then **Export**. A progress dialog shows overall percent, ETA,
    and the current clip's encode progress, and closes itself automatically
    once a successful export finishes (it stays open if something fails, so
    you can read the error).

### File menu

- **Open Video...** — same as the Open Video button.
- **Save Project JSON...** (**Ctrl+S**) — saves the video path, all clips
  (name/start/end/color), and the last-used export settings to a JSON
  file. The first save asks for a location; after that, Ctrl+S saves
  straight back to that file. Use **Save Project JSON...** again to pick
  a different file.
- **Open Project JSON...** — loads a saved project, restoring the clips
  and export settings and reopening its video. If the video has moved or
  been deleted, the clips still load (the timeline sizes itself to fit
  them) so you can relink it via Open Video. Asks for confirmation first
  if the current session has unsaved/unexported clips.
- **Open Recent** — the last 10 saved/opened project files.
- **Clear Recent Projects** — empties that list.
- **Exit** — closes the app (same confirmation as the window's close button).

### Help menu

**Help**, next to File, opens a popup with the shortcut table below plus a
summary of mouse interactions, projects, and export settings — a quick
reference without leaving the app.

### Shortcuts

| Key | Action |
| --- | --- |
| Ctrl+S | Save project |
| Space | Play / pause |
| I | Set in-point (or move selected clip's in-point) |
| O | Set out-point (or move selected clip's out-point) |
| Esc | Cancel a pending in-point |
| ←/→ | Seek 5s back/forward |
| Shift+←/→ | Seek 1s back/forward |
| ↑/↓ | Step one frame forward/back (pauses) |
| Home/End | Jump to start/end |
| Del | Delete the selected clip (no confirmation) |

## Notes on export settings

- **Copy** (no re-encode) is fastest but cuts snap to the nearest keyframe
  (a clip may start slightly earlier than its marker), and resolution/frame
  rate can't be changed without re-encoding, so those controls are disabled
  in that mode.
- Re-encoded clips (H.264/H.265/VP9) decode from the nearest keyframe and
  drop everything before the exact in-point before encoding, so the cut
  point is frame-accurate.
- CRF is the standard constant-quality knob (same meaning as ffmpeg's):
  lower = better quality and a bigger file. 18–28 is the usual range for
  x264/x265.
- **Resolution** is scaled by *height* only (width is derived automatically
  to preserve the source's aspect ratio) — this works for non-16:9 sources
  too, not just 1080p-style 16:9 video.
- **Frame rate** defaults to "Maintain original" (fps is read from the
  source when the video loads). 23.976 is encoded as the exact `24000/1001`
  fraction rather than a rounded decimal.
- **WebM** can only carry Opus audio (not AAC), so its audio codec choice
  is narrowed to Opus automatically.
- **Include original video name in exported files** (default on) names
  clips `{video_name}_{clip_name}.ext` instead of just `{clip_name}.ext`.
- **Save clip metadata** (default on) writes `{video_name}_clips_metadata.json`
  into the output folder alongside the clips: the source video's path,
  duration, resolution and fps; the export settings used; and each clip's
  name, output filename, start/end/duration.
