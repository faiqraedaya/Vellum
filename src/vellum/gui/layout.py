"""
Layout and widget factories built on the design tokens.

Every layout in the app is created through these helpers so margins, spacing
and control geometry land on the 8 px grid by construction rather than by
each caller remembering to set them. Qt's own defaults (9 px margin, 6 px
spacing) are off-grid and are never relied on.

No widget here calls ``setStyleSheet`` - appearance comes from ``theme.py``.
Variants are set through dynamic properties.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QListWidget, QPushButton, QSizePolicy, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .theme import Tokens, restyle

T = Tokens


# ---------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------

def vbox(parent: QWidget | None = None, *, margin: int = 0,
         spacing: int | None = None) -> QVBoxLayout:
    """Vertical layout with explicit token margins and spacing."""
    layout = QVBoxLayout(parent) if parent is not None else QVBoxLayout()
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(T.SPACING_ROW if spacing is None else spacing)
    return layout


def hbox(parent: QWidget | None = None, *, margin: int = 0,
         spacing: int | None = None) -> QHBoxLayout:
    """Horizontal layout with explicit token margins and spacing."""
    layout = QHBoxLayout(parent) if parent is not None else QHBoxLayout()
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(T.SPACING_ROW if spacing is None else spacing)
    return layout


def grid(parent: QWidget | None = None, *, margin: int = 0) -> QGridLayout:
    """Grid layout for parameter rows whose units and actions align in columns.

    Column spacing is tighter than row spacing so a label sits visibly closer
    to its own field than to the next row.
    """
    layout = QGridLayout(parent) if parent is not None else QGridLayout()
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setHorizontalSpacing(T.SPACING_ROW)
    layout.setVerticalSpacing(T.SPACING_ROW)
    return layout


def form(parent: QWidget | None = None, *, margin: int = 0) -> QFormLayout:
    """Form layout for plain parameter entry. Labels align left app-wide."""
    layout = QFormLayout(parent) if parent is not None else QFormLayout()
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setHorizontalSpacing(T.SPACING_ROW)
    layout.setVerticalSpacing(T.SPACING_ROW)
    layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
    layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    return layout


def window_layout(parent: QWidget) -> QVBoxLayout:
    """Top-level layout for a window or dialog: window margins, group spacing."""
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(T.MARGIN_WINDOW, T.MARGIN_WINDOW,
                              T.MARGIN_WINDOW, T.MARGIN_WINDOW)
    layout.setSpacing(T.SPACING_GROUP)
    return layout


def panel(*, margin: int = 0, spacing: int | None = None):
    """A plain container widget plus its vertical layout.

    Returns ``(widget, layout)``. The widget draws no border of its own - it
    groups content without adding another outline to whatever already
    encloses it.
    """
    widget = QWidget()
    layout = vbox(widget, margin=margin,
                  spacing=T.SPACING_GROUP if spacing is None else spacing)
    return widget, layout


def splitter(*widgets, orientation=Qt.Horizontal, sizes=None,
             stretch=None) -> QSplitter:
    """Splitter with a grab area wide enough to hit (padding is in the QSS).

    The panes are passed in rather than added afterwards: Qt discards
    ``setSizes`` issued before the widgets exist, so a splitter built the
    other way round silently ignores its intended proportions.
    """
    split = QSplitter(orientation)
    split.setChildrenCollapsible(False)
    split.setHandleWidth(T.SPLITTER_GRAB)
    for widget in widgets:
        split.addWidget(widget)
    if stretch:
        for index, factor in enumerate(stretch):
            split.setStretchFactor(index, factor)
    if sizes:
        split.setSizes(list(sizes))
    return split


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

def title(text: str) -> QLabel:
    """The name of the current page. One per screen, at the top of it."""
    label = QLabel(text)
    label.setProperty("role", "title")
    return label


def brand(text: str) -> QLabel:
    """The application name in the navigation rail."""
    label = QLabel(text)
    label.setProperty("role", "brand")
    return label


def heading(text: str) -> QLabel:
    """Section heading. Earns its place only above 3+ controls or a result."""
    label = QLabel(text)
    label.setProperty("role", "heading")
    return label


def caption(text: str) -> QLabel:
    """Supporting text: column captions, held-constant notes, hints."""
    label = QLabel(text)
    label.setProperty("role", "caption")
    label.setWordWrap(True)
    return label


def field_label(text: str) -> QLabel:
    """Label for an input. Sentence case, no trailing colon."""
    return QLabel(text)


def unit_label(text: str) -> QLabel:
    """Engineering unit beside a value.

    Fixed to its own width and never wrapped: a clipped unit changes what
    the number means, so it is the last thing allowed to give way.
    """
    label = QLabel(text)
    label.setProperty("role", "unit")
    label.setWordWrap(False)
    label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
    label.setMinimumWidth(label.fontMetrics().horizontalAdvance(text) + 4)
    return label


def action_row(primary_button: QPushButton, *others) -> QHBoxLayout:
    """The app's one action-row shape: primary first, then a stretch.

    Every window places its main action identically, so the eye finds it in
    the same spot on every tab.
    """
    row = hbox()
    row.addWidget(primary_button)
    for widget in others:
        row.addWidget(widget)
    row.addStretch()
    return row


def status_label(text: str = "", role: str = "") -> QLabel:
    """Inline status line. ``role`` is "", "error", "warning" or "success".

    Colour never carries the meaning alone - the text always says what
    happened.
    """
    label = QLabel(text)
    label.setWordWrap(True)
    label.setVisible(bool(text))
    if role:
        label.setProperty("role", role)
    return label


def set_status(label: QLabel, text: str, role: str = "") -> None:
    """Update a status label's text and semantic role, hiding it when empty."""
    label.setText(text)
    label.setProperty("role", role or None)
    label.setVisible(bool(text))
    restyle(label)


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------

def button(text: str, *, variant: str = "", on_click=None,
           tooltip: str = "") -> QPushButton:
    """Push button. ``variant`` is "", "primary", "quiet" or "danger".

    At most one primary button per action group.
    """
    btn = QPushButton(text)
    if variant:
        btn.setProperty("variant", variant)
    if on_click is not None:
        btn.clicked.connect(on_click)
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setMinimumHeight(T.CONTROL_HEIGHT)
    return btn


def value_field(widget: QWidget) -> QWidget:
    """Give a numeric entry control a floor width so long values never clip."""
    widget.setMinimumWidth(T.FIELD_MIN_W)
    widget.setMinimumHeight(T.CONTROL_HEIGHT)
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return widget


def choice_field(widget: QWidget, *, min_width: int = 0) -> QWidget:
    """Size a combo box consistently with the other controls in its row."""
    widget.setMinimumHeight(T.CONTROL_HEIGHT)
    if min_width:
        widget.setMinimumWidth(min_width)
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return widget


def read_only(widget: QWidget) -> QWidget:
    """Mark a control as showing a computed value rather than taking input."""
    widget.setProperty("readOnlyValue", "true")
    return widget


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

class ResultsTable(QTableWidget):
    """A table that says what will appear in it instead of sitting blank.

    An empty results area is the most common dead end in a calculation tool:
    the user cannot tell whether nothing was found, something failed, or they
    have not run anything yet. One tertiary line naming the action that fills
    the table answers all three.
    """

    def __init__(self, empty_text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.empty_text = empty_text

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.rowCount() or not self.empty_text:
            return
        painter = QPainter(self.viewport())
        painter.setPen(QColor(T.ink_hex(T.INK_TERTIARY)))
        font = painter.font()
        font.setPixelSize(T.FONT_CAPTION)
        font.setWeight(QFont.Weight(T.WEIGHT_MEDIUM))
        painter.setFont(font)
        rect = self.viewport().rect().adjusted(
            T.MARGIN_GROUP, T.MARGIN_GROUP, -T.MARGIN_GROUP, -T.MARGIN_GROUP)
        painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap,
                         self.empty_text)
        painter.end()


def results_table(headers: list, *, empty_text: str = "",
                  stretch_last: bool = True,
                  sortable: bool = False,
                  editable: bool = False) -> ResultsTable:
    """A results table wired to the design system.

    Alternating row wash instead of gridlines, elided cells with the full
    value in a tooltip, and an empty-state line rather than a blank
    rectangle.
    """
    table = ResultsTable(empty_text)
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.ElideRight)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setEditTriggers(
        QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        if editable else QAbstractItemView.NoEditTriggers)
    table.setSortingEnabled(sortable)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(T.CONTROL_HEIGHT)
    header = table.horizontalHeader()
    if header is not None:
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if stretch_last and len(headers) > 1:
            # Narrow table: the first column absorbs the slack and elides;
            # every other column keeps its content at full length.
            header.setStretchLastSection(False)
            header.setSectionResizeMode(0, QHeaderView.Stretch)
            for c in range(1, len(headers)):
                header.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        else:
            # Wide table: it scrolls horizontally in its own container, and
            # the last column takes up any slack so the rows do not stop
            # short of the table's own border.
            header.setSectionResizeMode(QHeaderView.Interactive)
            header.setStretchLastSection(True)
    set_header_tooltips(table)
    return table


def set_header_tooltips(table: QTableWidget) -> None:
    """Put each column's full heading in a tooltip.

    Headers elide when a column narrows; without this the user cannot
    recover what the column was.
    """
    for c in range(table.columnCount()):
        item = table.horizontalHeaderItem(c)
        if item is not None and item.text():
            item.setToolTip(item.text())


def align_headers(table: QTableWidget, numeric_columns=()) -> None:
    """Match each header's alignment to the cells below it."""
    for c in range(table.columnCount()):
        item = table.horizontalHeaderItem(c)
        if item is None:
            continue
        item.setTextAlignment(
            (Qt.AlignRight if c in numeric_columns else Qt.AlignLeft)
            | Qt.AlignVCenter)


def table_item(text: str, *, numeric: bool = False) -> QTableWidgetItem:
    """A table cell that always exposes its full text through a tooltip."""
    item = QTableWidgetItem(text)
    item.setToolTip(text)
    if numeric:
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    else:
        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    return item


def fill_table(table: QTableWidget, rows: list, *,
               numeric_columns=()) -> None:
    """Replace a table's contents, preserving sort state and tooltips."""
    was_sorting = table.isSortingEnabled()
    table.setSortingEnabled(False)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.setItem(r, c, table_item(str(value),
                                           numeric=c in numeric_columns))
    table.setSortingEnabled(was_sorting)
    set_header_tooltips(table)
    align_headers(table, numeric_columns)
    header = table.horizontalHeader()
    if header is not None and header.sectionResizeMode(0) == QHeaderView.Interactive:
        table.resizeColumnsToContents()


def table_rows(table: QTableWidget) -> list:
    """Every populated row of a table as a list of cell strings."""
    rows = []
    for r in range(table.rowCount()):
        cells = [table.item(r, c) for c in range(table.columnCount())]
        if all(cells):
            rows.append([cell.text() for cell in cells])
    return rows


class EmptyStateList(QListWidget):
    """A list that says what will appear in it instead of sitting blank.

    Same reasoning as ``ResultsTable``: an empty rectangle cannot tell the
    user whether nothing matched, something failed, or they have not done
    anything yet.
    """

    def __init__(self, empty_text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.empty_text = empty_text

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count() or not self.empty_text:
            return
        painter = QPainter(self.viewport())
        painter.setPen(QColor(T.ink_hex(T.INK_TERTIARY)))
        font = painter.font()
        font.setPixelSize(T.FONT_CAPTION)
        font.setWeight(QFont.Weight(T.WEIGHT_MEDIUM))
        painter.setFont(font)
        rect = self.viewport().rect().adjusted(
            T.MARGIN_GROUP, T.MARGIN_GROUP, -T.MARGIN_GROUP, -T.MARGIN_GROUP)
        painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, self.empty_text)
        painter.end()


def list_widget(*, empty_text: str = "",
                selection=QAbstractItemView.ExtendedSelection) -> EmptyStateList:
    """A list wired to the design system: row wash, elision, empty state."""
    widget = EmptyStateList(empty_text)
    widget.setAlternatingRowColors(True)
    widget.setTextElideMode(Qt.ElideRight)
    widget.setSelectionMode(selection)
    widget.setUniformItemSizes(False)
    return widget


def list_item_tooltips(widget: QListWidget) -> None:
    """Give every row its own full text as a tooltip.

    Rows elide as readily as table cells, and an elided measurement label is
    a value the user can no longer read.
    """
    for row in range(widget.count()):
        item = widget.item(row)
        if item is not None and not item.toolTip():
            item.setToolTip(item.text())


def vseparator() -> QFrame:
    """A 1 px vertical rule, for use between unrelated status-bar segments."""
    line = QFrame()
    line.setFrameShape(QFrame.NoFrame)
    line.setProperty("role", "vsep")
    line.setFixedWidth(1)
    return line


def empty_state(text: str) -> QLabel:
    """One tertiary line saying what will appear here and what fills it."""
    label = caption(text)
    label.setAlignment(Qt.AlignCenter)
    return label
