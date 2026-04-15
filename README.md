# pipeline-ocr

Extracts total footage/distance surveyed from CCTV pipeline inspection videos using OCR.

Supports multiple equipment types via per-equipment profiles. Processes batches of thousands of videos and outputs a CSV.

---

## Requirements

- Python 3.9+
- [ffmpeg](https://ffmpeg.org/download.html) installed and available on PATH

Install Python dependencies:

```bash
pip install -r requirements.txt
```

> **GPU users:** Replace `paddlepaddle` in `requirements.txt` with `paddlepaddle-gpu` before installing for significantly faster processing.

---

## Usage

### 1. Calibrate a new equipment type

Run the calibration GUI on a sample video from the equipment:

```bash
python calibrate.py
```

- Open a sample video
- Draw boxes around the footage counter, date, and pipe ID fields
- Name and save the profile

Profiles are saved to `profiles/` and committed to the repo so all teammates get them automatically.

### 2. Run batch extraction

```bash
python run.py /path/to/videos/

# Options:
python run.py /path/to/videos/ --output results.csv
python run.py /path/to/videos/ --profile "Envirosight ROVVER X"
python run.py /path/to/videos/ --interval 3
python run.py /path/to/videos/ --gpu
```

Output CSV columns: `filename, total_footage, unit, date, pipe_id, profile_used, status`

---

## Adding a New Equipment Type

1. Get one sample video from the new equipment
2. Run `python calibrate.py` and open the sample video
3. Draw crop boxes around each field
4. Save the profile
5. Commit `profiles/<name>.json` to the repo

---

## Project Structure

```
pipeline-ocr/
├── run.py          — batch runner (main entry point)
├── calibrate.py    — GUI tool for creating equipment profiles
├── engine/
│   ├── video.py    — frame extraction via ffmpeg
│   ├── ocr.py      — PaddleOCR wrapper
│   ├── parser.py   — regex parsing for footage, date, pipe ID
│   └── profiles.py — profile load/save/auto-detect
└── profiles/       — JSON equipment profiles (one per equipment type)
```
