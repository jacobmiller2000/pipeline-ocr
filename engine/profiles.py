"""
Equipment profile management: load, save, and auto-detect profiles.
"""

import json
from pathlib import Path

import imagehash
from PIL import Image

PROFILES_DIR = Path(__file__).parent.parent / "profiles"
HASH_THRESHOLD = 15  # Max hamming distance to consider a profile a match


def load_profile(path: str | Path) -> dict:
    """Load a profile JSON file and return it as a dict."""
    with open(path) as f:
        return json.load(f)


def list_profiles() -> list[dict]:
    """Return all profiles found in the profiles/ directory."""
    profiles = []
    for p in sorted(PROFILES_DIR.glob("*.json")):
        if p.name == "example.json":
            continue
        try:
            profiles.append(load_profile(p))
        except Exception:
            pass
    return profiles


def save_profile(data: dict, name: str) -> Path:
    """
    Save a profile dict to profiles/<name>.json.
    Returns the saved file path.
    """
    PROFILES_DIR.mkdir(exist_ok=True)
    safe_name = name.replace(" ", "_").replace("/", "-")
    path = PROFILES_DIR / f"{safe_name}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def _compute_hash(frame_path: str | Path, region: list) -> str:
    """Compute a perceptual hash of a specific region of a frame."""
    x, y, w, h = region
    img = Image.open(frame_path)
    cropped = img.crop((x, y, x + w, y + h))
    return str(imagehash.phash(cropped))


def compute_fingerprint_hash(frame_path: str | Path, region: list) -> str:
    """Public helper used by calibrate.py to generate a fingerprint hash."""
    return _compute_hash(frame_path, region)


def match_profile(frame_path: str | Path) -> dict | None:
    """
    Compare a video frame against all known profiles using perceptual hashing.
    Returns the best-matching profile dict, or None if no match is close enough.
    """
    profiles = list_profiles()
    if not profiles:
        return None

    best_profile = None
    best_distance = HASH_THRESHOLD + 1

    for profile in profiles:
        fp = profile.get("fingerprint")
        if not fp or not fp.get("hash") or not fp.get("region"):
            continue
        try:
            frame_hash = imagehash.hex_to_hash(_compute_hash(frame_path, fp["region"]))
            stored_hash = imagehash.hex_to_hash(fp["hash"])
            distance = frame_hash - stored_hash
            if distance < best_distance:
                best_distance = distance
                best_profile = profile
        except Exception:
            continue

    return best_profile if best_distance <= HASH_THRESHOLD else None
