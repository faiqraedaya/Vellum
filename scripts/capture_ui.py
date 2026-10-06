"""Render every surface of Vellum to PNG so the design can be looked at.

    python scripts/capture_ui.py [output directory]

Code inspection is not verification: clipped units, overflowing icons and
double borders are invisible in a diff and obvious in a screenshot. Each page
is captured at its default size and at the window's minimum, empty and
populated with real results, plus every dialog.
"""
import sys
from pathlib import Path

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

from vellum.core.constants import Tool
from vellum.core.models import DiagramObject
from vellum.gui.theme import apply_theme
from vellum.gui.window import MainWindow
from vellum.gui import dialogs

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "build/ui-shots")
OUT.mkdir(parents=True, exist_ok=True)


def sample_drawing(path: Path) -> Path:
    """A light technical-drawing-ish page, like the documents this tool opens."""
    img = QImage(1400, 900, QImage.Format_RGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor("#C8C8C8"), 1))
    for x in range(0, 1400, 50):
        p.drawLine(x, 0, x, 900)
    for y in range(0, 900, 50):
        p.drawLine(0, y, 1400, y)
    p.setPen(QPen(QColor("#404040"), 3))
    p.drawRect(200, 160, 900, 560)
    p.drawLine(200, 440, 1100, 440)
    p.drawEllipse(QPointF(650, 440), 180, 180)
    p.end()
    img.save(str(path))
    return path


def grab(widget, name):
    widget.grab().save(str(OUT / f"{name}.png"))
    print("captured", name)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    apply_theme(app)

    win = MainWindow()
    win.show()
    app.processEvents()
    grab(win, "01_window_empty")

    win.resize(win.MIN_WIDTH, win.MIN_HEIGHT)
    app.processEvents()
    grab(win, "02_window_minimum")

    win.resize(1400, 860)
    drawing = sample_drawing(OUT / "_sample.png")
    win._load_path(str(drawing))
    app.processEvents()

    v = win.viewer
    v.fit_to_window()

    def add(kind, name, pts, **kw):
        obj = DiagramObject(kind=kind, name=name,
                            points=[(float(x), float(y)) for x, y in pts], **kw)
        v.objects.append(obj)
        return obj

    add("point", "Datum A", [(200, 160)])
    add("point", "Datum B", [(1100, 720)])
    add("distance", "Span", [(200, 440), (1100, 440)])
    add("angle", "Corner", [(200, 720), (200, 440), (650, 260)])
    add("polygon", "Footprint", [(300, 250), (900, 250), (900, 600), (300, 600)])
    add("polyline", "Route", [(250, 800), (500, 760), (760, 820), (1100, 780)])
    add("ellipse", "Bore", [(470, 260), (830, 620)])
    add("textbox", "Note", [(950, 180), (1330, 300)],
        text="Overall span measured\nfrom datum A.")
    add("point_contour", "Release point", [(650, 440)],
        levels=[{"reference": "Fatality", "distance": 60, "width": 2.0,
                 "color": dialogs.T.contour(0)},
                {"reference": "Serious injury", "distance": 110, "width": 2.0,
                 "color": dialogs.T.contour(1)},
                {"reference": "Minor injury", "distance": 170, "width": 2.0,
                 "color": dialogs.T.contour(2)}])
    v.set_selection([2])
    v.objects_changed.emit()
    win._refresh_ui_for_active_tab()
    win.set_status("9 objects placed")
    app.processEvents()
    grab(win, "03_window_populated")

    # Busy state: the bar is visible and every input is disabled.
    win._set_inputs_enabled(False)
    win.set_busy(True, "Loading objects… (120 of 400)")
    win._progress.setRange(0, 400)
    win._progress.setValue(120)
    app.processEvents()
    grab(win, "04_window_busy")
    assert win._progress.isVisible(), "busy: progress bar not shown"
    assert not win._toolbar.isEnabled(), "busy: toolbar still live"
    win.set_busy(False)
    win._set_inputs_enabled(True)
    app.processEvents()
    assert not win._progress.isVisible(), "busy released: bar still shown"
    assert win._toolbar.isEnabled(), "busy released: toolbar still disabled"

    # A tool selected, so the checked toolbar state is on screen.
    win._set_tool(Tool.ADD_POLYGON)
    app.processEvents()
    grab(win, "05_window_tool_checked")

    # Focus chain: every focusable widget must show its ring.
    win._set_tool(Tool.PAN)
    win.right_panel.export_btn.setFocus()
    app.processEvents()
    grab(win, "06_focus_primary_button")
    win.right_panel.objects_list.setFocus()
    app.processEvents()
    grab(win, "07_focus_objects_list")

    # Dialogs, each populated.
    d = dialogs.ExportDialog(list(v.objects),
                             lambda x, y: v.img_to_world(QPointF(x, y)))
    d.show(); app.processEvents(); grab(d, "10_dialog_export"); d.close()

    d = dialogs.ExportDialog([], lambda x, y: (x, y))
    d.show(); app.processEvents(); grab(d, "11_dialog_export_empty"); d.close()

    d = dialogs.ContourLevelsDialog("Point contour", "m", "Release point",
                                    [{"reference": "Fatality", "distance": 90,
                                      "width": 2.0, "color": dialogs.T.contour(0)},
                                     {"reference": "Serious injury", "distance": 40,
                                      "width": 2.0, "color": dialogs.T.contour(1)}])
    d.show(); app.processEvents(); grab(d, "12_dialog_contour_warning"); d.close()

    d = dialogs.EditObjectDialog("polyline", "Route",
                                 [(1.0, 2.0), (3.5, 4.25), (9.0, 12.5)],
                                 color=dialogs.T.MARK_POLYLINE, unit="m",
                                 line_width=2.0, line_style="dashed")
    d.show(); app.processEvents(); grab(d, "13_dialog_edit_polyline"); d.close()

    d = dialogs.TextBoxDialog(name="Note", text="Overall span measured "
                              "from datum A.", font_size=14)
    d.show(); app.processEvents(); grab(d, "14_dialog_textbox"); d.close()

    d = dialogs.ScaleDistanceDialog()
    d.show(); app.processEvents(); grab(d, "15_dialog_scale_distance"); d.close()

    d = dialogs.ScaleCoordsDialog()
    d.show(); app.processEvents(); grab(d, "16_dialog_scale_coords"); d.close()

    d = dialogs.NameDialog("distance", "Span")
    d.show(); app.processEvents(); grab(d, "17_dialog_name"); d.close()

    d = dialogs.SetOriginDialog()
    d.show(); app.processEvents(); grab(d, "18_dialog_set_origin"); d.close()

    d = dialogs.LegendTitleDialog("Risk contours")
    d.show(); app.processEvents(); grab(d, "19_dialog_legend_title"); d.close()

    print("done")


if __name__ == "__main__":
    main()
