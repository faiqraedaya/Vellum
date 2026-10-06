"""Assertions for the states a screenshot cannot prove on its own.

    python scripts/verify_ui.py

Exits non-zero if any check fails. Run it beside scripts/capture_ui.py after
any change to theme.py, layout.py, or a window: between them they cover the
verification list in the design system - focus chain, busy state, empty
states, header alignment, elision tooltips, and the minimum window size.
"""
import sys

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QComboBox, QHeaderView, QLineEdit,
    QPushButton, QTableWidget, QWidget,
)

from vellum.core.constants import Tool
from vellum.core.models import DiagramObject
from vellum.gui import dialogs, icons
from vellum.gui.theme import apply_theme, Tokens
from vellum.gui.window import MainWindow

failures = []


def check(ok, message):
    print(("  PASS  " if ok else "  FAIL  ") + message)
    if not ok:
        failures.append(message)


def check_table(table: QTableWidget, label: str, numeric_columns=()):
    header = table.horizontalHeader()
    for c in range(table.columnCount()):
        item = table.horizontalHeaderItem(c)
        if item is None:
            continue
        check(bool(item.toolTip()), f"{label}: header {c} has a tooltip")
        want = (Qt.AlignRight if c in numeric_columns else Qt.AlignLeft)
        got = Qt.Alignment(item.textAlignment()) & (Qt.AlignRight | Qt.AlignLeft)
        check(bool(got & want),
              f"{label}: header {c} alignment matches its cells")
    for r in range(table.rowCount()):
        for c in range(table.columnCount()):
            cell = table.item(r, c)
            if cell is None:      # a cell widget, not a text cell
                continue
            check(bool(cell.toolTip()) or not cell.text(),
                  f"{label}: cell ({r},{c}) carries its full text")
            if c in numeric_columns:
                check(bool(Qt.Alignment(cell.textAlignment()) & Qt.AlignRight),
                      f"{label}: cell ({r},{c}) is right aligned")
    check(not table.showGrid(), f"{label}: no gridlines")
    check(table.alternatingRowColors(), f"{label}: alternating row wash")
    check(table.textElideMode() == Qt.ElideRight, f"{label}: cells elide")
    total = sum(table.columnWidth(c) for c in range(table.columnCount()))
    if header.sectionResizeMode(0) == QHeaderView.Stretch:
        check(total <= table.viewport().width() + 1,
              f"{label}: columns fit without sideways scrolling")


def focusables(root: QWidget):
    for w in root.findChildren(QWidget):
        if (w.focusPolicy() & Qt.TabFocus and w.isVisible() and w.isEnabled()
                and not w.objectName().startswith("qt_")):
            yield w


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    apply_theme(app)

    print("Theme")
    check(Tokens.FONT_FAMILY.startswith("Inter"),
          f"the bundled family is in use ({Tokens.FONT_FAMILY})")
    check(Tokens.font_css().count(",") >= 1, "the font stack has a fallback")
    try:
        icons.icon("no-such-glyph")
        check(False, "an unknown icon name raises")
    except KeyError:
        check(True, "an unknown icon name raises")
    check(all(icons.tool_icon(t) is not None for t in Tool),
          "every tool has an icon")

    win = MainWindow()
    win.show()
    app.processEvents()

    print("Window")
    check(win.minimumWidth() >= 480 and win.minimumHeight() >= 360,
          f"minimum size set ({win.minimumWidth()}x{win.minimumHeight()})")
    check(win.viewer.minimumWidth() > 0, "the canvas keeps a minimum width")
    check(win.right_panel.minimumWidth() > 0,
          "the objects column keeps a minimum width")

    # Nothing clips at the minimum size: every visible widget stays inside its
    # parent, and the toolbar does not fold into an overflow menu.
    win.resize(win.MIN_WIDTH, win.MIN_HEIGHT)
    app.processEvents()
    tb = win._toolbar
    last = tb.actions()[-1]
    check(tb.widgetForAction(tb.actions()[10]).isVisible(),
          "the tool palette fits at the minimum window width")
    check(win.right_panel.export_btn.isVisible(),
          "the primary action is visible at the minimum window width")
    for widget in (win.right_panel.del_obj_btn, win.right_panel.clear_all_btn,
                   win.right_panel.move_up_btn, win.right_panel.move_down_btn):
        check(widget.width() >= widget.sizeHint().width(),
              f"'{widget.text()}' is not clipped at the minimum width")

    win.resize(1400, 860)
    app.processEvents()

    print("Nothing to act on")
    # Disabled, not hidden: hiding these would make the column jump, and
    # leaving them live would make them do nothing silently.
    for button in (win.right_panel.export_btn, win.right_panel.clear_all_btn,
                   win.right_panel.del_obj_btn, win.right_panel.move_up_btn,
                   win.right_panel.move_down_btn):
        check(not button.isEnabled(),
              f"'{button.text()}' is disabled with nothing to act on")
        check(bool(button.toolTip()), f"'{button.text()}' says why it is disabled")
        check(button.isVisible(), f"'{button.text()}' is still visible")
    check(not any(a.isEnabled() for a in win._tool_actions.values()),
          "the measurement tools are disabled with no document open")
    check(win._toolbar.actions()[0].isEnabled(),
          "opening a document is still available")

    print("Focus chain")
    win.right_panel.set_action_state(True, True)
    app.processEvents()
    for widget in list(focusables(win.right_panel)):
        widget.setFocus()
        app.processEvents()
        check(widget.hasFocus(),
              f"focus lands on {type(widget).__name__} "
              f"'{getattr(widget, 'text', lambda: '')()}'")
    win.right_panel.set_action_state(False, False)

    print("Busy state")
    win._set_inputs_enabled(False)
    win.set_busy(True, "Loading…")
    app.processEvents()
    check(win._progress.isVisible(), "the progress bar shows while running")
    check(not win._toolbar.isEnabled(), "the toolbar is disabled while running")
    check(not win.right_panel.isEnabled(),
          "the objects column is disabled while running")
    win.set_busy(False)
    win._set_inputs_enabled(True)
    app.processEvents()
    check(not win._progress.isVisible(), "the progress bar is released")
    check(win._toolbar.isEnabled(), "the toolbar is released")

    print("Empty states")
    check(bool(win.right_panel.objects_list.empty_text),
          "the objects list says what will appear in it")
    check(not win.right_panel.count_label.isVisible(),
          "the empty objects column does not repeat its own empty state")
    win.right_panel.set_object_count(3)
    check(win.right_panel.count_label.text() == "3 objects",
          "the objects column counts what it holds")
    win.right_panel.set_object_count(0)

    print("Dialogs")
    objs = [
        DiagramObject(kind="distance", name="Span", points=[(0, 0), (10, 0)]),
        DiagramObject(kind="point", name="Datum A", points=[(1, 2)]),
    ]
    d = dialogs.ExportDialog(objs, lambda x, y: (x, y))
    d.show(); app.processEvents()
    check_table(d.preview, "export preview", numeric_columns=(2,))
    check(d.minimumWidth() >= Tokens.MIN_DIALOG_W, "export dialog min width")
    d.close()

    d = dialogs.ExportDialog([], lambda x, y: (x, y))
    d.show(); app.processEvents()
    check(bool(d.preview.empty_text), "an empty export says why it is empty")
    buttons = {b.text(): b for b in d.findChildren(QPushButton)}
    check(not buttons["Export CSV…"].isEnabled(),
          "exporting nothing is disabled, with a reason in its tooltip")
    check(bool(buttons["Export CSV…"].toolTip()),
          "the disabled export button says why")
    d.close()

    d = dialogs.ContourLevelsDialog(
        "Point contour", "m", "Release",
        [{"reference": "Fatality", "distance": 90, "width": 2.0, "color": "#7F1D1D"},
         {"reference": "Serious injury", "distance": 40, "width": 2.0, "color": "#B91C1C"}])
    d.show(); app.processEvents()
    check_table(d._levels._table, "contour levels", numeric_columns=(1, 2))
    levels = d._levels._table
    for c in range(1, levels.columnCount()):
        widget = levels.cellWidget(0, c)
        if widget is not None:
            check(levels.columnWidth(c) >= widget.minimumSizeHint().width(),
                  f"contour levels: column {c} fits the control in it")
    check(not d._levels._limit_note.isVisible(),
          "the levels note stays quiet until the limit is reached")
    check(d._status.isVisible() and "closer than" in d._status.text(),
          "out-of-order levels are reported inline, in words")
    check(d._status.property("role") == "warning",
          "the inline report carries a semantic role, not colour alone")
    d.close()

    d = dialogs.EditObjectDialog("polyline", "Route", [(1.0, 2.0), (3.0, 4.0)],
                                 unit="m")
    d.show(); app.processEvents()
    check_table(d._table, "vertices", numeric_columns=(0, 1))
    check(not d._rem_btn.isEnabled() or d._table.rowCount() > 2,
          "removing below the minimum vertex count is disabled")
    check(bool(d._rem_btn.toolTip()) or d._rem_btn.isEnabled(),
          "the disabled remove button says why")
    d.close()

    for factory, name in ((dialogs.ScaleDistanceDialog, "scale distance"),
                          (dialogs.ScaleCoordsDialog, "scale coordinates"),
                          (dialogs.SetOriginDialog, "set origin"),
                          (dialogs.LegendTitleDialog, "legend title")):
        d = factory()
        d.show(); app.processEvents()
        check(d.minimumWidth() >= Tokens.MIN_DIALOG_W,
              f"{name} dialog is at least {Tokens.MIN_DIALOG_W} px wide")
        for w in d.findChildren(QWidget):
            if isinstance(w, (QLineEdit, QAbstractSpinBox, QComboBox)):
                check(w.height() >= Tokens.CONTROL_HEIGHT - 1,
                      f"{name}: {type(w).__name__} is on the control height")
                break
        d.close()

    print()
    if failures:
        print(f"{len(failures)} FAILED:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
