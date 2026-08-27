"""ffmpeg discovery, probing, thumbnail extraction, and the export worker."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from typing import List, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from .models import Clip, SourceInfo
from .utils import sanitize_filename

_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

_OUT_TIME_RE = re.compile(r"out_time=(\d+):(\d+):(\d+(?:\.\d+)?)")

# ffmpeg -r arguments for well-known frame rates. 23.976/29.97/59.94 are the
# NTSC "drop-frame" rates and are best expressed as exact fractions rather
# than their rounded decimals.
FPS_CHOICES = [
    ("24", 24.0, "24"),
    ("25", 25.0, "25"),
    ("23.976", 23.976, "24000/1001"),
    ("30", 30.0, "30"),
    ("60", 60.0, "60"),
]

# Height-based scale presets (width is derived automatically to preserve
# the source's aspect ratio, so these work for non-16:9 sources too).
SCALE_CHOICES = [
    ("Source resolution", "source"),
    ("2160p (4K)", 2160),
    ("1440p (QHD)", 1440),
    ("1080p (Full HD)", 1080),
    ("720p (HD)", 720),
    ("480p", 480),
]


def get_ffmpeg_path() -> Optional[str]:
    """Prefer a system ffmpeg; fall back to the bundled binary from imageio-ffmpeg."""
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def get_ffprobe_path() -> Optional[str]:
    return shutil.which("ffprobe")


def _run_hidden(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, creationflags=_CREATE_NO_WINDOW, **kwargs)


def _parse_fraction(text: str) -> Optional[float]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        if "/" in text:
            num, den = text.split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else None
        return float(text)
    except (ValueError, ZeroDivisionError):
        return None


def probe_video(ffmpeg_path: Optional[str], ffprobe_path: Optional[str],
                 video_path: str) -> SourceInfo:
    """Best-effort discovery of duration/resolution/fps for the source video.

    Prefers ffprobe's JSON output; falls back to parsing `ffmpeg -i` stderr
    if ffprobe isn't installed. Never raises - returns a mostly-empty
    SourceInfo on total failure.
    """
    if ffprobe_path:
        try:
            proc = _run_hidden(
                [ffprobe_path, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,r_frame_rate:format=duration",
                 "-of", "json", video_path],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
            data = json.loads(proc.stdout or "{}")
            fmt = data.get("format", {}) or {}
            streams = data.get("streams") or [{}]
            stream0 = streams[0] or {}
            duration = float(fmt.get("duration", 0) or 0)
            width = int(stream0.get("width", 0) or 0)
            height = int(stream0.get("height", 0) or 0)
            fps = _parse_fraction(stream0.get("r_frame_rate", ""))
            if duration or width or height or fps:
                return SourceInfo(duration=duration, width=width, height=height, fps=fps)
        except Exception:
            pass

    if not ffmpeg_path:
        return SourceInfo()

    try:
        proc = _run_hidden([ffmpeg_path, "-i", video_path],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        err = proc.stderr or ""
    except Exception:
        return SourceInfo()

    duration = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if m:
        duration = hms_to_seconds(*m.groups())
    width = height = 0
    m = re.search(r"(\d{2,5})x(\d{2,5})", err)
    if m:
        width, height = int(m.group(1)), int(m.group(2))
    fps = None
    m = re.search(r"([\d.]+)\s*fps", err)
    if m:
        fps = float(m.group(1))
    return SourceInfo(duration=duration, width=width, height=height, fps=fps)


def extract_thumbnail_bytes(ffmpeg_path: str, video_path: str, time_sec: float,
                             width: int = 320) -> bytes:
    """Grab a single JPEG frame near `time_sec` and return its raw bytes."""
    time_sec = max(0.0, time_sec)
    cmd = [
        ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{time_sec:.3f}", "-i", video_path,
        "-frames:v", "1",
        "-vf", f"scale={width}:-2",
        "-f", "image2", "-c:v", "mjpeg",
        "pipe:1",
    ]
    proc = _run_hidden(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError("ffmpeg produced no thumbnail data")
    return proc.stdout


def hms_to_seconds(h: str, m: str, s: str) -> float:
    return int(h) * 3600 + int(m) * 60 + float(s)


def build_ffmpeg_cmd(ffmpeg_path: str, source: str, clip: Clip, settings: dict,
                      out_path: str) -> List[str]:
    """Build the ffmpeg command line to extract one clip.

    Uses the "fast seek then accurate seek" trick (-ss before AND after -i)
    so re-encoded clips start on the exact frame while still benefiting from
    a fast keyframe seek for anything before that. Stream-copy mode only
    supports the fast (keyframe-snapped) seek, which is the usual ffmpeg
    trade-off for not re-encoding.
    """
    start = max(0.0, clip.start)
    duration = max(0.01, clip.duration())
    video_codec = settings.get("video_codec", "libx264")

    cmd = [ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error"]

    if video_codec == "copy":
        cmd += ["-ss", f"{start:.3f}", "-i", source, "-t", f"{duration:.3f}"]
        cmd += ["-c:v", "copy"]
    else:
        outer = max(0.0, start - 5.0)
        inner = start - outer
        cmd += ["-ss", f"{outer:.3f}", "-i", source,
                "-ss", f"{inner:.3f}", "-t", f"{duration:.3f}"]

        vf = []
        scale = settings.get("scale", "source")
        if scale != "source":
            # Scale to a target *height*, deriving width automatically
            # (-2 keeps it even) so non-16:9 sources aren't distorted.
            vf.append(f"scale=-2:{int(scale)}:flags=lanczos")
        if vf:
            cmd += ["-vf", ",".join(vf)]

        cmd += ["-c:v", video_codec]
        if video_codec in ("libx264", "libx265"):
            cmd += ["-preset", settings.get("preset", "medium"),
                    "-crf", str(settings.get("crf", 20))]
            if video_codec == "libx264":
                cmd += ["-pix_fmt", "yuv420p"]
        elif video_codec == "libvpx-vp9":
            cmd += ["-b:v", "0", "-crf", str(settings.get("crf", 32))]

        fps_arg = settings.get("fps_arg")
        if fps_arg:
            cmd += ["-r", str(fps_arg)]

    if settings.get("include_audio", True):
        audio_codec = settings.get("audio_codec", "aac")
        cmd += ["-c:a", audio_codec]
        if audio_codec != "copy":
            cmd += ["-b:a", settings.get("audio_bitrate", "192k")]
    else:
        cmd += ["-an"]

    if out_path.lower().endswith(".mp4"):
        cmd += ["-movflags", "+faststart"]

    cmd += ["-progress", "pipe:1", "-nostats", out_path]
    return cmd


def build_output_basename(video_path: str, clip_name: str, include_video_name: bool) -> str:
    clip_part = sanitize_filename(clip_name)
    if not include_video_name:
        return clip_part
    video_stem = sanitize_filename(os.path.splitext(os.path.basename(video_path))[0])
    return f"{video_stem}_{clip_part}"


class Exporter(QThread):
    """Runs ffmpeg once per clip in sequence, reporting fine-grained progress."""

    clip_started = pyqtSignal(int, int, str)      # index, total, clip name
    clip_progress = pyqtSignal(int, float)          # index, percent 0-100
    overall_progress = pyqtSignal(float, object)     # percent 0-100, eta seconds (or None)
    finished_all = pyqtSignal(bool, str)             # success, message

    def __init__(self, ffmpeg_path: str, source_path: str, clips: List[Clip],
                 output_dir: str, settings: dict, ext: str,
                 source_info: Optional[SourceInfo] = None, parent=None):
        super().__init__(parent)
        self.ffmpeg_path = ffmpeg_path
        self.source_path = source_path
        self.clips = clips
        self.output_dir = output_dir
        self.settings = settings
        self.ext = ext
        self.source_info = source_info
        self._cancelled = False
        self._current_proc: Optional[subprocess.Popen] = None

    def request_cancel(self):
        self._cancelled = True
        if self._current_proc and self._current_proc.poll() is None:
            try:
                self._current_proc.terminate()
            except Exception:
                pass

    def run(self):
        clips = self.clips
        total_duration = sum(c.duration() for c in clips) or 1.0
        completed_duration = 0.0
        start_time = time.time()
        used_names: dict[str, int] = {}
        include_video_name = self.settings.get("include_video_name", True)
        exported_records = []

        for idx, clip in enumerate(clips):
            if self._cancelled:
                self.finished_all.emit(False, "Export cancelled.")
                return

            base = build_output_basename(self.source_path, clip.name, include_video_name)
            used_names[base] = used_names.get(base, 0) + 1
            suffix = "" if used_names[base] == 1 else f" ({used_names[base]})"
            out_name = f"{base}{suffix}{self.ext}"
            out_path = os.path.join(self.output_dir, out_name)

            self.clip_started.emit(idx, len(clips), clip.name)
            cmd = build_ffmpeg_cmd(self.ffmpeg_path, self.source_path, clip,
                                    self.settings, out_path)

            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    universal_newlines=True, creationflags=_CREATE_NO_WINDOW,
                )
            except Exception as exc:
                self.finished_all.emit(False, f"Could not start ffmpeg: {exc}")
                return

            self._current_proc = proc
            clip_dur = max(clip.duration(), 0.01)

            if proc.stdout is not None:
                for line in proc.stdout:
                    if self._cancelled:
                        break
                    m = _OUT_TIME_RE.search(line)
                    if not m:
                        continue
                    secs = hms_to_seconds(*m.groups())
                    pct = min(100.0, secs / clip_dur * 100.0)
                    self.clip_progress.emit(idx, pct)

                    overall_secs = completed_duration + min(secs, clip_dur)
                    overall_pct = min(100.0, overall_secs / total_duration * 100.0)
                    elapsed = time.time() - start_time
                    frac = overall_pct / 100.0
                    eta = elapsed * (1 - frac) / frac if frac > 0.02 else None
                    self.overall_progress.emit(overall_pct, eta)

            proc.wait()
            self._current_proc = None

            if self._cancelled:
                self.finished_all.emit(False, "Export cancelled.")
                return
            if proc.returncode != 0:
                self.finished_all.emit(False, f"ffmpeg failed while exporting '{clip.name}'.")
                return

            completed_duration += clip_dur
            self.clip_progress.emit(idx, 100.0)
            overall_pct = min(100.0, completed_duration / total_duration * 100.0)
            self.overall_progress.emit(overall_pct, 0.0)

            exported_records.append({
                "name": clip.name,
                "output_file": out_name,
                "start_seconds": round(clip.start, 3),
                "end_seconds": round(clip.end, 3),
                "duration_seconds": round(clip.duration(), 3),
            })

        if self.settings.get("save_metadata", True):
            self._write_metadata(exported_records)

        self.finished_all.emit(True, f"Exported {len(clips)} clip(s) to {self.output_dir}")

    def _write_metadata(self, clip_records: list):
        info = self.source_info
        video_stem = sanitize_filename(os.path.splitext(os.path.basename(self.source_path))[0])
        exportable_settings = {k: v for k, v in self.settings.items() if k != "output_dir"}
        manifest = {
            "source_video": {
                "path": self.source_path,
                "filename": os.path.basename(self.source_path),
                "duration_seconds": round(info.duration, 3) if info else None,
                "width": info.width if info else None,
                "height": info.height if info else None,
                "fps": round(info.fps, 3) if info and info.fps else None,
            },
            "export_settings": exportable_settings,
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "clips": clip_records,
        }
        path = os.path.join(self.output_dir, f"{video_stem}_clips_metadata.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
        except Exception:
            pass  # metadata is best-effort; never fail the export because of it


class ThumbnailWorker(QThread):
    """Fetches one thumbnail frame off the UI thread."""

    ready = pyqtSignal(int, bytes)
    failed = pyqtSignal(int, str)

    def __init__(self, ffmpeg_path: str, clip_id: int, video_path: str, time_sec: float,
                 parent=None):
        super().__init__(parent)
        self.ffmpeg_path = ffmpeg_path
        self.clip_id = clip_id
        self.video_path = video_path
        self.time_sec = time_sec

    def run(self):
        try:
            data = extract_thumbnail_bytes(self.ffmpeg_path, self.video_path, self.time_sec)
            self.ready.emit(self.clip_id, data)
        except Exception as exc:
            self.failed.emit(self.clip_id, str(exc))


class ProbeWorker(QThread):
    """Fetches source video metadata (duration/resolution/fps) off the UI thread."""

    ready = pyqtSignal(object)  # SourceInfo

    def __init__(self, ffmpeg_path: Optional[str], ffprobe_path: Optional[str],
                 video_path: str, parent=None):
        super().__init__(parent)
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.video_path = video_path

    def run(self):
        info = probe_video(self.ffmpeg_path, self.ffprobe_path, self.video_path)
        self.ready.emit(info)
