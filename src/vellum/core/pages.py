"""Blank page sizes, and the blank one-page PDF a new document starts from.

A size is held in inches, the one unit both paper and pixels convert through:
a paper size is physical and keeps its inches whatever the resolution, while a
screen size is a pixel count that only becomes inches once a resolution is
chosen.
"""

from __future__ import annotations

from dataclasses import dataclass

import fitz  # PyMuPDF

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0

# The largest page the viewer will hold as one pixmap. Beyond this the
# rendered page costs more memory than a desktop can comfortably give it, and
# some platforms refuse to paint a side longer than 32767 px at all.
MAX_SIDE_PX = 32_000
MAX_PIXELS = 200_000_000

DEFAULT_DPI = 150


@dataclass(frozen=True)
class PagePreset:
    name: str
    width: float          # in `unit`, portrait
    height: float
    unit: str             # "mm", "in" or "px"
    dpi: int | None = None  # screen presets carry their own resolution
    group: str = "Paper"


PRESETS: tuple[PagePreset, ...] = (
    PagePreset("A5", 148, 210, "mm"),
    PagePreset("A4", 210, 297, "mm"),
    PagePreset("A3", 297, 420, "mm"),
    PagePreset("A2", 420, 594, "mm"),
    PagePreset("A1", 594, 841, "mm"),
    PagePreset("A0", 841, 1189, "mm"),
    PagePreset("Letter", 8.5, 11, "in"),
    PagePreset("Legal", 8.5, 14, "in"),
    PagePreset("Tabloid", 11, 17, "in"),
    PagePreset("HD", 1280, 720, "px", dpi=72, group="Screen"),
    PagePreset("Full HD", 1920, 1080, "px", dpi=72, group="Screen"),
    PagePreset("4K UHD", 3840, 2160, "px", dpi=72, group="Screen"),
)

DEFAULT_PRESET = "A4"


def to_inches(value: float, unit: str, dpi: float) -> float:
    if unit == "mm":
        return value / MM_PER_INCH
    if unit == "px":
        return value / dpi
    return value


def from_inches(inches: float, unit: str, dpi: float) -> float:
    if unit == "mm":
        return inches * MM_PER_INCH
    if unit == "px":
        return inches * dpi
    return inches


def pixel_size(width_in: float, height_in: float, dpi: float) -> tuple[int, int]:
    return max(1, round(width_in * dpi)), max(1, round(height_in * dpi))


def size_problem(width_px: int, height_px: int) -> str | None:
    """Why a page of this many pixels cannot be created, or None if it can."""
    if max(width_px, height_px) > MAX_SIDE_PX:
        return (f"A side of {max(width_px, height_px):,} px is longer than the "
                f"{MAX_SIDE_PX:,} px the canvas can draw. Lower the resolution "
                f"or the page size.")
    if width_px * height_px > MAX_PIXELS:
        return (f"{width_px * height_px / 1e6:,.0f} megapixels is more than the "
                f"{MAX_PIXELS / 1e6:,.0f} the canvas can hold. Lower the "
                f"resolution or the page size.")
    return None


def blank_pdf(width_px: int, height_px: int, dpi: float) -> fitz.Document:
    """A one-page PDF that renders at `dpi` to exactly `width_px` x `height_px`.

    The page is sized in points so the physical size survives export: an A4
    page made here is an A4 page in Acrobat, whatever resolution it was
    drawn at.
    """
    k = PT_PER_INCH / dpi
    doc = fitz.open()
    doc.new_page(width=width_px * k, height=height_px * k)
    return doc


def ratio_text(width: float, height: float) -> str:
    """A page's aspect ratio in the form people say it: 16 : 9, 1 : 1.414."""
    from math import gcd

    w, h = round(width), round(height)
    if w > 0 and h > 0:
        d = gcd(w, h)
        if w // d <= 32 and h // d <= 32 and abs(width - w) < 1e-6 and abs(height - h) < 1e-6:
            return f"{w // d} : {h // d}"
    short, long_ = sorted((width, height))
    if short <= 0:
        return "—"
    if width <= height:
        return f"1 : {long_ / short:.3f}"
    return f"{long_ / short:.3f} : 1"
