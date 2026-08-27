"""Small stateless helpers shared across the app."""
from __future__ import annotations

import colorsys
import random
import re
from typing import Optional


def format_time(seconds: float, always_hours: bool = False) -> str:
    """Format a second count as M:SS or H:MM:SS."""
    seconds = max(0.0, seconds)
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h or always_hours:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def format_time_ms(seconds: float) -> str:
    """Format with a tenth-of-a-second, used for the live playhead readout."""
    seconds = max(0.0, seconds)
    total_tenths = int(round(seconds * 10))
    s, tenths = divmod(total_tenths, 10)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}.{tenths}"
    return f"{m:d}:{s:02d}.{tenths}"


def sanitize_filename(name: str) -> str:
    name = (name or "").strip() or "clip"
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:80] or "clip"


def random_pleasant_color() -> tuple[int, int, int]:
    """A random, readable accent color (mid saturation/lightness pastel-ish)."""
    hue = random.random()
    sat = 0.55 + random.random() * 0.25
    light = 0.48 + random.random() * 0.12
    r, g, b = colorsys.hls_to_rgb(hue, light, sat)
    return (int(r * 255), int(g * 255), int(b * 255))


def format_fps(fps: Optional[float]) -> str:
    """Format a frame rate for display, e.g. 25.0 -> '25', 29.97 -> '29.97'."""
    if not fps or fps <= 0:
        return ""
    rounded = round(fps, 3)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.3f}".rstrip("0").rstrip(".")


def nice_time_step(duration: float, pixel_width: float) -> float:
    """Pick a pleasant tick spacing (in seconds) for a timeline ruler."""
    if duration <= 0 or pixel_width <= 0:
        return 1.0
    target_ticks = max(2, int(pixel_width // 90))
    raw = duration / target_ticks
    steps = (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200)
    for step in steps:
        if raw <= step:
            return float(step)
    return float(steps[-1])
