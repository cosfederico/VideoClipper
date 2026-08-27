# VideoClipper

A small desktop app for scrubbing a video and cutting it into named clips,
exported with ffmpeg.

## Setup

```
pip install -r requirements.txt
```

You also need **ffmpeg** on your `PATH` (used to generate clip thumbnails and
to export). If you'd rather not install it system-wide, uncomment
`imageio-ffmpeg` in `requirements.txt` and install it — the app will fall
back to its bundled ffmpeg binary automatically.

Video *playback* uses Qt's own multimedia backend, which is separate from
the ffmpeg process used for thumbnails/export (on recent Qt6 builds this
backend is itself FFmpeg-based, so MP4/MKV/AVI/MOV/WebM all preview fine in
practice). If a particular file's codec ever fails to preview in the
viewport, ffmpeg can usually still export clips from it — the two paths are
independent.

## Run

```
python main.py
```

## Using it

1. Click **Open Video** (top left, or the big button in the viewport) and
   pick a file. It loads paused, on the first frame. Opening another video
   later replaces the current one — if you have clips that haven't been
   exported yet, you'll be asked to confirm first (same on quitting the app).
2. Scrub the timeline (click/drag) or press **Space** to play/pause.
3. Press **I** (or click **Set In**) at the point you want a clip to start.
4. Scrub ahead and press **O** (or click **Set Out**) to close the clip.
   A colored block appears on the timeline and a card appears in the right
   panel. Clips can't overlap.
5. Drag either edge of a clip's block to trim it — the viewport follows the
   handle so you can see exactly where you're cutting. A trim is clamped so
   it can never cross into a neighboring clip.
6. Double-click a clip's block on the timeline (or its name in the right
   panel) to rename it. Right-click a block for rename/recolor/delete.
7. Click a clip card on the right to jump the viewport to that clip's start
   and play it — playback auto-pauses at the clip's end. Any manual seek
   (dragging the timeline, arrow keys, Home/End) cancels that auto-stop.
8. Use the speaker button and slider next to Play to control volume/mute.
9. Click **Export Clips** (top right), choose an output folder and quality
   settings, then **Export**. A progress dialog shows overall percent, ETA,
   and the current clip's encode progress, and closes itself automatically
   once a successful export finishes (it stays open if something fails, so
   you can read the error).

### Shortcuts

| Key | Action |
| --- | --- |
| Space | Play / pause |
| I | Set in-point |
| O | Set out-point |
| Esc | Cancel a pending in-point |
| ←/→ | Seek 5s back/forward |
| Shift+←/→ | Seek 1s back/forward |
| Home/End | Jump to start/end |

## Notes on export settings

- **Copy** (no re-encode) is fastest but cuts snap to the nearest keyframe
  (a clip may start slightly earlier than its marker), and resolution/frame
  rate can't be changed without re-encoding, so those controls are disabled
  in that mode.
- Re-encoded clips (H.264/H.265/VP9) use ffmpeg's two-stage seek
  (`-ss` before *and* after `-i`) so the cut point is frame-accurate while
  still seeking quickly.
- CRF is ffmpeg's standard constant-quality knob: lower = better quality and
  a bigger file. 18–28 is the usual range for x264/x265.
- **Resolution** is scaled by *height* only (`scale=-2:H`) so width is
  derived automatically to preserve the source's aspect ratio — this works
  for non-16:9 sources too, not just 1080p-style 16:9 video.
- **Frame rate** defaults to "Maintain original" (fps is read from the
  source via ffprobe when the video loads; if ffprobe isn't available the
  option still works, it just omits the `-r` flag instead of showing a
  number). 23.976 is emitted as the exact `24000/1001` fraction rather than
  a rounded decimal.
- **Include original video name in exported files** (default on) names
  clips `{video_name}_{clip_name}.ext` instead of just `{clip_name}.ext`.
- **Save clip metadata** (default on) writes `{video_name}_clips_metadata.json`
  into the output folder alongside the clips: the source video's path,
  duration, resolution and fps; the export settings used; and each clip's
  name, output filename, start/end/duration.
