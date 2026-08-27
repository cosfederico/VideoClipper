"""Video probing, thumbnail extraction, and clip export - all via PyAV.

PyAV bundles FFmpeg's libraries directly, so there's no system ffmpeg
binary, PATH lookup, or subprocess involved. Playback (video_widget.py)
uses Qt's own multimedia backend and is unaffected.

Two PyAV/libavcodec gotchas - see CLAUDE.md for details:
- An output video stream's `width`/`height` must be set explicitly before
  the first `encode()` call, or it silently opens at 640x480.
- `Container.seek(offset, stream=X, ...)` interprets `offset` in stream
  X's `time_base`, not `av.time_base` - omit `stream=` unless converting.
"""
from __future__ import annotations

import fractions
import io
import json
import os
import time
from typing import List, Optional, Tuple

import av
from PyQt6.QtCore import QThread, pyqtSignal

from .models import Clip, SourceInfo
from .utils import sanitize_filename

# Well-known frame rates as exact Fraction objects. 23.976/29.97/59.94 are
# the NTSC "drop-frame" rates and are best expressed as exact fractions
# rather than their rounded decimals.
FPS_CHOICES = [
    ("24", 24.0, fractions.Fraction(24, 1)),
    ("25", 25.0, fractions.Fraction(25, 1)),
    ("23.976", 23.976, fractions.Fraction(24000, 1001)),
    ("30", 30.0, fractions.Fraction(30, 1)),
    ("60", 60.0, fractions.Fraction(60, 1)),
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

# WebM can only mux Vorbis/Opus audio, never AAC - this is the sole audio
# codec choice offered when the container is WebM (see export_dialog.py).
WEBM_AUDIO_CODEC = "libopus"
_OPUS_RATE = 48000  # Opus only accepts 8k/12k/16k/24k/48k

_SEEK_LOOKBACK = 5.0  # seconds of slack before base_offset to still accept a packet


def probe_video(video_path: str) -> SourceInfo:
    """Best-effort discovery of duration/resolution/fps for the source video.

    Never raises - returns a mostly-empty SourceInfo on total failure.
    """
    try:
        with av.open(video_path) as container:
            vstream = next((s for s in container.streams if s.type == "video"), None)
            duration = 0.0
            if container.duration is not None:
                duration = float(container.duration) / av.time_base
            elif vstream is not None and vstream.duration is not None:
                duration = float(vstream.duration * vstream.time_base)
            width = vstream.width if vstream else 0
            height = vstream.height if vstream else 0
            fps = None
            if vstream is not None:
                rate = vstream.average_rate or vstream.guessed_rate
                if rate:
                    fps = float(rate)
            return SourceInfo(duration=duration, width=width or 0, height=height or 0, fps=fps)
    except Exception:
        return SourceInfo()


def extract_thumbnail_bytes(video_path: str, time_sec: float, width: int = 320) -> bytes:
    """Grab a single JPEG frame near `time_sec` and return its raw bytes."""
    time_sec = max(0.0, time_sec)
    with av.open(video_path) as container:
        vstream = container.streams.video[0]
        container.seek(int(time_sec * av.time_base), any_frame=False, backward=True)
        frame = None
        for candidate in container.decode(vstream):
            if candidate.pts is not None and float(candidate.pts * candidate.time_base) >= time_sec - 0.5:
                frame = candidate
                break
        if frame is None:
            raise RuntimeError("could not decode a frame near that timestamp")
        img = frame.to_image()
        out_w = max(2, width)
        out_h = max(2, int(img.height * (out_w / img.width) / 2) * 2)
        img = img.resize((out_w, out_h))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()


def build_output_basename(video_path: str, clip_name: str, include_video_name: bool) -> str:
    clip_part = sanitize_filename(clip_name)
    if not include_video_name:
        return clip_part
    video_stem = sanitize_filename(os.path.splitext(os.path.basename(video_path))[0])
    return f"{video_stem}_{clip_part}"


def _scaled_dims(width: int, height: int, target_height) -> Tuple[int, int]:
    """Scale to a target *height*, deriving width automatically (kept even)
    so non-16:9 sources aren't distorted - equivalent to ffmpeg's scale=-2:H."""
    if target_height == "source" or not target_height or not width or not height:
        return width, height
    out_h = int(target_height)
    out_w = int(round(width * out_h / height))
    out_w -= out_w % 2
    out_h -= out_h % 2
    return max(2, out_w), max(2, out_h)


class _ExportError(Exception):
    """An expected, reportable export failure - message is user-facing."""


class Exporter(QThread):
    """Extracts one clip per iteration via PyAV, reporting fine-grained progress.

    Each of video/audio is independently either stream-copied (remuxed
    without decoding - fast, but keyframe-snapped like ffmpeg's `-c copy`)
    or re-encoded (frame-accurate; scale/fps/crf/preset applied), matching
    whatever combination the export settings ask for.
    """

    clip_started = pyqtSignal(int, int, str)       # index, total, clip name
    clip_progress = pyqtSignal(int, float)          # index, percent 0-100
    overall_progress = pyqtSignal(float, object)    # percent 0-100, eta seconds (or None)
    finished_all = pyqtSignal(bool, str)            # success, message

    def __init__(self, source_path: str, clips: List[Clip], output_dir: str,
                 settings: dict, ext: str, source_info: Optional[SourceInfo] = None,
                 parent=None):
        super().__init__(parent)
        self.source_path = source_path
        self.clips = clips
        self.output_dir = output_dir
        self.settings = settings
        self.ext = ext
        self.source_info = source_info
        self._cancelled = False

    def request_cancel(self):
        self._cancelled = True

    # ------------------------------------------------------------------
    def run(self):
        clips = self.clips
        total_duration = sum(c.duration() for c in clips) or 1.0
        completed_duration = 0.0
        start_time = time.time()
        used_names: dict = {}
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

            try:
                self._export_one(clip, idx, out_path, completed_duration, total_duration, start_time)
            except _ExportError as exc:
                self.finished_all.emit(False, f"{exc} while exporting '{clip.name}'.")
                return
            except Exception as exc:
                self.finished_all.emit(False, f"Failed exporting '{clip.name}': {exc}")
                return

            if self._cancelled:
                self.finished_all.emit(False, "Export cancelled.")
                return

            completed_duration += max(clip.duration(), 0.01)
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

    # ------------------------------------------------------------------
    def _peek_copy_start_t(self, in_v_index: int, start: float) -> float:
        """Find the keyframe at/before `start` that stream-copy mode will
        actually cut on, via a second throwaway open."""
        peek = av.open(self.source_path)
        try:
            v = peek.streams.video[in_v_index]
            peek.seek(int(start / v.time_base), stream=v, any_frame=False, backward=True)
            for packet in peek.demux(v):
                if packet.dts is None:
                    continue
                return float(packet.pts * packet.time_base)
        finally:
            peek.close()
        return start

    def _export_one(self, clip: Clip, idx: int, out_path: str,
                     completed_duration: float, total_duration: float, start_time: float):
        settings = self.settings
        start, end = max(0.0, clip.start), clip.end
        clip_dur = max(clip.duration(), 0.01)

        video_codec = settings.get("video_codec", "libx264")
        video_copy = video_codec == "copy"
        include_audio = settings.get("include_audio", True)
        audio_codec = settings.get("audio_codec", "aac")
        audio_copy = include_audio and audio_codec == "copy"

        in_c = av.open(self.source_path)
        try:
            if not in_c.streams.video:
                raise _ExportError("Source has no video stream")
            in_v = in_c.streams.video[0]
            in_a = in_c.streams.audio[0] if (include_audio and in_c.streams.audio) else None

            base_offset = self._peek_copy_start_t(0, start) if video_copy else start

            try:
                out_c = av.open(out_path, mode="w",
                                 options={"movflags": "faststart"} if out_path.lower().endswith(".mp4") else None)
            except Exception as exc:
                raise _ExportError(f"Could not create output file ({exc})")

            try:
                out_v, v_graph = self._make_video_output(out_c, in_v, video_codec, video_copy, settings)
                out_a, resampler = self._make_audio_output(out_c, in_a, audio_codec, audio_copy, settings)

                in_c.seek(int(base_offset * av.time_base), any_frame=False, backward=True)

                video_done = False
                audio_done = in_a is None
                last_pct = -1.0
                target_streams = [in_v] + ([in_a] if in_a is not None else [])

                for packet in in_c.demux(target_streams):
                    if self._cancelled:
                        return
                    if video_done and audio_done:
                        break
                    if packet.dts is None:
                        continue
                    is_video = packet.stream.type == "video"
                    t = float(packet.pts * packet.time_base)

                    if is_video:
                        if video_done:
                            continue
                        if t > end:
                            video_done = True
                            continue
                        if t < base_offset - _SEEK_LOOKBACK:
                            continue
                        if video_copy:
                            self._remux_packet(out_c, out_v, packet, base_offset)
                        else:
                            self._reencode_video_packet(packet, base_offset, end, v_graph, out_v, out_c)
                    else:
                        if audio_done:
                            continue
                        if t > end:
                            audio_done = True
                            continue
                        if t < base_offset - _SEEK_LOOKBACK:
                            continue
                        if audio_copy:
                            self._remux_packet(out_c, out_a, packet, base_offset)
                        else:
                            self._reencode_audio_packet(packet, base_offset, end, resampler, out_a, out_c)

                    pct = max(0.0, min(100.0, (t - base_offset) / clip_dur * 100.0))
                    if pct - last_pct >= 1.0:
                        last_pct = pct
                        self._emit_progress(idx, pct, completed_duration, total_duration, start_time)

                if not video_copy:
                    for pkt in out_v.encode():
                        out_c.mux(pkt)
                if out_a is not None and not audio_copy:
                    for rframe in (resampler.resample(None) or []):
                        for pkt in out_a.encode(rframe):
                            out_c.mux(pkt)
                    for pkt in out_a.encode():
                        out_c.mux(pkt)
            finally:
                out_c.close()
        finally:
            in_c.close()

    def _emit_progress(self, idx, pct, completed_duration, total_duration, start_time):
        self.clip_progress.emit(idx, pct)
        overall_secs = completed_duration + pct / 100.0 * max(0.01, self.clips[idx].duration())
        overall_pct = min(100.0, overall_secs / total_duration * 100.0)
        elapsed = time.time() - start_time
        frac = overall_pct / 100.0
        eta = elapsed * (1 - frac) / frac if frac > 0.02 else None
        self.overall_progress.emit(overall_pct, eta)

    # -- stream setup ----------------------------------------------------
    def _make_video_output(self, out_c, in_v, video_codec, video_copy, settings):
        if video_copy:
            return out_c.add_stream_from_template(in_v), None

        out_w, out_h = _scaled_dims(in_v.width, in_v.height, settings.get("scale", "source"))
        target_fps = settings.get("fps_arg") or (in_v.average_rate or in_v.guessed_rate) or fractions.Fraction(30, 1)

        try:
            out_v = out_c.add_stream(video_codec, rate=target_fps)
        except Exception as exc:
            raise _ExportError(f"Could not start the '{video_codec}' encoder ({exc})")
        out_v.width, out_v.height = out_w, out_h  # must be set before encode() - see module docstring
        out_v.pix_fmt = "yuv420p"

        opts = {}
        if video_codec in ("libx264", "libx265"):
            opts["crf"] = str(settings.get("crf", 20))
            opts["preset"] = settings.get("preset", "medium")
        elif video_codec == "libvpx-vp9":
            out_v.bit_rate = 0  # required for CRF (constant-quality) mode
            opts["crf"] = str(settings.get("crf", 32))
        out_v.options = opts

        graph = av.filter.Graph()
        node = graph.add_buffer(template=in_v)
        if (out_w, out_h) != (in_v.width, in_v.height):
            scale = graph.add("scale", f"{out_w}:{out_h}:flags=lanczos")
            node.link_to(scale)
            node = scale
        fps_filter = graph.add("fps", str(target_fps))
        node.link_to(fps_filter)
        sink = graph.add("buffersink")
        fps_filter.link_to(sink)
        graph.configure()
        return out_v, graph

    def _make_audio_output(self, out_c, in_a, audio_codec, audio_copy, settings):
        if in_a is None:
            return None, None
        if audio_copy:
            return out_c.add_stream_from_template(in_a), None

        target_rate = _OPUS_RATE if audio_codec == "libopus" else in_a.rate
        try:
            out_a = out_c.add_stream(audio_codec, rate=target_rate)
        except Exception as exc:
            raise _ExportError(f"Could not start the '{audio_codec}' audio encoder ({exc})")
        if audio_codec != "libopus":
            bitrate = settings.get("audio_bitrate", "192k")
            try:
                out_a.bit_rate = int(str(bitrate).rstrip("kK")) * 1000
            except ValueError:
                pass
        resampler = av.AudioResampler(format=out_a.format, layout=out_a.layout, rate=out_a.rate)
        return out_a, resampler

    # -- per-packet handling ----------------------------------------------
    @staticmethod
    def _remux_packet(out_c, out_stream, packet, base_offset):
        offset_ticks = int(base_offset / packet.time_base)
        packet.pts -= offset_ticks
        packet.dts -= offset_ticks
        if packet.pts < 0 or packet.dts < 0:
            return
        packet.stream = out_stream
        out_c.mux(packet)

    @staticmethod
    def _reencode_video_packet(packet, base_offset, end, graph, out_v, out_c):
        for frame in packet.decode():
            ft = float(frame.pts * frame.time_base) if frame.pts is not None else None
            if ft is None or ft < base_offset or ft > end:
                continue
            graph.push(frame)
            while True:
                try:
                    filtered = graph.pull()
                except (av.EOFError, av.error.BlockingIOError):
                    break
                filtered.pts = None  # let the encoder assign fresh, monotonic pts
                for pkt in out_v.encode(filtered):
                    out_c.mux(pkt)

    @staticmethod
    def _reencode_audio_packet(packet, base_offset, end, resampler, out_a, out_c):
        for frame in packet.decode():
            ft = float(frame.pts * frame.time_base) if frame.pts is not None else None
            if ft is None or ft < base_offset or ft > end:
                continue
            frame.pts = None
            for rframe in (resampler.resample(frame) or []):
                for pkt in out_a.encode(rframe):
                    out_c.mux(pkt)

    # ------------------------------------------------------------------
    def _write_metadata(self, clip_records: list):
        info = self.source_info
        video_stem = sanitize_filename(os.path.splitext(os.path.basename(self.source_path))[0])
        exportable_settings = {k: v for k, v in self.settings.items() if k != "output_dir"}
        for key, value in list(exportable_settings.items()):
            if isinstance(value, fractions.Fraction):
                exportable_settings[key] = str(value)
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

    def __init__(self, clip_id: int, video_path: str, time_sec: float, parent=None):
        super().__init__(parent)
        self.clip_id = clip_id
        self.video_path = video_path
        self.time_sec = time_sec

    def run(self):
        try:
            data = extract_thumbnail_bytes(self.video_path, self.time_sec)
            self.ready.emit(self.clip_id, data)
        except Exception as exc:
            self.failed.emit(self.clip_id, str(exc))


class ProbeWorker(QThread):
    """Fetches source video metadata (duration/resolution/fps) off the UI thread."""

    ready = pyqtSignal(object)  # SourceInfo

    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)
        self.video_path = video_path

    def run(self):
        info = probe_video(self.video_path)
        self.ready.emit(info)
