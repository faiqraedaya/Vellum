"""
Unified PySide6 theme - single authority for every colour, metric, and stylesheet.

Usage:
    from .theme import apply_theme, Tokens, restyle

    # In main():
    apply_theme(app)                        # once, after QApplication is created

    # Mark a widget variant:
    button.setProperty("variant", "primary")
    restyle(button)

    # Access tokens directly:
    Tokens.ink(0.64)                        # secondary text colour string
    Tokens.RADIUS                           # border radius in px

Run standalone to print the contrast ladder and verify WCAG ratios:
    python -m vellum.gui.theme
"""

from __future__ import annotations

import logging
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

# Inter ships with the app rather than being assumed present on the host,
# so every machine renders the same type scale. A PyInstaller bundle
# unpacks the faces beside this module, so the frozen root is checked too.
def _fonts_dir() -> Path:
    beside_module = Path(__file__).parent / "fonts"
    if beside_module.is_dir():
        return beside_module
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "vellum" / "gui" / "fonts"
    return beside_module


FONTS_DIR = _fonts_dir()


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Tokens:
    """All visual constants. Override by subclassing, not patching."""

    # -- Canvas & ink -------------------------------------------------------
    CANVAS: str = "#FFFFFF"
    INK: str = "#000000"

    # -- Ink ladder (alpha on canvas) ---------------------------------------
    # fmt: off
    INK_PRIMARY:   float = 1.00   # values, headings, active labels
    INK_SECONDARY: float = 0.64   # supporting text, inactive tabs
    INK_TERTIARY:  float = 0.56   # units, captions, metadata, placeholder text
    INK_GLYPH:     float = 0.44   # icons, dividers - never text
    INK_DISABLED:  float = 0.38   # inactive controls only
    # fmt: on

    # -- Surface alphas (ink over canvas) -----------------------------------
    SURFACE_BORDER: float = 0.10
    SURFACE_BORDER_STRONG: float = 0.18
    SURFACE_WASH: float = 0.03
    SURFACE_HOVER: float = 0.05
    SURFACE_PRESSED: float = 0.09
    SURFACE_SELECTED: float = 0.09

    # -- Semantic colours ---------------------------------------------------
    ACTION: str = "#2563EB"       # blue - primary action, checked toggles
    ACTION_HOVER: str = "#1D4ED8"
    ACTION_PRESSED: str = "#1E40AF"
    ACTION_TEXT: str = "#FFFFFF"

    SUCCESS: str = "#16A34A"      # green - success states
    SUCCESS_BG: str = "#F0FDF4"
    WARNING: str = "#D97706"      # orange - warning states
    WARNING_BG: str = "#FFFBEB"
    ERROR: str = "#DC2626"        # red - failure states
    ERROR_BG: str = "#FEF2F2"
    ERROR_PRESSED: str = "#B91C1C"

    # -- Typography ---------------------------------------------------------
    FONT_FAMILY: str = "Inter"
    FONT_FALLBACK: str = ""       # resolved at apply_theme time

    # Sizes in px - Qt scales with DPI
    FONT_TITLE: int = 22
    FONT_HEADING: int = 16
    FONT_BODY: int = 14
    FONT_LABEL: int = 13
    FONT_CAPTION: int = 12

    WEIGHT_REGULAR: int = 400
    WEIGHT_MEDIUM: int = 500
    WEIGHT_SEMIBOLD: int = 600

    # -- Geometry (8px grid) ------------------------------------------------
    MARGIN_WINDOW: int = 20
    MARGIN_GROUP: int = 16
    SPACING_ROW: int = 8
    SPACING_GROUP: int = 20
    SPACING_SECTION: int = 32

    CONTROL_HEIGHT: int = 32
    CONTROL_COMPACT: int = 26
    RADIUS: int = 6
    RADIUS_PANEL: int = 8
    ICON_SIZE: int = 16

    MIN_WINDOW_W: int = 480
    MIN_WINDOW_H: int = 360
    MIN_DIALOG_W: int = 360

    # Minimum width for a value-entry control, so long numbers never clip
    FIELD_MIN_W: int = 128

    # -- Splitter -----------------------------------------------------------
    SPLITTER_VISUAL: int = 1      # visible line width
    SPLITTER_GRAB: int = 8        # total grab area (transparent padding)

    # -- Motion -------------------------------------------------------------
    DURATION_MS: int = 150
    animate: ClassVar[bool] = True

    # -- Data series --------------------------------------------------------
    # Categorical slots in FIXED order - never cycled, never reordered. Slots
    # 1-3 are the prefix validated for all-pairs use on a light surface; a
    # chart needing a fourth identity folds into "Other" or becomes small
    # multiples rather than inventing a hue.
    SERIES: tuple = ("#2A78D6", "#EB6834", "#1BAF7A")

    # Sequential blue ramp for ORDERED magnitude (e.g. a fan of isobars).
    # Starts at step 250 - the lightest step that still clears 2:1 on white.
    SERIES_SEQUENTIAL: tuple = ("#86B6EF", "#5598E7", "#2A78D6", "#1C5CAB", "#104281")

    # -- Document canvas ----------------------------------------------------
    # The viewer draws a user's image or PDF page onto a mat (see mat()). The
    # mat is a surface, so it comes off the ink ladder; the page itself is
    # whatever the user opened and is never tinted.
    # -- Annotation marks ---------------------------------------------------
    # Measurement marks are encoded values drawn on top of an arbitrary
    # document, so they keep their colour (rule 4) and are NOT the categorical
    # SERIES palette: that palette is validated for a white surface, while
    # these sit on whatever the user opened. Every mark carries its own drawn
    # label, so colour is never the sole carrier of identity. Each entry is a
    # 700-weight hue that clears 4.5:1 on white so it survives a light
    # technical drawing.
    MARK_POINT: str = "#047857"        # emerald
    MARK_DISTANCE: str = "#B45309"     # amber
    MARK_ANGLE: str = "#7E22CE"        # purple
    MARK_POLYGON: str = "#BE185D"      # pink
    MARK_POLYLINE: str = "#0E7490"     # cyan
    MARK_ELLIPSE: str = "#4D7C0F"      # lime
    MARK_TEXTBOX: str = "#1F2937"      # near-ink, for type
    # A filled note on a drawing: pale enough that dark type still reads on it.
    MARK_TEXTBOX_FILL: str = "#FFFBEB"
    MARK_CONTOUR: str = "#57534E"      # neutral: levels carry their own colour

    # The origin fiducial. Red by convention on a measurement canvas, and
    # deliberately not ERROR: nothing has gone wrong, it marks the datum.
    MARK_ORIGIN: str = "#DC2626"
    # In-progress geometry and the current selection. ACTION means "active",
    # and no default mark colour uses it, so a selected object is unambiguous.
    MARK_SELECTED: str = ACTION
    MARK_PREVIEW: str = ACTION
    # Construction geometry: skeletons, bounding boxes, guides. Dark neutral
    # rather than an ink alpha - it is drawn over the document, not the canvas.
    MARK_GUIDE: str = "#57534E"
    # A snap target is a valid state, so it takes the semantic success colour.
    MARK_SNAP: str = SUCCESS

    # Risk-contour levels are ordered by severity, not identity, so they take
    # one ordered ramp rather than a cycled categorical palette. Row 0 is the
    # most severe.
    CONTOUR_RAMP: tuple = ("#7F1D1D", "#B91C1C", "#DC2626", "#C2410C",
                           "#B45309", "#A16207")

    # -- Helpers ------------------------------------------------------------
    def ink(self, alpha: float) -> str:
        """Return rgba() string for ink at given alpha."""
        c = QColor(self.INK)
        return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"

    def surface(self, alpha: float) -> str:
        """Return rgba() string for a surface (ink over canvas)."""
        return self.ink(alpha)

    def ink_hex(self, alpha: float) -> str:
        """Return an ink ladder rung flattened to an opaque hex colour.

        For libraries that cannot read rgba() - matplotlib, pyqtgraph.
        """
        return _alpha_blend(self.INK, self.CANVAS, alpha)

    def series(self, index: int) -> str:
        """Return the categorical series colour for a fixed slot index."""
        if not 0 <= index < len(self.SERIES):
            raise IndexError(
                f"Series slot {index} is out of range. The palette has "
                f"{len(self.SERIES)} validated slots; fold further series "
                f"into 'Other' or use small multiples rather than "
                f"inventing a hue."
            )
        return self.SERIES[index]

    def sequential_ink(self, index: int, count: int) -> str:
        """An ordered ramp in neutral ink, for reference contours.

        Contour lines you read a value off - a fan of isobars - are ordered
        chart chrome, not identities. Giving them a hue would collide with
        the categorical series sharing the axes.
        """
        lo, hi = self.INK_GLYPH * 0.6, self.INK_SECONDARY
        if count <= 1:
            return self.ink_hex((lo + hi) / 2)
        return self.ink_hex(lo + (hi - lo) * index / (count - 1))

    def contour(self, index: int) -> str:
        """Default colour for contour level `index`, most severe first.

        Clamps at the last step instead of wrapping: past the ramp the levels
        stop being visually ordered, and a repeated hue would read as a
        repeated severity. The user can override any level, and every level is
        named in the on-canvas legend.
        """
        ramp = self.CONTOUR_RAMP
        return ramp[min(max(index, 0), len(ramp) - 1)]

    def mat(self) -> str:
        """Opaque colour of the mat the document page sits on."""
        return self.ink_hex(self.SURFACE_PRESSED)

    def sequential(self, index: int, count: int) -> str:
        """Return a step of the sequential ramp for item `index` of `count`."""
        ramp = self.SERIES_SEQUENTIAL
        if count <= 1:
            return ramp[len(ramp) // 2]
        pos = round(index * (len(ramp) - 1) / (count - 1))
        return ramp[pos]

    @staticmethod
    def pt(px: float, dpi: int = 100) -> float:
        """Convert a px type-scale token to matplotlib points at `dpi`.

        Qt sizes text in px; matplotlib sizes it in points. Without this the
        same token renders ~39 % larger inside a figure than beside it.
        """
        return px * 72.0 / dpi

    def font_css(self) -> str:
        parts = [f'"{self.FONT_FAMILY}"']
        if self.FONT_FALLBACK and self.FONT_FALLBACK != self.FONT_FAMILY:
            parts.append(f'"{self.FONT_FALLBACK}"')
        parts.append("sans-serif")
        return ", ".join(parts)


Tokens = _Tokens()


# ---------------------------------------------------------------------------
# Contrast verification
# ---------------------------------------------------------------------------

def _relative_luminance(hex_colour: str) -> float:
    """WCAG 2.x relative luminance from sRGB hex."""
    c = QColor(hex_colour)
    channels = []
    for v in (c.redF(), c.greenF(), c.blueF()):
        channels.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(l1: float, l2: float) -> float:
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _alpha_blend(fg_hex: str, bg_hex: str, alpha: float) -> str:
    fg, bg = QColor(fg_hex), QColor(bg_hex)
    r = int(fg.red() * alpha + bg.red() * (1 - alpha))
    g = int(fg.green() * alpha + bg.green() * (1 - alpha))
    b = int(fg.blue() * alpha + bg.blue() * (1 - alpha))
    return f"#{r:02X}{g:02X}{b:02X}"


def check_ladder() -> list:
    """Print and return contrast ratios for the ink ladder."""
    canvas_lum = _relative_luminance(Tokens.CANVAS)
    rungs = [
        ("Primary",   Tokens.INK_PRIMARY),
        ("Secondary", Tokens.INK_SECONDARY),
        ("Tertiary",  Tokens.INK_TERTIARY),
        ("Glyph",     Tokens.INK_GLYPH),
        ("Disabled",  Tokens.INK_DISABLED),
    ]
    results = []
    for name, alpha in rungs:
        blended = _alpha_blend(Tokens.INK, Tokens.CANVAS, alpha)
        lum = _relative_luminance(blended)
        ratio = _contrast_ratio(lum, canvas_lum)
        results.append({"name": name, "alpha": alpha, "hex": blended, "ratio": ratio})
        print(f"  {name:12s}  a={alpha:.2f}  {blended}  {ratio:.1f}:1")
    return results


# ---------------------------------------------------------------------------
# QSS builder
# ---------------------------------------------------------------------------

# Size of the chevron in a combo box or spin box: smaller than a full icon,
# because it labels the control rather than standing on its own.
ARROW_SIZE = 10


def _arrow_qss(arrows: dict) -> str:
    """Stylesheet rules for the rendered arrows, or nothing if they are missing."""
    if not arrows:
        return ""
    return f"""
QComboBox::down-arrow, QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({arrows['down']});
    width: {ARROW_SIZE}px;
    height: {ARROW_SIZE}px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({arrows['up']});
    width: {ARROW_SIZE}px;
    height: {ARROW_SIZE}px;
}}
QComboBox::down-arrow:disabled, QSpinBox::down-arrow:disabled,
QDoubleSpinBox::down-arrow:disabled {{
    image: url({arrows['down_disabled']});
}}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled {{
    image: url({arrows['up_disabled']});
}}
"""


def _arrow_assets() -> dict:
    """Render the dropdown and stepper chevrons to files the QSS can point at.

    Qt paints a bordered box rather than a CSS triangle for these sub-controls,
    and a widget carrying a stylesheet no longer gets the style's own arrow -
    so they are drawn from the one icon family instead of being invented here.
    QSS can only reference an image by URL, hence the temporary files; they are
    generated from the ink ladder, never shipped as coloured assets.
    """
    from . import icons          # imported here: icons imports this module

    directory = Path(tempfile.gettempdir()) / "vellum-theme"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("No cache directory for the arrow glyphs: %s", directory)
        return {}

    assets = {}
    rungs = {"": Tokens.INK_GLYPH, "_disabled": Tokens.INK_DISABLED}
    for direction, glyph in (("down", "chevron-down"), ("up", "chevron-up")):
        for suffix, alpha in rungs.items():
            key = f"{direction}{suffix}"
            path = directory / f"arrow_{key}.png"
            image = icons.pixmap(glyph, Tokens.ink_hex(alpha), size=ARROW_SIZE)
            if not image.save(str(path), "PNG"):
                logger.warning("Could not write the arrow glyph: %s", path)
                return {}
            assets[key] = path.as_posix()
    return assets


def _build_qss() -> str:
    T = Tokens
    f = T.font_css()

    arrows = _arrow_assets()
    grab_pad = (T.SPLITTER_GRAB - T.SPLITTER_VISUAL) // 2

    return f"""
/* -- Global ------------------------------------------------ */
* {{
    font-family: {f};
    font-size: {T.FONT_BODY}px;
    font-weight: {T.WEIGHT_REGULAR};
    color: {T.ink(T.INK_PRIMARY)};
    outline: none;
}}

/* -- Window ------------------------------------------------ */
QMainWindow, QDialog, QWidget#centralWidget {{
    background: {T.CANVAS};
}}

/* -- Labels ------------------------------------------------ */
QLabel {{
    background: transparent;
    padding: 0px;
    border: none;
}}
QLabel[role="title"] {{
    font-size: {T.FONT_TITLE}px;
    font-weight: {T.WEIGHT_SEMIBOLD};
}}
QLabel[role="heading"] {{
    font-size: {T.FONT_HEADING}px;
    font-weight: {T.WEIGHT_SEMIBOLD};
}}
QLabel[role="brand"] {{
    font-size: {T.FONT_HEADING}px;
    font-weight: {T.WEIGHT_SEMIBOLD};
    color: {T.ink(T.INK_PRIMARY)};
}}
QLabel[role="caption"] {{
    font-size: {T.FONT_CAPTION}px;
    font-weight: {T.WEIGHT_MEDIUM};
    color: {T.ink(T.INK_TERTIARY)};
}}
QLabel[role="unit"] {{
    font-size: {T.FONT_CAPTION}px;
    font-weight: {T.WEIGHT_MEDIUM};
    color: {T.ink(T.INK_TERTIARY)};
}}
/* Status roles - always paired with words, never colour alone */
QLabel[role="error"] {{
    font-size: {T.FONT_CAPTION}px;
    font-weight: {T.WEIGHT_MEDIUM};
    color: {T.ERROR};
    background: {T.ERROR_BG};
    border-radius: {T.RADIUS}px;
    padding: 6px 10px;
}}
QLabel[role="success"] {{
    font-size: {T.FONT_CAPTION}px;
    font-weight: {T.WEIGHT_MEDIUM};
    color: {T.SUCCESS};
    background: {T.SUCCESS_BG};
    border-radius: {T.RADIUS}px;
    padding: 6px 10px;
}}
QLabel[role="warning"] {{
    font-size: {T.FONT_CAPTION}px;
    font-weight: {T.WEIGHT_MEDIUM};
    color: {T.WARNING};
    background: {T.WARNING_BG};
    border-radius: {T.RADIUS}px;
    padding: 6px 10px;
}}

/* -- Inputs ------------------------------------------------ */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {T.CANVAS};
    border: 1px solid {T.ink(T.SURFACE_BORDER)};
    border-radius: {T.RADIUS}px;
    padding: 6px 10px;
    min-height: {T.CONTROL_HEIGHT - 14}px;
    font-size: {T.FONT_BODY}px;
    color: {T.ink(T.INK_PRIMARY)};
    selection-background-color: {T.ink(T.SURFACE_SELECTED)};
}}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover,
QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
    border-color: {T.ink(T.SURFACE_BORDER_STRONG)};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 2px solid {T.ink(T.INK_GLYPH)};
    padding: 5px 9px;
}}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background: {T.ink(T.SURFACE_WASH)};
    color: {T.ink(T.INK_DISABLED)};
    border-color: {T.ink(T.SURFACE_BORDER)};
}}
/* Read-only output field: reads as a value, not as somewhere to type */
QDoubleSpinBox[readOnlyValue="true"], QLineEdit[readOnlyValue="true"],
QTextEdit[readOnlyValue="true"] {{
    background: {T.ink(T.SURFACE_WASH)};
}}

/* -- Buttons ----------------------------------------------- */
QPushButton {{
    background: {T.CANVAS};
    border: 1px solid {T.ink(T.SURFACE_BORDER)};
    border-radius: {T.RADIUS}px;
    padding: 6px 16px;
    min-height: {T.CONTROL_HEIGHT - 14}px;
    font-size: {T.FONT_LABEL}px;
    font-weight: {T.WEIGHT_MEDIUM};
    color: {T.ink(T.INK_PRIMARY)};
}}
QPushButton:hover {{
    background: {T.ink(T.SURFACE_HOVER)};
    border-color: {T.ink(T.SURFACE_BORDER_STRONG)};
}}
QPushButton:pressed {{
    background: {T.ink(T.SURFACE_PRESSED)};
}}
QPushButton:focus {{
    border: 2px solid {T.ink(T.INK_GLYPH)};
    padding: 5px 15px;
}}
QPushButton:disabled {{
    color: {T.ink(T.INK_DISABLED)};
    border-color: {T.ink(T.SURFACE_BORDER)};
    background: {T.ink(T.SURFACE_WASH)};
}}

/* Primary action button */
QPushButton[variant="primary"] {{
    background: {T.ACTION};
    border: 1px solid {T.ACTION};
    color: {T.ACTION_TEXT};
}}
QPushButton[variant="primary"]:hover {{
    background: {T.ACTION_HOVER};
    border-color: {T.ACTION_HOVER};
}}
QPushButton[variant="primary"]:pressed {{
    background: {T.ACTION_PRESSED};
    border-color: {T.ACTION_PRESSED};
}}
QPushButton[variant="primary"]:focus {{
    border: 2px solid {T.ACTION_PRESSED};
    padding: 5px 15px;
}}
QPushButton[variant="primary"]:disabled {{
    background: {T.ink(T.SURFACE_BORDER)};
    border-color: {T.ink(T.SURFACE_BORDER)};
    color: {T.ink(T.INK_DISABLED)};
}}

/* Quiet / tertiary button */
QPushButton[variant="quiet"] {{
    background: transparent;
    border: none;
    color: {T.ink(T.INK_SECONDARY)};
}}
QPushButton[variant="quiet"]:hover {{
    background: {T.ink(T.SURFACE_HOVER)};
    color: {T.ink(T.INK_PRIMARY)};
}}
QPushButton[variant="quiet"]:pressed {{
    background: {T.ink(T.SURFACE_PRESSED)};
}}
QPushButton[variant="quiet"]:focus {{
    border: 2px solid {T.ink(T.INK_GLYPH)};
    padding: 4px 14px;
}}
QPushButton[variant="quiet"]:disabled {{
    background: transparent;
    color: {T.ink(T.INK_DISABLED)};
}}

/* Danger button */
QPushButton[variant="danger"] {{
    background: {T.CANVAS};
    border: 1px solid {T.ERROR};
    color: {T.ERROR};
}}
QPushButton[variant="danger"]:hover {{
    background: {T.ERROR};
    color: {T.ACTION_TEXT};
}}
QPushButton[variant="danger"]:pressed {{
    background: {T.ERROR_PRESSED};
    border-color: {T.ERROR_PRESSED};
    color: {T.ACTION_TEXT};
}}
QPushButton[variant="danger"]:focus {{
    border: 2px solid {T.ERROR_PRESSED};
    padding: 5px 15px;
}}
/* A disabled destructive action still has to read as destructive: without
   its own rule the danger colours above win over the plain disabled rule and
   the button looks live. It keeps a muted red so it never looks like the
   neutral buttons beside it. */
QPushButton[variant="danger"]:disabled {{
    background: {T.ink(T.SURFACE_WASH)};
    border-color: {_alpha_blend(T.ERROR, T.CANVAS, 0.30)};
    color: {_alpha_blend(T.ERROR, T.CANVAS, 0.45)};
}}

/* -- ComboBox dropdown ------------------------------------- */
QComboBox::drop-down {{
    border: none;
    width: {T.ICON_SIZE + 8}px;
}}
{_arrow_qss(arrows)}
QComboBox QAbstractItemView {{
    background: {T.CANVAS};
    border: 1px solid {T.ink(T.SURFACE_BORDER_STRONG)};
    border-radius: {T.RADIUS}px;
    padding: 4px;
    selection-background-color: {T.ink(T.SURFACE_SELECTED)};
    outline: none;
}}

/* -- SpinBox arrows ---------------------------------------- */
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: transparent;
    border: none;
    width: 20px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {T.ink(T.SURFACE_HOVER)};
}}
/* -- Checkbox & Radio -------------------------------------- */
QCheckBox, QRadioButton {{
    spacing: 8px;
    font-size: {T.FONT_BODY}px;
    color: {T.ink(T.INK_PRIMARY)};
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: {T.ICON_SIZE}px;
    height: {T.ICON_SIZE}px;
    border: 1px solid {T.ink(T.SURFACE_BORDER_STRONG)};
    background: {T.CANVAS};
}}
QCheckBox::indicator {{
    border-radius: 3px;
}}
QRadioButton::indicator {{
    border-radius: {T.ICON_SIZE // 2}px;
}}
QCheckBox::indicator:checked {{
    background: {T.ACTION};
    border-color: {T.ACTION};
}}
QRadioButton::indicator:checked {{
    background: {T.ACTION};
    border-color: {T.ACTION};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {T.ink(T.INK_GLYPH)};
}}
QCheckBox::indicator:focus, QRadioButton::indicator:focus {{
    border: 2px solid {T.ink(T.INK_GLYPH)};
}}
QCheckBox:disabled, QRadioButton:disabled {{
    color: {T.ink(T.INK_DISABLED)};
}}

/* -- GroupBox ---------------------------------------------- */
QGroupBox {{
    font-size: {T.FONT_LABEL}px;
    font-weight: {T.WEIGHT_SEMIBOLD};
    color: {T.ink(T.INK_PRIMARY)};
    border: 1px solid {T.ink(T.SURFACE_BORDER)};
    border-radius: {T.RADIUS_PANEL}px;
    margin-top: 12px;
    padding: {T.MARGIN_GROUP}px;
    padding-top: 28px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: {T.MARGIN_GROUP}px;
    padding: 0 6px;
    background: {T.CANVAS};
}}

/* -- TabWidget --------------------------------------------- */
QTabWidget::pane {{
    border: 1px solid {T.ink(T.SURFACE_BORDER)};
    border-radius: {T.RADIUS_PANEL}px;
    background: {T.CANVAS};
    padding: {T.MARGIN_GROUP}px;
}}
/* Nested tabs: the outer pane already draws the boundary, so a second
   outline around the same content would be a double border. */
QTabWidget[variant="inner"]::pane {{
    border: none;
    border-top: 1px solid {T.ink(T.SURFACE_BORDER)};
    border-radius: 0px;
    padding: {T.SPACING_ROW}px 0px 0px 0px;
}}
QTabBar::tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 16px;
    font-size: {T.FONT_LABEL}px;
    font-weight: {T.WEIGHT_MEDIUM};
    color: {T.ink(T.INK_SECONDARY)};
}}
QTabBar::tab:selected {{
    color: {T.ink(T.INK_PRIMARY)};
    border-bottom-color: {T.ink(T.INK_PRIMARY)};
}}
QTabBar::tab:hover:!selected {{
    color: {T.ink(T.INK_PRIMARY)};
    background: {T.ink(T.SURFACE_HOVER)};
}}
QTabBar::tab:focus {{
    border-bottom: 2px solid {T.ink(T.INK_GLYPH)};
    color: {T.ink(T.INK_PRIMARY)};
}}

/* -- Table ------------------------------------------------- */
QTableView, QTreeView, QListView {{
    background: {T.CANVAS};
    border: 1px solid {T.ink(T.SURFACE_BORDER)};
    border-radius: {T.RADIUS}px;
    gridline-color: transparent;
    alternate-background-color: {T.ink(T.SURFACE_WASH)};
    selection-background-color: {T.ink(T.SURFACE_SELECTED)};
    selection-color: {T.ink(T.INK_PRIMARY)};
    font-size: {T.FONT_BODY}px;
    outline: none;
}}
QTableView::item, QTreeView::item, QListView::item {{
    padding: 6px 10px;
    border: none;
}}
/* Selection has to hold when the view is not the focused widget - the row
   stays marked while the user is working on the drawing beside it. Stated as
   a rule rather than left to selection-background-color, which Qt drops for
   the inactive palette group. */
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{
    background: {T.ink(T.SURFACE_SELECTED)};
    color: {T.ink(T.INK_PRIMARY)};
}}
QTableView:focus, QTreeView:focus, QListView:focus {{
    border: 2px solid {T.ink(T.INK_GLYPH)};
}}
QHeaderView::section {{
    background: {T.ink(T.SURFACE_WASH)};
    border: none;
    border-bottom: 1px solid {T.ink(T.SURFACE_BORDER)};
    padding: 6px 10px;
    font-size: {T.FONT_CAPTION}px;
    font-weight: {T.WEIGHT_SEMIBOLD};
    color: {T.ink(T.INK_SECONDARY)};
}}
QTableCornerButton::section {{
    background: {T.ink(T.SURFACE_WASH)};
    border: none;
    border-bottom: 1px solid {T.ink(T.SURFACE_BORDER)};
}}

/* -- Scrollbar --------------------------------------------- */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {T.ink(T.INK_GLYPH)};
    border-radius: 4px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{
    background: {T.ink(T.INK_TERTIARY)};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    height: 0px;
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {T.ink(T.INK_GLYPH)};
    border-radius: 4px;
    min-width: 32px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {T.ink(T.INK_TERTIARY)};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    width: 0px;
    background: transparent;
}}

/* -- ToolTip ----------------------------------------------- */
QToolTip {{
    background: {T.ink(0.92)};
    color: {T.CANVAS};
    border: none;
    border-radius: {T.RADIUS}px;
    padding: 6px 10px;
    font-size: {T.FONT_CAPTION}px;
}}

/* -- StatusBar --------------------------------------------- */
QStatusBar {{
    background: {T.CANVAS};
    border-top: 1px solid {T.ink(T.SURFACE_BORDER)};
    font-size: {T.FONT_CAPTION}px;
    color: {T.ink(T.INK_TERTIARY)};
    padding: 4px {T.MARGIN_WINDOW}px;
}}
QStatusBar::item {{
    border: none;
}}
QStatusBar QLabel {{
    font-size: {T.FONT_CAPTION}px;
    color: {T.ink(T.INK_TERTIARY)};
}}
/* The live measurement readout is a value, not chrome, so it takes primary
   ink while the rest of the bar stays tertiary. */
QStatusBar QLabel[role="value"] {{
    color: {T.ink(T.INK_PRIMARY)};
    font-weight: {T.WEIGHT_MEDIUM};
}}
QStatusBar QProgressBar {{
    max-width: 120px;
}}

/* -- ProgressBar ------------------------------------------- */
QProgressBar {{
    background: {T.ink(T.SURFACE_WASH)};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    font-size: 0px;
}}
QProgressBar::chunk {{
    background: {T.ACTION};
    border-radius: 3px;
}}

/* -- Slider ------------------------------------------------ */
QSlider::groove:horizontal {{
    background: {T.ink(T.SURFACE_BORDER)};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {T.ink(T.INK_PRIMARY)};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{
    background: {T.ACTION};
}}

/* -- Splitter ---------------------------------------------- */
QSplitter::handle {{
    background: {T.ink(T.SURFACE_BORDER)};
}}
QSplitter::handle:hover {{
    background: {T.ink(T.SURFACE_BORDER_STRONG)};
}}
QSplitter::handle:horizontal {{
    width: {T.SPLITTER_VISUAL}px;
    margin: 0 {grab_pad}px;
}}
QSplitter::handle:vertical {{
    height: {T.SPLITTER_VISUAL}px;
    margin: {grab_pad}px 0;
}}

/* -- Menu -------------------------------------------------- */
QMenuBar {{
    background: {T.CANVAS};
    border-bottom: 1px solid {T.ink(T.SURFACE_BORDER)};
    padding: 2px 8px;
    font-size: {T.FONT_LABEL}px;
}}
QMenuBar::item {{
    padding: 6px 10px;
    border-radius: {T.RADIUS}px;
    color: {T.ink(T.INK_PRIMARY)};
}}
QMenuBar::item:selected {{
    background: {T.ink(T.SURFACE_HOVER)};
}}
QMenu {{
    background: {T.CANVAS};
    border: 1px solid {T.ink(T.SURFACE_BORDER_STRONG)};
    border-radius: {T.RADIUS_PANEL}px;
    padding: 4px;
    font-size: {T.FONT_LABEL}px;
}}
QMenu::item {{
    padding: 6px 28px 6px 12px;
    border-radius: {T.RADIUS - 2}px;
    color: {T.ink(T.INK_PRIMARY)};
}}
QMenu::item:selected {{
    background: {T.ink(T.SURFACE_HOVER)};
}}
QMenu::item:disabled {{
    color: {T.ink(T.INK_DISABLED)};
}}
QMenu::separator {{
    height: 1px;
    background: {T.ink(T.SURFACE_BORDER)};
    margin: 4px 8px;
}}

/* -- Toolbar ----------------------------------------------- */
QToolBar {{
    background: {T.CANVAS};
    border-bottom: 1px solid {T.ink(T.SURFACE_BORDER)};
    spacing: 4px;
    padding: 4px 8px;
}}
QToolButton {{
    background: transparent;
    border: none;
    border-radius: {T.RADIUS}px;
    padding: 6px;
    color: {T.ink(T.INK_SECONDARY)};
}}
QToolButton:hover {{
    background: {T.ink(T.SURFACE_HOVER)};
    color: {T.ink(T.INK_PRIMARY)};
}}
QToolButton:pressed {{
    background: {T.ink(T.SURFACE_PRESSED)};
}}
QToolButton:checked {{
    background: {T.ink(T.SURFACE_SELECTED)};
    color: {T.ink(T.INK_PRIMARY)};
}}
QToolButton:disabled {{
    color: {T.ink(T.INK_DISABLED)};
}}
QToolButton:focus {{
    border: 2px solid {T.ink(T.INK_GLYPH)};
    padding: 4px;
}}
/* Home-page card: one way to start, as an outlined tile. The outline is
   what makes the three read as equal choices rather than a toolbar. */
QToolButton[variant="card"] {{
    background: {T.CANVAS};
    border: 1px solid {T.ink(T.SURFACE_BORDER)};
    border-radius: {T.RADIUS_PANEL}px;
    padding: {T.MARGIN_GROUP}px;
    font-size: {T.FONT_LABEL}px;
    font-weight: {T.WEIGHT_MEDIUM};
    color: {T.ink(T.INK_PRIMARY)};
}}
QToolButton[variant="card"]:hover {{
    background: {T.ink(T.SURFACE_HOVER)};
    border-color: {T.ink(T.SURFACE_BORDER_STRONG)};
}}
QToolButton[variant="card"]:pressed {{
    background: {T.ink(T.SURFACE_PRESSED)};
}}
QToolButton[variant="card"]:focus {{
    border: 2px solid {T.ink(T.INK_GLYPH)};
    padding: {T.MARGIN_GROUP - 1}px;
}}
/* Toolbar groups are separated by a rule, not by a gap alone: the tool
   palette is long enough that the eye needs the break to find a group. */
QToolBar::separator {{
    background: {T.ink(T.SURFACE_BORDER)};
    width: 1px;
    margin: 6px {T.SPACING_ROW}px;
}}
QToolBar QLabel {{
    font-size: {T.FONT_CAPTION}px;
    font-weight: {T.WEIGHT_MEDIUM};
    color: {T.ink(T.INK_SECONDARY)};
    padding: 0 {T.SPACING_ROW}px;
}}

/* -- Divider ----------------------------------------------- */
/* Between unrelated status-bar segments only - never across a value and
   its unit, or a label and its field. */
QFrame[role="vsep"] {{
    background: {T.ink(T.SURFACE_BORDER)};
    border: none;
    max-width: 1px;
    min-width: 1px;
}}

/* -- Document tab bar -------------------------------------- */
/* The open documents, sitting directly on top of the viewer canvas. */
QTabBar#documentTabs {{
    background: {T.CANVAS};
    border-bottom: 1px solid {T.ink(T.SURFACE_BORDER)};
}}
QTabBar#documentTabs::tab {{
    max-width: 240px;
}}
QTabBar::close-button {{
    subcontrol-position: right;
    margin-left: {T.SPACING_ROW}px;
}}

/* -- DialogButtonBox --------------------------------------- */
QDialogButtonBox {{
    dialogbuttonbox-buttons-have-icons: 0;
}}

/* -- Sidebar ----------------------------------------------- */
QWidget#sidebar {{
    background: {T.ink(T.SURFACE_WASH)};
    border: none;
}}
/* Navigation item: the destination list, not a row of buttons. Left
   aligned so the labels form a readable column, and the checked state
   carries weight and ink as well as a fill - never fill alone. */
QPushButton[variant="nav"] {{
    background: transparent;
    border: none;
    border-radius: {T.RADIUS}px;
    padding: 6px 10px;
    min-height: {T.CONTROL_HEIGHT - 12}px;
    text-align: left;
    font-size: {T.FONT_LABEL}px;
    font-weight: {T.WEIGHT_MEDIUM};
    color: {T.ink(T.INK_SECONDARY)};
}}
QPushButton[variant="nav"]:hover {{
    background: {T.ink(T.SURFACE_HOVER)};
    color: {T.ink(T.INK_PRIMARY)};
}}
QPushButton[variant="nav"]:pressed {{
    background: {T.ink(T.SURFACE_PRESSED)};
}}
QPushButton[variant="nav"]:checked {{
    background: {T.ink(T.SURFACE_SELECTED)};
    color: {T.ink(T.INK_PRIMARY)};
    font-weight: {T.WEIGHT_SEMIBOLD};
}}
QPushButton[variant="nav"]:focus {{
    border: 2px solid {T.ink(T.INK_GLYPH)};
    padding: 4px 8px;
}}

/* -- ScrollArea -------------------------------------------- */
QScrollArea {{
    background: {T.CANVAS};
    border: none;
}}
"""


# ---------------------------------------------------------------------------
# Application-level setup
# ---------------------------------------------------------------------------

def load_fonts() -> str:
    """Register the bundled Inter faces and return the family Qt filed them under.

    A variable font does not necessarily register under the name in the token:
    Inter's variable build files itself as "Inter Variable". The family that
    was actually registered is read back rather than assumed, so the app uses
    the type it ships with instead of silently falling back. A missing font
    file is logged rather than raised - the app still runs on the platform
    sans-serif, it just does not look like itself.
    """
    wanted = Tokens.FONT_FAMILY
    if not FONTS_DIR.is_dir():
        logger.warning("Bundled font directory missing: %s", FONTS_DIR)
        return wanted if wanted in QFontDatabase.families() else ""

    registered: list[str] = []
    for path in sorted(FONTS_DIR.glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id == -1:
            logger.warning("Qt refused the bundled font file: %s", path.name)
            continue
        registered.extend(QFontDatabase.applicationFontFamilies(font_id))

    if wanted in registered or wanted in QFontDatabase.families():
        return wanted
    # "Inter Variable" before "Inter Variable Text SemiBold": the shortest
    # name that still starts with the token is the family, not a weight.
    variants = [name for name in registered if name.startswith(wanted)]
    return min(variants, key=len) if variants else ""


def apply_theme(app: QApplication) -> None:
    """Apply the unified theme to a QApplication. Call once after construction."""

    # Resolve font: the bundled Inter first, the platform sans-serif only if
    # registering it failed. The platform family is kept either way so the QSS
    # font stack ends somewhere real.
    platform_family = app.font().family()
    family = load_fonts()
    if family:
        object.__setattr__(Tokens, "FONT_FAMILY", family)
        object.__setattr__(Tokens, "FONT_FALLBACK", platform_family)
    else:
        family = platform_family
        object.__setattr__(Tokens, "FONT_FAMILY", family)
        logger.warning("Inter unavailable; falling back to %s", family)

    font = QFont(family, Tokens.FONT_BODY)
    font.setWeight(QFont.Weight(Tokens.WEIGHT_REGULAR))
    app.setFont(font)

    # Build and apply QSS
    app.setStyleSheet(_build_qss())

    # Palette for widgets that ignore QSS (native dialogs, some item views)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(Tokens.CANVAS))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(Tokens.INK))
    palette.setColor(QPalette.ColorRole.Base, QColor(Tokens.CANVAS))
    palette.setColor(QPalette.ColorRole.AlternateBase,
                     QColor(Tokens.ink_hex(Tokens.SURFACE_WASH)))
    palette.setColor(QPalette.ColorRole.Text, QColor(Tokens.INK))
    palette.setColor(QPalette.ColorRole.Button, QColor(Tokens.CANVAS))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(Tokens.INK))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(Tokens.ACTION))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(Tokens.ACTION_TEXT))
    palette.setColor(QPalette.ColorRole.PlaceholderText,
                     QColor(Tokens.ink_hex(Tokens.INK_TERTIARY)))
    app.setPalette(palette)


def restyle(widget: QWidget) -> None:
    """Force a widget to re-read its stylesheet after a property change."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


# ---------------------------------------------------------------------------
# Standalone: verify the contrast ladder
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    print("Ink ladder - contrast against canvas:")
    check_ladder()
    print()

    canvas_lum = _relative_luminance(Tokens.CANVAS)
    for name, hex_val in [
        ("Action", Tokens.ACTION),
        ("Success", Tokens.SUCCESS),
        ("Warning", Tokens.WARNING),
        ("Error", Tokens.ERROR),
    ]:
        lum = _relative_luminance(hex_val)
        print(f"  {name:12s}  {hex_val}  "
              f"{_contrast_ratio(lum, canvas_lum):.1f}:1 on canvas")

    action_lum = _relative_luminance(Tokens.ACTION)
    text_lum = _relative_luminance(Tokens.ACTION_TEXT)
    print(f"  {'Action text':12s}  {Tokens.ACTION_TEXT} on {Tokens.ACTION}  "
          f"{_contrast_ratio(action_lum, text_lum):.1f}:1")

    print()
    print("Data series - contrast against canvas:")
    for i, hex_val in enumerate(Tokens.SERIES, start=1):
        lum = _relative_luminance(hex_val)
        ratio = _contrast_ratio(lum, canvas_lum)
        note = "" if ratio >= 3.0 else "   relief rule: needs a visible label"
        print(f"  slot {i}        {hex_val}  {ratio:.1f}:1{note}")

    print()
    print("Annotation marks - contrast against white paper:")
    marks = [
        ("Point", Tokens.MARK_POINT), ("Distance", Tokens.MARK_DISTANCE),
        ("Angle", Tokens.MARK_ANGLE), ("Polygon", Tokens.MARK_POLYGON),
        ("Polyline", Tokens.MARK_POLYLINE), ("Ellipse", Tokens.MARK_ELLIPSE),
        ("Text box", Tokens.MARK_TEXTBOX), ("Contour", Tokens.MARK_CONTOUR),
        ("Origin", Tokens.MARK_ORIGIN), ("Selected", Tokens.MARK_SELECTED),
        ("Guide", Tokens.MARK_GUIDE), ("Snap", Tokens.MARK_SNAP),
    ]
    for name, hex_val in marks:
        lum = _relative_luminance(hex_val)
        print(f"  {name:12s}  {hex_val}  {_contrast_ratio(lum, canvas_lum):.1f}:1")

    print()
    print("Contour severity ramp - most severe first:")
    for i, hex_val in enumerate(Tokens.CONTOUR_RAMP):
        lum = _relative_luminance(hex_val)
        print(f"  step {i}       {hex_val}  {_contrast_ratio(lum, canvas_lum):.1f}:1")
