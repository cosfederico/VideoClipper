"""Data model for a single extracted clip."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Optional, Tuple

_id_seq = itertools.count(1)


@dataclass
class Clip:
    start: float
    end: float
    name: str
    color: Tuple[int, int, int]
    id: int = field(default_factory=lambda: next(_id_seq))
    thumbnail: object = None  # QPixmap, filled in asynchronously

    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def contains(self, t: float) -> bool:
        """True if `t` falls strictly inside [start, end) of this clip."""
        return self.start <= t < self.end

    def overlaps(self, start: float, end: float) -> bool:
        """True if the half-open range [start, end) overlaps this clip."""
        return not (end <= self.start or start >= self.end)


@dataclass
class SourceInfo:
    """What we know about the loaded source video (best-effort; fields may
    be missing/None if ffprobe isn't available)."""
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: Optional[float] = None
