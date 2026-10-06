"""The New page wizard: size, resolution and orientation of a blank page."""

from __future__ import annotations

import math

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QLineEdit, QSpinBox,
)

from ..core import pages
from ..core.pages import PRESETS, PagePreset
from . import layout as ly
from .dialogs import _button_box
from .theme import Tokens as T

_CUSTOM = "Custom"
# Combo data for "no preset" and "no ratio": findData() cannot find None.
_NONE = "none"
_UNITS = (("Millimetres", "mm"), ("Inches", "in"), ("Pixels", "px"))
_DECIMALS = {"mm": 1, "in": 3, "px": 0}

# Long side over short side. Orientation decides which way round it lands, so
# "16 : 9" in portrait is a 9 x 16 page.
_RATIOS = (
    ("Free", _NONE),
    ("Keep current", "current"),
    ("1 : 1", 1.0),
    ("4 : 3", 4 / 3),
    ("3 : 2", 3 / 2),
    ("16 : 9", 16 / 9),
    ("ISO paper, 1 : √2", math.sqrt(2)),
)


class NewPageDialog(QDialog):
    """Choose the size of a blank page, Photoshop-style: start from a preset,
    then adjust width, height, units, resolution and orientation."""

    def __init__(self, untitled_name: str = "Untitled", parent=None):
        super().__init__(parent)
        self.setWindowTitle("New page")
        self.setMinimumWidth(480)

        self._w_in = 0.0
        self._h_in = 0.0
        self._lock: float | None = None   # long side / short side
        self._updating = False

        layout = ly.window_layout(self)

        self.name_edit = QLineEdit(untitled_name)
        self.name_edit.setMinimumHeight(T.CONTROL_HEIGHT)

        self.preset_combo = ly.choice_field(QComboBox())
        last_group = None
        for preset in PRESETS:
            if last_group is not None and preset.group != last_group:
                self.preset_combo.insertSeparator(self.preset_combo.count())
            last_group = preset.group
            self.preset_combo.addItem(self._preset_label(preset), preset)
        self.preset_combo.insertSeparator(self.preset_combo.count())
        self.preset_combo.addItem(_CUSTOM, _NONE)

        self.width_spin = ly.value_field(QDoubleSpinBox())
        self.height_spin = ly.value_field(QDoubleSpinBox())
        self.unit_combo = ly.choice_field(QComboBox())
        for label, unit in _UNITS:
            self.unit_combo.addItem(label, unit)

        self.dpi_spin = ly.value_field(QSpinBox())
        self.dpi_spin.setRange(10, 2400)
        self.dpi_spin.setValue(pages.DEFAULT_DPI)

        self.orientation_combo = ly.choice_field(QComboBox())
        self.orientation_combo.addItem("Portrait", "portrait")
        self.orientation_combo.addItem("Landscape", "landscape")

        self.ratio_combo = ly.choice_field(QComboBox())
        for label, ratio in _RATIOS:
            self.ratio_combo.addItem(label, ratio)

        # Units sit in their own column so width and height line up, and the
        # unit beside each value is never the thing that clips.
        grid = ly.grid()
        grid.setColumnStretch(1, 1)
        rows = [
            ("Name", self.name_edit, None),
            ("Preset", self.preset_combo, None),
            ("Width", self.width_spin, self.unit_combo),
            ("Height", self.height_spin, None),
            ("Resolution", self.dpi_spin, ly.unit_label("px/in")),
            ("Orientation", self.orientation_combo, None),
            ("Aspect ratio", self.ratio_combo, None),
        ]
        for r, (label, field, trailing) in enumerate(rows):
            grid.addWidget(ly.field_label(label), r, 0)
            grid.addWidget(field, r, 1, 1, 1 if trailing else 2)
            if trailing is not None:
                grid.addWidget(trailing, r, 2)
        self._height_unit = ly.unit_label("mm")
        grid.addWidget(self._height_unit, 3, 2)
        layout.addLayout(grid)

        # The summary says what will actually be made, in every unit at once,
        # so the user never has to convert in their head.
        self.summary = ly.caption("")
        layout.addWidget(self.summary)
        self.status = ly.status_label()
        layout.addWidget(self.status)

        self.buttons = _button_box("Create page", self)
        layout.addWidget(self.buttons)

        self.preset_combo.currentIndexChanged.connect(self._on_preset)
        self.unit_combo.currentIndexChanged.connect(self._on_unit)
        self.width_spin.valueChanged.connect(self._on_width)
        self.height_spin.valueChanged.connect(self._on_height)
        self.dpi_spin.valueChanged.connect(self._on_dpi)
        self.orientation_combo.currentIndexChanged.connect(self._on_orientation)
        self.ratio_combo.currentIndexChanged.connect(self._on_ratio)

        default = next(i for i in range(self.preset_combo.count())
                       if isinstance(self.preset_combo.itemData(i), PagePreset)
                       and self.preset_combo.itemData(i).name == pages.DEFAULT_PRESET)
        self.preset_combo.setCurrentIndex(default)
        self._on_preset()
        self.name_edit.selectAll()

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    def page_name(self) -> str:
        return self.name_edit.text().strip() or "Untitled"

    def dpi(self) -> int:
        return self.dpi_spin.value()

    def pixel_size(self) -> tuple[int, int]:
        return pages.pixel_size(self._w_in, self._h_in, self.dpi())

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _preset_label(preset: PagePreset) -> str:
        return f"{preset.name}  ({preset.width:g} × {preset.height:g} {preset.unit})"

    def _unit(self) -> str:
        return self.unit_combo.currentData()

    def _landscape(self) -> bool:
        return self.orientation_combo.currentData() == "landscape"

    def _set_combo_data(self, combo: QComboBox, data) -> None:
        combo.blockSignals(True)
        combo.setCurrentIndex(combo.findData(data))
        combo.blockSignals(False)

    def _mark_custom(self) -> None:
        self._set_combo_data(self.preset_combo, _NONE)

    def _sync_orientation_from_size(self) -> None:
        if self._w_in != self._h_in:
            self._set_combo_data(self.orientation_combo,
                                 "landscape" if self._w_in > self._h_in else "portrait")

    def _refresh(self) -> None:
        """Push the held size into the fields, and say what will be made."""
        unit, dpi = self._unit(), self.dpi()
        self._updating = True
        for spin, inches in ((self.width_spin, self._w_in),
                             (self.height_spin, self._h_in)):
            spin.setDecimals(_DECIMALS[unit])
            spin.setRange(10 ** -_DECIMALS[unit], pages.from_inches(2000, unit, dpi))
            spin.setValue(pages.from_inches(inches, unit, dpi))
        self._updating = False
        self._height_unit.setText(unit)

        w_px, h_px = self.pixel_size()
        w_mm, h_mm = self._w_in * pages.MM_PER_INCH, self._h_in * pages.MM_PER_INCH
        segments = (
            f"{w_px:,} × {h_px:,} px",
            f"{w_mm:.1f} × {h_mm:.1f} mm",
            f"{self._w_in:.2f} × {self._h_in:.2f} in",
            f"aspect {pages.ratio_text(self.width_spin.value(), self.height_spin.value())}",
            f"{w_px * h_px / 1e6:.1f} MP",
        )
        # Wrap only between segments, never inside a value and its unit.
        self.summary.setText("  ·  ".join(s.replace(" ", " ") for s in segments))

        problem = pages.size_problem(w_px, h_px)
        ly.set_status(self.status, problem or "", "error" if problem else "")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(problem is None)

    def _apply_lock(self, changed: str) -> None:
        """Recompute the other side from the one just edited."""
        if self._lock is None:
            return
        # The edited side is long or short according to the orientation.
        if changed == "width":
            self._h_in = self._w_in / self._lock if self._landscape() else self._w_in * self._lock
        else:
            self._w_in = self._h_in * self._lock if self._landscape() else self._h_in / self._lock

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_preset(self) -> None:
        preset = self.preset_combo.currentData()
        if not isinstance(preset, PagePreset):
            return
        if preset.dpi is not None:
            self.dpi_spin.blockSignals(True)
            self.dpi_spin.setValue(preset.dpi)
            self.dpi_spin.blockSignals(False)
        self._set_combo_data(self.unit_combo, preset.unit)
        dpi = self.dpi()
        w = pages.to_inches(preset.width, preset.unit, dpi)
        h = pages.to_inches(preset.height, preset.unit, dpi)
        # Presets are stored the way they are usually named (A4 portrait,
        # Full HD landscape); the orientation field decides how they land.
        short, long_ = sorted((w, h))
        if preset.group == "Screen" or self._landscape():
            self._w_in, self._h_in = long_, short
        else:
            self._w_in, self._h_in = short, long_
        self._sync_orientation_from_size()
        self._lock = None
        self._set_combo_data(self.ratio_combo, _NONE)
        self._refresh()

    def _on_unit(self) -> None:
        self._refresh()

    def _on_width(self, value: float) -> None:
        if self._updating:
            return
        self._w_in = pages.to_inches(value, self._unit(), self.dpi())
        self._apply_lock("width")
        self._after_manual_edit()

    def _on_height(self, value: float) -> None:
        if self._updating:
            return
        self._h_in = pages.to_inches(value, self._unit(), self.dpi())
        self._apply_lock("height")
        self._after_manual_edit()

    def _after_manual_edit(self) -> None:
        self._mark_custom()
        if self._lock is None:
            self._sync_orientation_from_size()
        self._refresh()

    def _on_dpi(self) -> None:
        # A pixel size keeps its pixels when the resolution changes; a paper
        # size keeps its millimetres and gains or loses pixels instead.
        if self._unit() == "px":
            dpi = self.dpi()
            self._w_in = self.width_spin.value() / dpi
            self._h_in = self.height_spin.value() / dpi
        self._refresh()

    def _on_orientation(self) -> None:
        if (self._w_in > self._h_in) != self._landscape() and self._w_in != self._h_in:
            self._w_in, self._h_in = self._h_in, self._w_in
        self._refresh()

    def _on_ratio(self) -> None:
        ratio = self.ratio_combo.currentData()
        if ratio == _NONE:
            self._lock = None
        elif ratio == "current":
            short, long_ = sorted((self._w_in, self._h_in))
            self._lock = long_ / short
        else:
            self._lock = float(ratio)
            self._apply_lock("width")
            self._mark_custom()
        self._refresh()
