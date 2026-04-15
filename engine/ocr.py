"""
PaddleOCR wrapper. Initialise once and reuse across all videos.
"""

from pathlib import Path
from PIL import Image


def init_ocr(use_gpu: bool = False):
    """
    Create and return a PaddleOCR instance.
    Call once at startup and pass the result to run_ocr().
    """
    from paddleocr import PaddleOCR
    return PaddleOCR(
        use_angle_cls=False,
        lang="en",
        use_gpu=use_gpu,
        show_log=False,
    )


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
        # Clamp to image bounds
        x2 = min(x + w, img_w)
        y2 = min(y + h, img_h)
        cropped = img.crop((x, y, x2, y2))
        tmp_path = frame_path.with_suffix(".crop.jpg")
        cropped.save(tmp_path)
        target = str(tmp_path)
    else:
        target = str(frame_path)

    result = ocr.ocr(target, cls=False)

    texts = []
    if result and result[0]:
        for line in result[0]:
            if line and len(line) > 1 and line[1]:
                texts.append(line[1][0])

    # Clean up temp crop file
    if crop:
        Path(target).unlink(missing_ok=True)

    return texts
