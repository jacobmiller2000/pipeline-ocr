"""
ffmpeg-based video utilities: duration detection and frame extraction.
"""

import subprocess
from pathlib import Path


def get_duration(video_path: str | Path) -> float | None:
    """Return video duration in seconds, or None if it can't be determined."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def extract_frame(video_path: str | Path, timestamp: float, output_path: str | Path) -> bool:
    """
    Extract a single frame at the given timestamp (seconds) to output_path.
    Returns True on success.
    """
    result = subprocess.run(
        [
            "ffmpeg", "-ss", str(timestamp),
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(output_path),
            "-y",
        ],
        capture_output=True,
    )
    return result.returncode == 0 and Path(output_path).exists()


def sample_frame_timestamps(duration: float, interval: int) -> list[float]:
    """
    Return a list of timestamps (in seconds) spaced `interval` seconds apart,
    covering the full video duration.
    """
    if duration <= 0:
        return [0.0]
    timestamps = list(range(0, int(duration), interval))
    if not timestamps:
        timestamps = [0]
    return [float(t) for t in timestamps]
