"""Project save/load: a JSON snapshot of a VideoClipper session - source
video path, clips, and the last-used export settings."""
from __future__ import annotations

import fractions
import json
import time
from typing import List, Optional

from .models import Clip

PROJECT_FORMAT_VERSION = 1


def _settings_to_json(settings: Optional[dict]) -> Optional[dict]:
    if not settings:
        return None
    out = {}
    for key, value in settings.items():
        if isinstance(value, fractions.Fraction):
            value = {"__fraction__": str(value)}
        out[key] = value
    return out


def _settings_from_json(data: Optional[dict]) -> Optional[dict]:
    if not data:
        return None
    out = {}
    for key, value in data.items():
        if isinstance(value, dict) and "__fraction__" in value:
            value = fractions.Fraction(value["__fraction__"])
        out[key] = value
    return out


def save_project(path: str, video_path: Optional[str], clips: List[Clip],
                  clip_name_counter: int, export_settings: Optional[dict]):
    data = {
        "format_version": PROJECT_FORMAT_VERSION,
        "video_path": video_path,
        "clip_name_counter": clip_name_counter,
        "clips": [
            {"name": c.name, "start": c.start, "end": c.end, "color": list(c.color)}
            for c in clips
        ],
        "export_settings": _settings_to_json(export_settings),
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_project(path: str) -> dict:
    """Raises on missing/invalid files - callers should catch and report."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    clips = [
        Clip(start=float(c["start"]), end=float(c["end"]), name=c["name"],
             color=tuple(c["color"]))
        for c in data.get("clips", [])
    ]
    return {
        "video_path": data.get("video_path"),
        "clips": clips,
        "clip_name_counter": data.get("clip_name_counter", len(clips)),
        "export_settings": _settings_from_json(data.get("export_settings")),
    }
