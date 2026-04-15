"""
PaddleOCR wrapper. Initialise once and reuse across all videos.
Compatible with PaddleOCR v3+.
"""

import os
import logging
from pathlib import Path
from PIL import Image

# Suppress PaddleOCR's connectivity check and verbose logging
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


def _suppress_paddle_logging():
    for name in logging.root.manager.loggerDict:
        if "paddle" in name.lower() or "ppocr" in name.lower():
            logging.getLogger(name).setLevel(logging.ERROR)


def init_ocr(use_gpu: bool = False):
    """
    Create and return a PaddleOCR instance.
    Call once at startup and pass the result to run_ocr().
    """
    _suppress_paddle_logging()
    from paddleocr import PaddleOCR

    kwargs = dict(
        lang="en",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    if use_gpu:
        kwargs["device"] = "gpu"

    return PaddleOCR(**kwargs)


def run_ocr(ocr, frame_path: str | Path, crop: tuple | None = None) -> list[str]:
    """
    Run OCR on a frame, optionally cropping to (x, y, width, height) first.
    Returns a list of detected text strings.
    """
    frame_path = Path(frame_path)
    if not frame_path.exists():
        return []

    if crop:
        x, y, w, h = crop
        img = Image.open(frame_path)
        img_w, img_h = img.size
        x2 = min(x + w, img_w)
        y2 = min(y + h, img_h)
        cropped = img.crop((x, y, x2, y2))
        tmp_path = frame_path.with_suffix(".crop.jpg")
        cropped.save(tmp_path)
        target = str(tmp_path)
    else:
        target = str(frame_path)

    result = ocr.predict(target)

    texts = []
    if result:
        for item in result:
            texts.extend(item.get("rec_texts", []))

    if crop:
        Path(target).unlink(missing_ok=True)

    return texts
