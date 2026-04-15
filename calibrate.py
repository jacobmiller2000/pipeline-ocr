#!/usr/bin/env python3
"""
Pipeline Inspection OCR — Calibration Tool

GUI for creating equipment profiles. Open a sample video, draw crop boxes
around the footage counter, date, and pipe ID fields, then save as a profile.

Usage:
    python calibrate.py
    python calibrate.py /path/to/sample_video.mp4
"""

import sys
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from PIL import Image, ImageTk

from engine import video as vid
from engine import ocr as ocr_engine
from engine import profiles as prof
from engine.profiles import compute_fingerprint_hash

FIELDS = ["footage", "date", "pipe_id"]
FIELD_COLORS = {"footage": "#e74c3c", "date": "#2ecc71", "pipe_id": "#3498db"}
FIELD_LABELS = {"footage": "Footage Counter", "date": "Date", "pipe_id": "Pipe / Job ID"}

# Fingerprint region: top-left 300x120 of the frame (equipment branding tends to live here)
FINGERPRINT_REGION = [0, 0, 300, 120]


class CalibrateApp:
    def __init__(self, root: tk.Tk, initial_video: str | None = None):
        self.root = root
        self.root.title("Pipeline OCR — Calibration")
        self.root.resizable(True, True)

        self.ocr = None  # Lazy-init on first preview
        self.frame_path: Path | None = None
        self.orig_image: Image.Image | None = None
        self.tk_image: ImageTk.PhotoImage | None = None
        self.scale = 1.0

        # Crop state: field -> [x, y, w, h] in original image coords
        self.crops: dict[str, list | None] = {f: None for f in FIELDS}
        self.active_field = tk.StringVar(value="footage")

        # Drawing state
        self._drag_start: tuple | None = None
        self._rect_id = None
        self._rects: dict[str, int] = {}  # field -> canvas rect id

        self._build_ui()

        if initial_video:
            self.root.after(200, lambda: self._load_video(initial_video))

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        # Top toolbar
        toolbar = tk.Frame(self.root, bd=1, relief=tk.RAISED, pady=4)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        tk.Button(toolbar, text="Open Video", command=self._open_video, width=12).pack(side=tk.LEFT, padx=4)

        tk.Label(toolbar, text="Draw field:").pack(side=tk.LEFT, padx=(16, 4))
        for field in FIELDS:
            color = FIELD_COLORS[field]
            rb = tk.Radiobutton(
                toolbar,
                text=FIELD_LABELS[field],
                variable=self.active_field,
                value=field,
                fg=color,
                selectcolor="white",
                font=("TkDefaultFont", 10, "bold"),
            )
            rb.pack(side=tk.LEFT, padx=4)

        # Seek slider
        seek_frame = tk.Frame(self.root)
        seek_frame.pack(fill=tk.X, padx=8, pady=(4, 0))
        tk.Label(seek_frame, text="Seek:").pack(side=tk.LEFT)
        self.seek_var = tk.DoubleVar(value=10.0)
        self.seek_slider = tk.Scale(
            seek_frame, variable=self.seek_var, from_=0, to=300,
            orient=tk.HORIZONTAL, resolution=1, length=400,
            command=lambda _: self._on_seek(),
        )
        self.seek_slider.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.duration_label = tk.Label(seek_frame, text="")
        self.duration_label.pack(side=tk.LEFT, padx=4)

        # Main area: canvas + sidebar
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # Canvas
        canvas_frame = tk.Frame(main_frame, bd=2, relief=tk.SUNKEN)
        canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(canvas_frame, cursor="crosshair", bg="#1a1a1a")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # Sidebar
        sidebar = tk.Frame(main_frame, width=260, padx=8)
        sidebar.pack(side=tk.RIGHT, fill=tk.Y)
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="Crop Regions", font=("TkDefaultFont", 11, "bold")).pack(anchor=tk.W)

        self.crop_labels: dict[str, tk.Label] = {}
        for field in FIELDS:
            color = FIELD_COLORS[field]
            row = tk.Frame(sidebar)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=FIELD_LABELS[field], fg=color, font=("TkDefaultFont", 9, "bold"), width=16, anchor=tk.W).pack(side=tk.LEFT)
            lbl = tk.Label(row, text="not set", fg="#888", font=("TkFixedFont", 9))
            lbl.pack(side=tk.LEFT)
            self.crop_labels[field] = lbl
            tk.Button(row, text="Clear", command=lambda f=field: self._clear_crop(f), width=5).pack(side=tk.RIGHT)

        ttk.Separator(sidebar).pack(fill=tk.X, pady=8)

        # OCR Preview
        tk.Label(sidebar, text="OCR Preview", font=("TkDefaultFont", 11, "bold")).pack(anchor=tk.W)
        tk.Button(sidebar, text="Test OCR on crops", command=self._preview_ocr).pack(anchor=tk.W, pady=4)
        self.preview_text = tk.Text(sidebar, height=8, width=28, state=tk.DISABLED,
                                     font=("TkFixedFont", 9), bg="#f5f5f5", fg="black")
        self.preview_text.pack(fill=tk.X)

        ttk.Separator(sidebar).pack(fill=tk.X, pady=8)

        # Profile settings
        tk.Label(sidebar, text="Profile Settings", font=("TkDefaultFont", 11, "bold")).pack(anchor=tk.W)

        tk.Label(sidebar, text="Profile name:").pack(anchor=tk.W)
        self.name_var = tk.StringVar()
        tk.Entry(sidebar, textvariable=self.name_var, width=28).pack(anchor=tk.W)

        tk.Label(sidebar, text="Footage unit:").pack(anchor=tk.W, pady=(6, 0))
        self.unit_var = tk.StringVar(value="ft")
        unit_frame = tk.Frame(sidebar)
        unit_frame.pack(anchor=tk.W)
        tk.Radiobutton(unit_frame, text="ft", variable=self.unit_var, value="ft").pack(side=tk.LEFT)
        tk.Radiobutton(unit_frame, text="m", variable=self.unit_var, value="m").pack(side=tk.LEFT)

        tk.Label(sidebar, text="Max plausible value:").pack(anchor=tk.W, pady=(6, 0))
        self.max_var = tk.StringVar(value="5000")
        tk.Entry(sidebar, textvariable=self.max_var, width=10).pack(anchor=tk.W)

        tk.Label(sidebar, text="Sampling interval (sec):").pack(anchor=tk.W, pady=(6, 0))
        self.interval_var = tk.StringVar(value="5")
        tk.Entry(sidebar, textvariable=self.interval_var, width=10).pack(anchor=tk.W)

        ttk.Separator(sidebar).pack(fill=tk.X, pady=8)

        tk.Button(
            sidebar, text="Save Profile", command=self._save_profile,
            bg="#2ecc71", fg="white", font=("TkDefaultFont", 11, "bold"), height=2,
        ).pack(fill=tk.X)

        # Status bar
        self.status_var = tk.StringVar(value="Open a video to begin.")
        tk.Label(self.root, textvariable=self.status_var, anchor=tk.W, relief=tk.SUNKEN, pady=2).pack(
            side=tk.BOTTOM, fill=tk.X
        )

    # ------------------------------------------------------------------
    # Video Loading
    # ------------------------------------------------------------------

    def _open_video(self):
        path = filedialog.askopenfilename(
            title="Select a sample video",
            filetypes=[("Video files", "*.mp4 *.avi *.mov *.mpg *.mpeg *.wmv *.mkv *.mts *.m2ts"), ("All files", "*.*")],
        )
        if path:
            self._load_video(path)

    def _load_video(self, path: str):
        self.video_path = Path(path)
        duration = vid.get_duration(self.video_path)
        if not duration:
            messagebox.showerror("Error", f"Could not read video: {path}")
            return

        self.duration = duration
        self.seek_slider.config(to=max(int(duration) - 1, 1))
        self.duration_label.config(text=f"/ {int(duration)}s")
        self.seek_var.set(min(10.0, duration / 2))
        self.status_var.set(f"Loaded: {self.video_path.name}")
        self._extract_and_show(float(self.seek_var.get()))

    def _on_seek(self):
        if hasattr(self, "video_path"):
            self._extract_and_show(float(self.seek_var.get()))

    def _extract_and_show(self, timestamp: float):
        with tempfile.TemporaryDirectory() as tmpdir:
            frame_path = Path(tmpdir) / "calib_frame.jpg"
            if not vid.extract_frame(self.video_path, timestamp, frame_path):
                self.status_var.set("Failed to extract frame.")
                return
            # Keep a persistent copy for OCR
            persistent = Path(tempfile.mktemp(suffix=".jpg"))
            import shutil
            shutil.copy(frame_path, persistent)

        if self.frame_path and self.frame_path.exists():
            self.frame_path.unlink(missing_ok=True)
        self.frame_path = persistent
        self.orig_image = Image.open(self.frame_path)
        self._render_image()

    def _render_image(self):
        if not self.orig_image:
            return
        cw = self.canvas.winfo_width() or 800
        ch = self.canvas.winfo_height() or 500
        img_w, img_h = self.orig_image.size
        self.scale = min(cw / img_w, ch / img_h, 1.0)
        new_w = int(img_w * self.scale)
        new_h = int(img_h * self.scale)
        display = self.orig_image.resize((new_w, new_h), Image.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(display)
        self.canvas.delete("all")
        self._img_offset_x = (cw - new_w) // 2
        self._img_offset_y = (ch - new_h) // 2
        self.canvas.create_image(self._img_offset_x, self._img_offset_y, anchor=tk.NW, image=self.tk_image)
        self._redraw_rects()

    def _on_canvas_resize(self, _event):
        self._render_image()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _canvas_to_image(self, cx, cy):
        """Convert canvas coords to original image coords."""
        ix = (cx - self._img_offset_x) / self.scale
        iy = (cy - self._img_offset_y) / self.scale
        return ix, iy

    def _image_to_canvas(self, ix, iy):
        cx = ix * self.scale + self._img_offset_x
        cy = iy * self.scale + self._img_offset_y
        return cx, cy

    def _on_press(self, event):
        self._drag_start = (event.x, event.y)
        if self._rect_id:
            self.canvas.delete(self._rect_id)
            self._rect_id = None

    def _on_drag(self, event):
        if not self._drag_start:
            return
        x0, y0 = self._drag_start
        color = FIELD_COLORS[self.active_field.get()]
        if self._rect_id:
            self.canvas.delete(self._rect_id)
        self._rect_id = self.canvas.create_rectangle(
            x0, y0, event.x, event.y, outline=color, width=2, dash=(4, 2)
        )

    def _on_release(self, event):
        if not self._drag_start:
            return
        x0, y0 = self._drag_start
        x1, y1 = event.x, event.y
        self._drag_start = None

        if self._rect_id:
            self.canvas.delete(self._rect_id)
            self._rect_id = None

        # Convert to image coords
        ix0, iy0 = self._canvas_to_image(min(x0, x1), min(y0, y1))
        ix1, iy1 = self._canvas_to_image(max(x0, x1), max(y0, y1))
        w = ix1 - ix0
        h = iy1 - iy0

        if w < 5 or h < 5:
            return  # Ignore tiny accidental clicks

        field = self.active_field.get()
        self.crops[field] = [int(ix0), int(iy0), int(w), int(h)]
        self.crop_labels[field].config(
            text=f"({int(ix0)}, {int(iy0)}, {int(w)}, {int(h)})", fg="#333"
        )
        self._redraw_rects()

    def _redraw_rects(self):
        for field in FIELDS:
            if field in self._rects:
                self.canvas.delete(self._rects[field])
            crop = self.crops.get(field)
            if crop:
                x, y, w, h = crop
                cx0, cy0 = self._image_to_canvas(x, y)
                cx1, cy1 = self._image_to_canvas(x + w, y + h)
                color = FIELD_COLORS[field]
                rect_id = self.canvas.create_rectangle(cx0, cy0, cx1, cy1, outline=color, width=2)
                label_id = self.canvas.create_text(
                    cx0 + 4, cy0 + 4, anchor=tk.NW,
                    text=FIELD_LABELS[field], fill=color,
                    font=("TkDefaultFont", 9, "bold"),
                )
                self._rects[field] = rect_id

    def _clear_crop(self, field: str):
        self.crops[field] = None
        self.crop_labels[field].config(text="not set", fg="#888")
        self._redraw_rects()

    # ------------------------------------------------------------------
    # OCR Preview
    # ------------------------------------------------------------------

    def _preview_ocr(self):
        if not self.frame_path or not self.frame_path.exists():
            messagebox.showwarning("No frame", "Open a video first.")
            return

        self.status_var.set("Running OCR preview...")
        self.root.update()

        if self.ocr is None:
            self.ocr = ocr_engine.init_ocr(use_gpu=False)

        lines = []
        for field in FIELDS:
            crop = self.crops.get(field)
            texts = ocr_engine.run_ocr(self.ocr, self.frame_path, crop)
            lines.append(f"[{FIELD_LABELS[field]}]")
            if texts:
                for t in texts:
                    lines.append(f"  {t}")
            else:
                lines.append("  (nothing detected)")
            lines.append("")

        self.preview_text.config(state=tk.NORMAL)
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert(tk.END, "\n".join(lines))
        self.preview_text.config(state=tk.DISABLED)
        self.status_var.set("OCR preview complete.")

    # ------------------------------------------------------------------
    # Save Profile
    # ------------------------------------------------------------------

    def _save_profile(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing name", "Enter a profile name before saving.")
            return

        if not self.crops.get("footage"):
            messagebox.showwarning("Missing crop", "You must draw a crop box for the Footage Counter field.")
            return

        if not self.frame_path or not self.frame_path.exists():
            messagebox.showwarning("No frame", "Open a video first.")
            return

        try:
            max_val = float(self.max_var.get())
            interval = int(self.interval_var.get())
        except ValueError:
            messagebox.showerror("Invalid input", "Max plausible value and interval must be numbers.")
            return

        # Compute fingerprint hash
        fp_hash = compute_fingerprint_hash(self.frame_path, FINGERPRINT_REGION)

        profile = {
            "name": name,
            "unit": self.unit_var.get(),
            "interval": interval,
            "max_plausible_value": max_val,
            "fields": {
                field: ({"crop": self.crops[field]} if self.crops[field] else None)
                for field in FIELDS
            },
            "fingerprint": {
                "region": FINGERPRINT_REGION,
                "hash": fp_hash,
            },
        }

        saved_path = prof.save_profile(profile, name)
        messagebox.showinfo("Saved", f"Profile saved to:\n{saved_path}\n\nCommit this file to share it with your team.")
        self.status_var.set(f"Profile saved: {saved_path.name}")


def main():
    initial_video = sys.argv[1] if len(sys.argv) > 1 else None
    root = tk.Tk()
    root.geometry("1100x680")
    app = CalibrateApp(root, initial_video)
    root.mainloop()


if __name__ == "__main__":
    main()
