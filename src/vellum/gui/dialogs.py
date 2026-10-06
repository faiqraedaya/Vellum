import csv
import io
import json
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFontComboBox, QHeaderView, QLineEdit,
    QPlainTextEdit, QPushButton, QSpinBox, QTableWidgetItem, QWidget,
)

from ..core.models import DiagramObject
from . import layout as ly
from .theme import Tokens as T, restyle

MAX_CONTOUR_LEVELS = 20
DEFAULT_CONTOUR_WIDTH = 2.0

# Width of the swatch a ColorButton draws, and of the column that holds one.
_SWATCH = T.ICON_SIZE
# Each column is wide enough for the control it holds, arrows included: a
# clipped distance or stroke width changes what the level means.
_COLOR_COLUMN_W = 124
# Wide enough for the largest distance the spin box accepts, not
# just for a typical one: a clipped distance is a wrong distance.
_DISTANCE_COLUMN_W = 224
_WIDTH_COLUMN_W = 124
_REFERENCE_COLUMN_W = 136
# Enough for every levels column at its own width, plus the window
# margins, so the table never has to scroll sideways to show a distance.
_LEVELS_TABLE_W = (_REFERENCE_COLUMN_W + _DISTANCE_COLUMN_W
                   + _WIDTH_COLUMN_W + _COLOR_COLUMN_W + 2 * T.MARGIN_WINDOW + 24)


def _color_row(button: "ColorButton"):
    """Put a colour button at its natural width, at the leading edge."""
    row = ly.hbox()
    row.addWidget(button)
    row.addStretch()
    return row


def _button_box(accept_text: str, parent: QDialog) -> QDialogButtonBox:
    """The dialog footer, with the accept button named after what it does.

    QDialogButtonBox is used everywhere so button order follows the platform,
    and the accept button is the one primary action in the footer.
    """
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                           | QDialogButtonBox.StandardButton.Cancel)
    ok = box.button(QDialogButtonBox.StandardButton.Ok)
    ok.setText(accept_text)
    ok.setProperty("variant", "primary")
    ok.setMinimumHeight(T.CONTROL_HEIGHT)
    restyle(ok)
    cancel = box.button(QDialogButtonBox.StandardButton.Cancel)
    cancel.setMinimumHeight(T.CONTROL_HEIGHT)
    box.accepted.connect(parent.accept)
    box.rejected.connect(parent.reject)
    return box


class ColorButton(QPushButton):
    """A push button showing the current colour, which opens a colour picker.

    The colour of a mark is an encoded value, so it keeps its colour - and the
    button always names the colour in text beside the swatch, so the value is
    never carried by the swatch alone.
    """

    def __init__(self, color="", parent=None):
        super().__init__(parent)
        self._color = QColor(color or T.MARK_POINT)
        self.setMinimumWidth(_COLOR_COLUMN_W - 8)
        self.setMinimumHeight(T.CONTROL_HEIGHT)
        self.clicked.connect(self._pick)
        self._refresh()

    def _refresh(self):
        # The swatch is an icon, NOT a background stylesheet: a background
        # stylesheet would be inherited by the QColorDialog opened as this
        # button's child and tint the whole picker.
        pm = QPixmap(_SWATCH, _SWATCH)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(T.ink_hex(T.SURFACE_BORDER_STRONG)), 1))
        p.setBrush(QBrush(self._color))
        p.drawRoundedRect(0, 0, _SWATCH - 1, _SWATCH - 1, 3, 3)
        p.end()
        self.setIcon(QIcon(pm))
        self.setText(self._color.name())
        self.setToolTip(f"Colour {self._color.name()} — click to change it")

    def _pick(self):
        c = QColorDialog.getColor(self._color, self.window(), "Select colour")
        if c.isValid():
            self._color = c
            self._refresh()

    def color_name(self) -> str:
        return self._color.name()

    def set_color(self, color):
        self._color = QColor(color)
        self._refresh()


# Display label -> stored value for the line-style dropdown.
LINE_STYLES = [("Solid", "solid"), ("Dashed", "dashed"),
               ("Dotted", "dotted"), ("Dash-dot", "dashdot")]


class LineStyleControls(QWidget):
    """Compact width spin box + line-style dropdown, shared by the object
    dialogs so any line-based object can set its stroke."""

    def __init__(self, width=0.0, style="solid", parent=None):
        super().__init__(parent)
        lay = ly.hbox(self)

        self._width = QDoubleSpinBox()
        self._width.setRange(0.5, 30.0)
        self._width.setSingleStep(0.5)
        self._width.setDecimals(1)
        self._width.setValue(width if width and width > 0 else 2.0)
        self._width.setMinimumHeight(T.CONTROL_HEIGHT)
        self._width.setMinimumWidth(88)
        self._width.setSuffix(" px")

        self._style = QComboBox()
        for label, val in LINE_STYLES:
            self._style.addItem(label, val)
        self.set_style(style)
        ly.choice_field(self._style, min_width=T.FIELD_MIN_W)

        # Each label sits beside its own control, with the gap to the next
        # pair visibly wider than the gap within a pair.
        lay.addWidget(ly.field_label("Width"))
        lay.addWidget(self._width)
        lay.addSpacing(T.SPACING_GROUP)
        lay.addWidget(ly.field_label("Style"))
        lay.addWidget(self._style, 1)

    def set_style(self, style: str):
        idx = self._style.findData(style)
        self._style.setCurrentIndex(idx if idx >= 0 else 0)

    def width(self) -> float:
        return self._width.value()

    def style(self) -> str:
        return self._style.currentData()


class ContourLevelsTable(QWidget):
    """Editor for a contour object's levels: a table of (reference value,
    distance, width, colour) rows, capped at MAX_CONTOUR_LEVELS."""

    _HEADERS = ("Reference value", "Distance", "Width", "Colour")

    levels_changed = Signal()

    def __init__(self, unit="px", levels=None, parent=None):
        super().__init__(parent)
        self._unit = unit
        v = ly.vbox(self)

        self._table = ly.results_table(
            [self._HEADERS[0], f"Distance ({unit})", self._HEADERS[2],
             self._HEADERS[3]],
            empty_text="No levels yet. Add one to give this contour a distance.",
            editable=True,
        )
        header = self._table.horizontalHeader()
        # The reference name absorbs the slack, but never below a width that
        # still reads; the distance, the width and the colour hold their own
        # size, because a clipped distance changes what the level means.
        # ResizeToContents is not used here: it does not measure the spin boxes
        # and colour buttons in the cells, so the columns are given explicit
        # widths instead.
        header.setStretchLastSection(False)
        # The floor applies to every section, so it is the narrowest column's
        # width - the reference column's own floor comes from the dialog's
        # minimum width, which leaves it _REFERENCE_COLUMN_W of slack.
        header.setMinimumSectionSize(_WIDTH_COLUMN_W)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in ((1, _DISTANCE_COLUMN_W), (2, _WIDTH_COLUMN_W),
                              (3, _COLOR_COLUMN_W)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self._table.setColumnWidth(column, width)
        self._table.verticalHeader().setDefaultSectionSize(T.CONTROL_HEIGHT + 8)
        self._table.itemChanged.connect(lambda *_: self.levels_changed.emit())
        ly.align_headers(self._table, numeric_columns=(1, 2))
        v.addWidget(self._table, 1)

        row = ly.hbox()
        self._add_btn = ly.button("Add level", on_click=lambda: self.add_row())
        self._rem_btn = ly.button("Remove last", on_click=self.remove_last)
        row.addWidget(self._add_btn)
        row.addWidget(self._rem_btn)
        row.addStretch()
        v.addLayout(row)

        self._limit_note = ly.caption("")
        self._limit_note.setVisible(False)
        v.addWidget(self._limit_note)

        if levels:
            for lv in levels[:MAX_CONTOUR_LEVELS]:
                self.add_row(lv.get("reference", ""), lv.get("distance", 0.0),
                             lv.get("color"), lv.get("width"))
        else:
            self.add_row()
        self._sync_controls()

    def _sync_controls(self):
        """Disable what does not apply, and say why rather than leaving a trap."""
        n = self._table.rowCount()
        at_limit = n >= MAX_CONTOUR_LEVELS
        self._add_btn.setEnabled(not at_limit)
        self._rem_btn.setEnabled(n > 1)
        # Silent until it matters: the note exists to explain a disabled
        # button, not to count rows the user can see.
        self._limit_note.setText(
            f"At the limit of {MAX_CONTOUR_LEVELS} levels — "
            "remove one before adding another." if at_limit else "")
        self._limit_note.setVisible(at_limit)

    def add_row(self, reference="", distance=0.0, color=None, width=None):
        n = self._table.rowCount()
        if n >= MAX_CONTOUR_LEVELS:
            return
        if color is None:
            color = T.contour(n)
        self._table.insertRow(n)
        self._table.setItem(n, 0, ly.table_item(str(reference)))

        spin = QDoubleSpinBox()
        spin.setRange(0.0, 1e12)
        spin.setDecimals(4)
        spin.setValue(float(distance))
        spin.setSuffix(f" {self._unit}")
        spin.setToolTip(f"How far this level reaches, in {self._unit}")
        spin.valueChanged.connect(lambda *_: self.levels_changed.emit())
        spin.setMinimumHeight(T.CONTROL_HEIGHT)
        self._table.setCellWidget(n, 1, spin)

        wspin = QDoubleSpinBox()
        wspin.setRange(0.5, 30.0)
        wspin.setSingleStep(0.5)
        wspin.setDecimals(1)
        wspin.setSuffix(" px")
        wspin.setValue(float(width) if width and float(width) > 0
                       else DEFAULT_CONTOUR_WIDTH)
        wspin.setToolTip("Stroke width of this level, in pixels")
        wspin.setMinimumHeight(T.CONTROL_HEIGHT)
        self._table.setCellWidget(n, 2, wspin)

        self._table.setCellWidget(n, 3, ColorButton(color))
        self._sync_controls()
        self.levels_changed.emit()

    def remove_last(self):
        if self._table.rowCount() > 1:
            self._table.removeRow(self._table.rowCount() - 1)
            self._sync_controls()
            self.levels_changed.emit()

    def levels(self) -> list:
        out = []
        for r in range(self._table.rowCount()):
            ref_item = self._table.item(r, 0)
            ref = ref_item.text().strip() if ref_item else ""
            spin = self._table.cellWidget(r, 1)
            dist = spin.value() if spin else 0.0
            wspin = self._table.cellWidget(r, 2)
            width = wspin.value() if wspin else DEFAULT_CONTOUR_WIDTH
            cbtn = self._table.cellWidget(r, 3)
            color = cbtn.color_name() if cbtn else T.contour(r)
            out.append({"reference": ref, "distance": dist,
                        "width": width, "color": color})
        return out


def levels_order_warning(levels) -> Optional[str]:
    """Return a warning message if contour distances aren't non-decreasing down
    the rows (each level should reach at least as far as the one above it), or
    None if the ordering is fine. Rows with no distance are ignored."""
    flagged = []
    prev = None
    for lv in levels:
        dist = float(lv.get("distance", 0) or 0)
        if dist <= 0:
            continue
        ref = lv.get("reference", "") or "(unnamed)"
        if prev is not None and dist < prev[1]:
            flagged.append(f"'{ref}' ({dist:g}) is closer than "
                           f"'{prev[0]}' ({prev[1]:g})")
        prev = (ref, dist)
    if not flagged:
        return None
    return ("Contour distances usually increase as the reference level becomes "
            "less severe: " + "; ".join(flagged)
            + ". The contour will still be created.")


class ContourLevelsDialog(QDialog):
    """Name + levels editor shown after a contour's geometry is placed."""

    def __init__(self, kind_label="Contour", unit="px", name="", levels=None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{kind_label} levels")
        self.setMinimumWidth(_LEVELS_TABLE_W)

        layout = ly.window_layout(self)

        form = ly.form()
        self.name_edit = QLineEdit(name)
        self.name_edit.setMinimumHeight(T.CONTROL_HEIGHT)
        form.addRow(ly.field_label("Name"), self.name_edit)
        layout.addLayout(form)

        section = ly.vbox()
        section.addWidget(ly.heading("Levels"))
        self._levels = ContourLevelsTable(unit, levels)
        section.addWidget(self._levels, 1)
        layout.addLayout(section, 1)

        # Ordering is checked inline and live: the levels stay on screen while
        # the user reads what is odd about them, and nothing blocks the way
        # out - an out-of-order contour is unusual, not invalid.
        self._status = ly.status_label()
        layout.addWidget(self._status)
        self._levels.levels_changed.connect(self._check_order)
        self._check_order()

        layout.addWidget(_button_box("Create contour", self))

    def _check_order(self):
        ly.set_status(self._status,
                      levels_order_warning(self._levels.levels()) or "",
                      "warning")

    def values(self) -> Tuple[str, list]:
        return self.name_edit.text().strip(), self._levels.levels()


class LegendTitleDialog(QDialog):
    """Edit the on-canvas legend title."""

    def __init__(self, title="Legend", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Legend title")
        self.setMinimumWidth(T.MIN_DIALOG_W)

        self.edit = QLineEdit(title)
        self.edit.setMinimumHeight(T.CONTROL_HEIGHT)
        self.edit.selectAll()

        layout = ly.window_layout(self)
        form = ly.form()
        form.addRow(ly.field_label("Legend title"), self.edit)
        layout.addLayout(form)
        layout.addWidget(_button_box("Rename legend", self))

    def title(self) -> str:
        return self.edit.text().strip()


class ScaleDistanceDialog(QDialog):
    """Set the scale from a distance the user already knows."""

    _PRESETS = ["mm", "cm", "m", "km", "in", "ft"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set scale from a known distance")
        self.setMinimumWidth(440)

        layout = ly.window_layout(self)

        form = ly.form()
        self.distance_spin = QDoubleSpinBox()
        self.distance_spin.setRange(1e-9, 1e12)
        self.distance_spin.setDecimals(6)
        self.distance_spin.setValue(1.0)
        form.addRow(ly.field_label("Known distance"),
                    ly.value_field(self.distance_spin))

        self.unit_edit = QLineEdit("m")
        self.unit_edit.setMinimumHeight(T.CONTROL_HEIGHT)
        form.addRow(ly.field_label("Unit"), self.unit_edit)

        presets = ly.hbox()
        for unit in self._PRESETS:
            btn = ly.button(unit, on_click=lambda checked=False, u=unit:
                            self.unit_edit.setText(u))
            # Sized to its label rather than fixed: a unit that clips changes
            # what every measurement in the drawing means.
            btn.setMinimumWidth(48)
            presets.addWidget(btn)
        presets.addStretch()
        form.addRow(ly.field_label("Presets"), presets)
        layout.addLayout(form)

        layout.addWidget(_button_box("Set scale", self))

    def values(self) -> Tuple[float, str]:
        return self.distance_spin.value(), self.unit_edit.text().strip() or "px"


class ScaleCoordsDialog(QDialog):
    """Set the scale from the coordinates of two clicked points."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set scale from known coordinates")
        self.setMinimumWidth(440)

        layout = ly.window_layout(self)
        form = ly.form()
        self._spins = {}
        # The labels name the clicked point each field belongs to; the keys
        # stay X1/Y1/X2/Y2 because that is the order values() returns.
        for name, label in (("X1", "Point 1 X"), ("Y1", "Point 1 Y"),
                            ("X2", "Point 2 X"), ("Y2", "Point 2 Y")):
            spin = QDoubleSpinBox()
            spin.setRange(-1e12, 1e12)
            spin.setDecimals(6)
            form.addRow(ly.field_label(label), ly.value_field(spin))
            self._spins[name] = spin

        self.unit_edit = QLineEdit("m")
        self.unit_edit.setMinimumHeight(T.CONTROL_HEIGHT)
        form.addRow(ly.field_label("Unit"), self.unit_edit)
        layout.addLayout(form)

        layout.addWidget(_button_box("Set scale", self))

    def values(self) -> Tuple[Tuple[float, float, float, float], str]:
        coords = tuple(self._spins[k].value() for k in ("X1", "Y1", "X2", "Y2"))
        return coords, self.unit_edit.text().strip() or "px"


_KIND_DISPLAY = {
    "point":    "point",
    "distance": "line",
    "angle":    "angle",
    "polygon":  "polygon",
    "polyline": "polyline",
}

# Default mark colour per kind, so a new object is legible before the user
# picks anything. The mapping itself lives in theme.py.
_KIND_DEFAULT_COLOR = {
    "point":    T.MARK_POINT,
    "distance": T.MARK_DISTANCE,
    "angle":    T.MARK_ANGLE,
    "polygon":  T.MARK_POLYGON,
    "polyline": T.MARK_POLYLINE,
    "ellipse":  T.MARK_ELLIPSE,
    "textbox":  T.MARK_TEXTBOX,
}


class NameDialog(QDialog):
    """Label a newly placed object and choose how it is drawn."""

    def __init__(self, kind: str = "point", default: str = "",
                 color: str = "", parent=None):
        super().__init__(parent)
        display = _KIND_DISPLAY.get(kind, kind.replace("_", " "))
        self.setWindowTitle(f"Label this {display}")
        self.setMinimumWidth(480)

        layout = ly.window_layout(self)
        form = ly.form()

        self.edit = QLineEdit(default)
        self.edit.setMinimumHeight(T.CONTROL_HEIGHT)
        self.edit.selectAll()
        form.addRow(ly.field_label("Label"), self.edit)

        self._color_btn = ColorButton(
            color or _KIND_DEFAULT_COLOR.get(kind, T.MARK_POINT))
        form.addRow(ly.field_label("Colour"), _color_row(self._color_btn))

        # Line width/style for every line-based object (not plain points).
        self._line = None
        if kind != "point":
            self._line = LineStyleControls()
            form.addRow(ly.field_label("Line"), self._line)

        layout.addLayout(form)
        layout.addWidget(_button_box(f"Add {display}", self))

    def label(self) -> str:
        return self.edit.text()

    def color(self) -> str:
        return self._color_btn.color_name()

    def line_width(self) -> float:
        return self._line.width() if self._line else 0.0

    def line_style(self) -> str:
        return self._line.style() if self._line else "solid"


class SetOriginDialog(QDialog):
    """Ask the user what world coordinates a clicked point corresponds to."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set origin coordinates")
        self.setMinimumWidth(T.MIN_DIALOG_W)

        layout = ly.window_layout(self)
        layout.addWidget(ly.caption(
            "Leave at (0, 0) for a standard image-relative origin."))

        form = ly.form()
        self._wx = QDoubleSpinBox()
        self._wx.setRange(-1e12, 1e12); self._wx.setDecimals(6); self._wx.setValue(0.0)
        self._wy = QDoubleSpinBox()
        self._wy.setRange(-1e12, 1e12); self._wy.setDecimals(6); self._wy.setValue(0.0)
        form.addRow(ly.field_label("World X"), ly.value_field(self._wx))
        form.addRow(ly.field_label("World Y"), ly.value_field(self._wy))
        layout.addLayout(form)

        layout.addWidget(_button_box("Set origin", self))

    def values(self) -> tuple:
        return self._wx.value(), self._wy.value()


class EditObjectDialog(QDialog):
    """Edit the name, colour, and world-coordinate vertices of a DiagramObject.
    For contour objects, edits the name and contour levels instead."""

    _VERTEX_LABELS = {
        "distance": ["P1", "P2"],
        "angle":    ["P1 (arm)", "P2 (vertex)", "P3 (arm)"],
        "polyline": [],   # dynamically numbered
    }

    def __init__(self, kind: str, name: str, world_pts: list, color: str = "",
                 levels: list = None, unit: str = "px",
                 line_width: float = 0.0, line_style: str = "solid", parent=None):
        super().__init__(parent)
        display = kind.replace("_", " ")
        self.setWindowTitle(f"Edit {display}")
        self._kind = kind
        self._is_contour = kind in ("polyline_contour", "point_contour")
        self._world_pts = list(world_pts)
        self.setMinimumWidth(_LEVELS_TABLE_W if self._is_contour else 480)

        layout = ly.window_layout(self)

        form = ly.form()
        self.name_edit = QLineEdit(name)
        self.name_edit.setMinimumHeight(T.CONTROL_HEIGHT)
        form.addRow(ly.field_label("Name"), self.name_edit)
        self._color_btn = None
        self._line = None
        if not self._is_contour:
            self._color_btn = ColorButton(
                color or _KIND_DEFAULT_COLOR.get(kind, T.MARK_POINT))
            form.addRow(ly.field_label("Colour"), _color_row(self._color_btn))
            if kind != "point":
                self._line = LineStyleControls(line_width, line_style)
                form.addRow(ly.field_label("Line"), self._line)
        layout.addLayout(form)

        self._levels = None
        self._table = None
        if self._is_contour:
            section = ly.vbox()
            section.addWidget(ly.heading("Levels"))
            self._levels = ContourLevelsTable(unit, levels)
            self._levels.levels_changed.connect(self._check_order)
            section.addWidget(self._levels, 1)
            layout.addLayout(section, 1)
        elif kind == "point":
            wx, wy = world_pts[0] if world_pts else (0.0, 0.0)
            self._wx = QDoubleSpinBox()
            self._wx.setRange(-1e12, 1e12); self._wx.setDecimals(6); self._wx.setValue(wx)
            self._wy = QDoubleSpinBox()
            self._wy.setRange(-1e12, 1e12); self._wy.setDecimals(6); self._wy.setValue(wy)
            pf = ly.form()
            pf.addRow(ly.field_label(f"World X ({unit})"), ly.value_field(self._wx))
            pf.addRow(ly.field_label(f"World Y ({unit})"), ly.value_field(self._wy))
            layout.addLayout(pf)
        else:
            section = ly.vbox()
            section.addWidget(ly.heading("Vertices"))
            self._table = ly.results_table(
                [f"World X ({unit})", f"World Y ({unit})"],
                empty_text="This object has no vertices.",
                stretch_last=False, editable=True,
            )
            self._table.verticalHeader().setVisible(True)
            ly.align_headers(self._table, numeric_columns=(0, 1))
            self._table.setRowCount(len(world_pts))
            v_labels = self._VERTEX_LABELS.get(
                kind, [f"P{i+1}" for i in range(len(world_pts))])
            for i in range(len(world_pts)):
                lbl = v_labels[i] if i < len(v_labels) else f"P{i+1}"
                self._table.setVerticalHeaderItem(i, QTableWidgetItem(lbl))
            for row, (wx, wy) in enumerate(world_pts):
                self._table.setItem(row, 0, ly.table_item(f"{wx:.6f}", numeric=True))
                self._table.setItem(row, 1, ly.table_item(f"{wy:.6f}", numeric=True))
            section.addWidget(self._table, 1)

            if kind in ("polygon", "polyline"):
                btn_row = ly.hbox()
                self._add_btn = ly.button("Add vertex", on_click=self._add_row)
                self._rem_btn = ly.button("Remove last", on_click=self._remove_row)
                btn_row.addWidget(self._add_btn)
                btn_row.addWidget(self._rem_btn)
                btn_row.addStretch()
                section.addLayout(btn_row)
                self._sync_vertex_controls()
            layout.addLayout(section, 1)

        self._status = ly.status_label()
        layout.addWidget(self._status)
        if self._is_contour:
            self._check_order()
        layout.addWidget(_button_box("Apply changes", self))

    def _check_order(self):
        ly.set_status(self._status,
                      levels_order_warning(self._levels.levels()) or "",
                      "warning")

    def _min_vertices(self) -> int:
        return 2 if self._kind == "polyline" else 3

    def _sync_vertex_controls(self):
        """Say why removing is unavailable rather than letting it fail quietly."""
        minimum = self._min_vertices()
        can_remove = self._table.rowCount() > minimum
        self._rem_btn.setEnabled(can_remove)
        self._rem_btn.setToolTip(
            "" if can_remove else
            f"A {self._kind} needs at least {minimum} vertices.")

    def _add_row(self):
        n = self._table.rowCount()
        self._table.setRowCount(n + 1)
        self._table.setVerticalHeaderItem(n, QTableWidgetItem(f"P{n+1}"))
        self._table.setItem(n, 0, ly.table_item("0.000000", numeric=True))
        self._table.setItem(n, 1, ly.table_item("0.000000", numeric=True))
        self._sync_vertex_controls()

    def _remove_row(self):
        if self._table.rowCount() > self._min_vertices():
            self._table.setRowCount(self._table.rowCount() - 1)
            self._sync_vertex_controls()

    def values(self) -> Tuple[str, list, str, list, float, str]:
        """Return (name, world_pts, color, levels, line_width, line_style)."""
        name = self.name_edit.text()
        color = self._color_btn.color_name() if self._color_btn else ""
        lw = self._line.width() if self._line else 0.0
        ls = self._line.style() if self._line else "solid"

        if self._is_contour:
            return name, self._world_pts, color, self._levels.levels(), lw, ls
        if self._kind == "point":
            return name, [(self._wx.value(), self._wy.value())], color, [], lw, ls
        pts = []
        for row in range(self._table.rowCount()):
            try:
                wx = float(self._table.item(row, 0).text())
                wy = float(self._table.item(row, 1).text())
            except (ValueError, AttributeError):
                wx, wy = 0.0, 0.0
            pts.append((wx, wy))
        return name, pts, color, [], lw, ls


class TextBoxDialog(QDialog):
    """Define a text box: content, font, colours, border line style, and fill."""

    _H_ALIGNS = [("Left", "left"), ("Center", "center"), ("Right", "right")]
    _V_ALIGNS = [("Top", "top"), ("Middle", "middle"), ("Bottom", "bottom")]

    def __init__(self, name="", text="", font_family="", font_size=0,
                 font_color="", line_color="", fill_color="",
                 line_width=0.0, line_style="solid", bold=False, italic=False,
                 underline=False, h_align="left", v_align="top", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Text box")
        self.setMinimumWidth(520)

        layout = ly.window_layout(self)

        top = ly.form()
        self.name_edit = QLineEdit(name)
        self.name_edit.setMinimumHeight(T.CONTROL_HEIGHT)
        top.addRow(ly.field_label("Name"), self.name_edit)
        layout.addLayout(top)

        text_section = ly.vbox()
        text_section.addWidget(ly.field_label("Text"))
        self.text_edit = QPlainTextEdit(text)
        self.text_edit.setMinimumHeight(96)
        text_section.addWidget(self.text_edit)
        layout.addLayout(text_section)

        form = ly.form()
        self.font_combo = QFontComboBox()
        if font_family:
            self.font_combo.setCurrentFont(QFont(font_family))
        ly.choice_field(self.font_combo)
        form.addRow(ly.field_label("Font"), self.font_combo)

        self.size_spin = QSpinBox()
        self.size_spin.setRange(4, 200)
        self.size_spin.setValue(font_size if font_size and font_size > 0 else 12)
        self.size_spin.setSuffix(" px")
        form.addRow(ly.field_label("Font size"), ly.value_field(self.size_spin))

        style_row = ly.hbox()
        self.bold_check = QCheckBox("Bold")
        self.bold_check.setChecked(bool(bold))
        self.italic_check = QCheckBox("Italic")
        self.italic_check.setChecked(bool(italic))
        self.underline_check = QCheckBox("Underline")
        self.underline_check.setChecked(bool(underline))
        style_row.addWidget(self.bold_check)
        style_row.addWidget(self.italic_check)
        style_row.addWidget(self.underline_check)
        style_row.addStretch()
        form.addRow(ly.field_label("Style"), style_row)

        align_row = ly.hbox()
        self.halign_combo = QComboBox()
        for lbl, val in self._H_ALIGNS:
            self.halign_combo.addItem(lbl, val)
        hi = self.halign_combo.findData(h_align)
        self.halign_combo.setCurrentIndex(hi if hi >= 0 else 0)
        ly.choice_field(self.halign_combo)
        self.valign_combo = QComboBox()
        for lbl, val in self._V_ALIGNS:
            self.valign_combo.addItem(lbl, val)
        vi = self.valign_combo.findData(v_align)
        self.valign_combo.setCurrentIndex(vi if vi >= 0 else 0)
        ly.choice_field(self.valign_combo)
        align_row.addWidget(ly.field_label("Horizontal"))
        align_row.addWidget(self.halign_combo, 1)
        align_row.addSpacing(T.SPACING_GROUP)
        align_row.addWidget(ly.field_label("Vertical"))
        align_row.addWidget(self.valign_combo, 1)
        form.addRow(ly.field_label("Align"), align_row)

        self.font_color_btn = ColorButton(font_color or T.MARK_TEXTBOX)
        form.addRow(ly.field_label("Font colour"), _color_row(self.font_color_btn))

        self.line_color_btn = ColorButton(line_color or T.MARK_TEXTBOX)
        form.addRow(ly.field_label("Border colour"), _color_row(self.line_color_btn))

        self._line = LineStyleControls(line_width, line_style)
        form.addRow(ly.field_label("Border line"), self._line)

        fill_row = ly.hbox()
        self.fill_check = QCheckBox("Fill the box")
        self.fill_color_btn = ColorButton(fill_color or T.MARK_TEXTBOX_FILL)
        has_fill = bool(fill_color)
        self.fill_check.setChecked(has_fill)
        # The colour only applies when the box is filled, so it is disabled
        # rather than left live and silently ignored.
        self.fill_color_btn.setEnabled(has_fill)
        self.fill_check.toggled.connect(self.fill_color_btn.setEnabled)
        fill_row.addWidget(self.fill_check)
        fill_row.addWidget(self.fill_color_btn)
        fill_row.addStretch()
        form.addRow(ly.field_label("Fill"), fill_row)
        layout.addLayout(form)

        layout.addWidget(_button_box("Add text box" if not text
                                     else "Apply changes", self))

    def values(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "text": self.text_edit.toPlainText(),
            "font_family": self.font_combo.currentFont().family(),
            "font_size": self.size_spin.value(),
            "font_color": self.font_color_btn.color_name(),
            "line_color": self.line_color_btn.color_name(),
            "fill_color": (self.fill_color_btn.color_name()
                           if self.fill_check.isChecked() else ""),
            "line_width": self._line.width(),
            "line_style": self._line.style(),
            "bold": self.bold_check.isChecked(),
            "italic": self.italic_check.isChecked(),
            "underline": self.underline_check.isChecked(),
            "h_align": self.halign_combo.currentData(),
            "v_align": self.valign_combo.currentData(),
        }


class ExportDialog(QDialog):
    """Preview every object as a row, then write it out or copy it."""

    _FIELDNAMES = ["type", "name", "value", "unit", "measurements", "timestamp",
                   "levels", "world_points", "image_points"]
    # Column headings for the preview. The exported field names themselves are
    # data and keep their own casing - sentence-casing them would change the
    # file the user gets.
    _HEADERS = ["Type", "Name", "Value", "Unit", "Measurements", "Timestamp",
                "Levels", "World points", "Image points"]
    _NUMERIC = (2,)

    def __init__(self, objects: List[DiagramObject], to_world=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export data")
        self.setMinimumSize(880, 520)
        self._to_world = to_world or (lambda x, y: (x, y))
        self._rows = [self._obj_to_row(o) for o in objects]

        layout = ly.window_layout(self)

        self.preview = ly.results_table(
            self._HEADERS,
            empty_text="Nothing to export yet. Place a measurement on the "
                       "drawing and it will appear here.",
            stretch_last=False,
        )
        ly.fill_table(self.preview,
                      [[row[k] for k in self._FIELDNAMES] for row in self._rows],
                      numeric_columns=self._NUMERIC)
        layout.addWidget(self.preview, 1)

        self._status = ly.status_label()
        layout.addWidget(self._status)

        # One primary action per group: writing the file. Copying and closing
        # are alternatives to it, not rivals for the same emphasis.
        btn_csv = ly.button("Export CSV…", variant="primary",
                            on_click=self._export_csv)
        btn_json = ly.button("Export JSON…", on_click=self._export_json)
        btn_clip = ly.button("Copy to clipboard", on_click=self._copy_clipboard)
        btn_close = ly.button("Close", on_click=self.accept)

        row = ly.action_row(btn_csv, btn_json, btn_clip)
        row.addWidget(btn_close)
        layout.addLayout(row)

        has_rows = bool(self._rows)
        for btn in (btn_csv, btn_json, btn_clip):
            btn.setEnabled(has_rows)
            if not has_rows:
                btn.setToolTip("There is nothing to export yet.")

    def _obj_to_row(self, obj: DiagramObject) -> dict:
        img_str = "; ".join(f"({x:.4f},{y:.4f})" for x, y in obj.points)
        world_str = "; ".join(
            "({:.4f},{:.4f})".format(*self._to_world(x, y)) for x, y in obj.points
        )
        levels_str = "; ".join(
            f"{lv.get('reference','')}@{lv.get('distance',0)}{lv.get('color','')}"
            for lv in obj.levels
        )
        has_value = obj.kind not in ("point", "polyline_contour", "point_contour")
        return {
            "type":         obj.kind,
            "name":         obj.name,
            "value":        obj.value if has_value else "",
            "unit":         obj.unit  if has_value else "",
            "measurements": obj._measure_inline() if has_value else "",
            "timestamp":    obj.timestamp,
            "levels":       levels_str,
            "world_points": world_str,
            "image_points": img_str,
        }

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "",
                                              "CSV files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self._FIELDNAMES)
                writer.writeheader()
                writer.writerows(self._rows)
        except OSError as e:
            ly.set_status(self._status, f"Could not write {path}: {e}", "error")
            return
        ly.set_status(self._status,
                      f"{len(self._rows)} objects written to {path}", "success")

    def _export_json(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export JSON", "",
                                              "JSON files (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._rows, f, indent=2)
        except OSError as e:
            ly.set_status(self._status, f"Could not write {path}: {e}", "error")
            return
        ly.set_status(self._status,
                      f"{len(self._rows)} objects written to {path}", "success")

    def _copy_clipboard(self):
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=self._FIELDNAMES)
        writer.writeheader()
        writer.writerows(self._rows)
        QApplication.clipboard().setText(buf.getvalue())
        ly.set_status(self._status,
                      f"{len(self._rows)} objects copied to the clipboard as CSV",
                      "success")
