#!/usr/bin/env python3
"""
Pipeline Inspection OCR — Batch Runner

Processes a folder of CCTV inspection videos, extracts total footage surveyed,
date, and pipe/job ID from each video, and writes results to a CSV.

Usage:
    python run.py /path/to/videos/
    python run.py /path/to/videos/ --output results.csv --gpu
    python run.py /path/to/videos/ --profile "Envirosight ROVVER X"
    python run.py /path/to/videos/ --interval 3
"""

import argparse
import csv
import sys
import tempfile
from pathlib import Path

from engine import ocr as ocr_engine
from engine import video as vid
from engine import parser
from engine import profiles as prof

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mpg", ".mpeg", ".wmv", ".mkv", ".mts", ".m2ts"}


def find_videos(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    return sorted(p for p in input_path.rglob("*") if p.suffix.lower() in VIDEO_EXTENSIONS)


def process_video(video_path: Path, ocr, profile: dict | None, interval: int) -> dict:
    """
    Process a single video. Returns a result dict with keys:
    total_footage, unit, date, pipe_id, profile_used, status
    """
    result = {
        "total_footage": "",
        "unit": "",
        "date": "",
        "pipe_id": "",
        "profile_used": "",
        "status": "ok",
    }

    duration = vid.get_duration(video_path)
    if not duration:
        result["status"] = "error: could not read duration"
        return result

    # Determine effective interval and field crops
    eff_interval = interval or (profile.get("interval", 5) if profile else 5)
    max_plausible = profile.get("max_plausible_value", 5000) if profile else 5000
    result["profile_used"] = profile.get("name", "") if profile else "full-frame fallback"

    fields = (profile or {}).get("fields", {})
    footage_crop = (fields.get("footage") or {}).get("crop")
    date_crop    = (fields.get("date") or {}).get("crop")
    pipeid_crop  = (fields.get("pipe_id") or {}).get("crop")

    all_footage: list[tuple[float, str]] = []
    all_dates: list[str | None] = []
    all_pipe_ids: list[str | None] = []

    timestamps = vid.sample_frame_timestamps(duration, eff_interval)

    with tempfile.TemporaryDirectory() as tmpdir:
        for ts in timestamps:
            frame_path = Path(tmpdir) / f"frame_{int(ts)}.jpg"
            if not vid.extract_frame(video_path, ts, frame_path):
                continue

            # Footage field
            footage_texts = ocr_engine.run_ocr(ocr, frame_path, footage_crop)
            readings = parser.parse_footage(footage_texts)
            readings = parser.sanitize_footage(readings, max_plausible)
            all_footage.extend(readings)

            # Date field (only if a crop is defined or we're in fallback mode)
            if date_crop or not profile:
                date_texts = ocr_engine.run_ocr(ocr, frame_path, date_crop) if date_crop else footage_texts
                all_dates.append(parser.parse_date(date_texts))

            # Pipe ID field
            if pipeid_crop or not profile:
                id_texts = ocr_engine.run_ocr(ocr, frame_path, pipeid_crop) if pipeid_crop else footage_texts
                all_pipe_ids.append(parser.parse_pipe_id(id_texts))

    total, unit = parser.compute_total(all_footage)
    if total is None:
        result["status"] = "no_readings"
    else:
        result["total_footage"] = f"{total:.2f}"
        result["unit"] = unit

    result["date"] = parser.most_common_date(all_dates) or ""
    result["pipe_id"] = parser.most_common_pipe_id(all_pipe_ids) or ""

    return result


def main():
    ap = argparse.ArgumentParser(
        description="Extract total footage surveyed from pipeline inspection videos."
    )
    ap.add_argument("input", help="Video file or folder of videos")
    ap.add_argument("--output", default="results.csv", help="Output CSV path (default: results.csv)")
    ap.add_argument("--profile", default=None, help="Force a specific profile by name (skip auto-detect)")
    ap.add_argument("--interval", type=int, default=0,
                    help="Frame sampling interval in seconds (default: from profile or 5)")
    ap.add_argument("--gpu", action="store_true", help="Use GPU for OCR")
    ap.add_argument("--no-fallback", action="store_true",
                    help="Skip videos with no matching profile instead of using full-frame fallback")
    args = ap.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: '{input_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    videos = find_videos(input_path)
    if not videos:
        print("No video files found.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(videos)} video(s). Initialising OCR engine...")
    ocr = ocr_engine.init_ocr(use_gpu=args.gpu)

    # Resolve forced profile if --profile was given
    forced_profile = None
    if args.profile:
        all_profiles = prof.list_profiles()
        for p in all_profiles:
            if p.get("name", "").lower() == args.profile.lower():
                forced_profile = p
                break
        if not forced_profile:
            print(f"Warning: profile '{args.profile}' not found. Using auto-detect.", file=sys.stderr)

    output_path = Path(args.output)
    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(
            csvfile,
            fieldnames=["filename", "total_footage", "unit", "date", "pipe_id", "profile_used", "status"],
        )
        writer.writeheader()

        for i, video in enumerate(videos):
            prefix = f"[{i+1}/{len(videos)}] {video.name}"
            print(f"{prefix} ...", end=" ", flush=True)

            try:
                # Profile detection
                if forced_profile:
                    profile = forced_profile
                else:
                    with tempfile.TemporaryDirectory() as tmpdir:
                        probe_frame = Path(tmpdir) / "probe.jpg"
                        vid.extract_frame(video, 5, probe_frame)
                        profile = prof.match_profile(probe_frame) if probe_frame.exists() else None

                if profile is None and args.no_fallback:
                    row = {
                        "filename": video.name,
                        "total_footage": "", "unit": "", "date": "", "pipe_id": "",
                        "profile_used": "", "status": "profile_unknown",
                    }
                    writer.writerow(row)
                    csvfile.flush()
                    print("skipped (no profile match)")
                    continue

                result = process_video(video, ocr, profile, args.interval)
                row = {"filename": video.name, **result}
                writer.writerow(row)
                csvfile.flush()

                if result["status"] == "ok":
                    print(f"{result['total_footage']}{result['unit']}  [{result['profile_used']}]")
                else:
                    print(result["status"])

            except Exception as e:
                row = {
                    "filename": video.name,
                    "total_footage": "", "unit": "", "date": "", "pipe_id": "",
                    "profile_used": "", "status": f"error: {e}",
                }
                writer.writerow(row)
                csvfile.flush()
                print(f"ERROR: {e}")

    print(f"\nDone. Results saved to {output_path}")


if __name__ == "__main__":
    main()
