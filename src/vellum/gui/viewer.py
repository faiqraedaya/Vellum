import math
import os
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from PySide6.QtCore import Qt, QPointF, QRect, QRectF, QSize, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontInfo, QFontMetrics, QImage, QPainter, QPalette, QPen,
    QPixmap, QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication, QDialog, QMenu, QPlainTextEdit, QSizePolicy,
    QTabBar, QToolButton, QWidget,
)

from ..core.constants import Tool
from ..core import contours
from .dialogs import (
    ContourLevelsDialog, EditObjectDialog, LegendTitleDialog, NameDialog,
    ScaleCoordsDialog, ScaleDistanceDialog, SetOriginDialog, TextBoxDialog,
)
from ..core.models import DiagramObject, Point, ScaleInfo
from ..core.pdf_export import ExportStyle, PageMarkup
from . import icons
from .theme import Tokens as T

_HIT_R      = 8   # hit-test radius in screen pixels
_DRAG_THRESH = 4  # pixels before a press becomes a drag
_MAX_UNDO   = 100 # maximum retained undo steps (per page)

# Every colour here comes from theme.py. A mark is an encoded value drawn on
# top of the user's document, so it keeps its colour - and every mark carries
# its own drawn label, so colour is never the only thing identifying it.
_KIND_COLOR = {
    "point":    QColor(T.MARK_POINT),
    "distance": QColor(T.MARK_DISTANCE),
    "angle":    QColor(T.MARK_ANGLE),
    "polygon":  QColor(T.MARK_POLYGON),
    "polyline": QColor(T.MARK_POLYLINE),
    "ellipse":  QColor(T.MARK_ELLIPSE),
    "textbox":  QColor(T.MARK_TEXTBOX),
    "polyline_contour": QColor(T.MARK_CONTOUR),
    "point_contour":    QColor(T.MARK_CONTOUR),
}

_SEL_COLOR      = QColor(T.MARK_SELECTED)   # the current selection
_LABEL_COLOR    = QColor(T.MARK_TEXTBOX)    # a label with no colour of its own
_PREVIEW_COLOR  = QColor(T.MARK_PREVIEW)    # geometry still being placed
_HANDLE_COLOR   = QColor(T.MARK_SELECTED)   # draggable vertex handles
_DATUM_COLOR    = QColor(T.MARK_ORIGIN)     # origin and scale references
_SKELETON_COLOR = QColor(T.MARK_GUIDE)      # thin dashed defining geometry of contours
_BBOX_COLOR     = QColor(T.MARK_GUIDE)      # thin dashed bounding box (ellipse/textbox)

_PEN_STYLES = {
    "solid":   Qt.PenStyle.SolidLine,
    "dashed":  Qt.PenStyle.DashLine,
    "dotted":  Qt.PenStyle.DotLine,
    "dashdot": Qt.PenStyle.DashDotLine,
}

_H_ALIGN = {
    "left":   Qt.AlignmentFlag.AlignLeft,
    "center": Qt.AlignmentFlag.AlignHCenter,
    "right":  Qt.AlignmentFlag.AlignRight,
}
_V_ALIGN = {
    "top":    Qt.AlignmentFlag.AlignTop,
    "middle": Qt.AlignmentFlag.AlignVCenter,
    "bottom": Qt.AlignmentFlag.AlignBottom,
}


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _dist_pt_to_seg(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _point_in_polygon(px, py, poly) -> bool:
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _snap_cardinal(base: QPointF, pos: QPointF) -> QPointF:
    dx = pos.x() - base.x()
    dy = pos.y() - base.y()
    angle = math.atan2(dy, dx)
    snapped = round(angle / (math.pi / 2)) * (math.pi / 2)
    dist = math.hypot(dx, dy)
    return QPointF(base.x() + dist * math.cos(snapped), base.y() + dist * math.sin(snapped))


def _square_box(base: QPointF, pos: QPointF) -> QPointF:
    """Constrain the opposite corner so the box base→pos is square (for a 1:1
    ellipse / circle while holding Shift)."""
    dx = pos.x() - base.x()
    dy = pos.y() - base.y()
    m = max(abs(dx), abs(dy))
    sx = -1.0 if dx < 0 else 1.0
    sy = -1.0 if dy < 0 else 1.0
    return QPointF(base.x() + sx * m, base.y() + sy * m)


def _ellipse_circumference(a: float, b: float) -> float:
    """Ramanujan's approximation of an ellipse circumference (semi-axes a, b)."""
    if a <= 0 and b <= 0:
        return 0.0
    h = ((a - b) ** 2) / ((a + b) ** 2) if (a + b) else 0.0
    return math.pi * (a + b) * (1 + (3 * h) / (10 + math.sqrt(4 - 3 * h)))


def _seg_insert_point(screen_pos: QPointF, sa: QPointF, sb: QPointF) -> QPointF:
    """Project screen_pos onto segment sa→sb and return the closest screen point."""
    ax, ay = sa.x(), sa.y()
    bx, by = sb.x(), sb.y()
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((screen_pos.x() - ax) * dx + (screen_pos.y() - ay) * dy) / denom)) if denom else 0.0
    return QPointF(ax + t * dx, ay + t * dy)


# ---------------------------------------------------------------------------
# Inline text-box editor (overlay shown on double-click)
# ---------------------------------------------------------------------------

class _InlineTextEditor(QPlainTextEdit):
    """A floating editor for changing a text box's content in place. Commits on
    focus-out or Ctrl+Enter; cancels on Escape."""
    committed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._done = False

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._done = True
            self.cancelled.emit()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self._done = True
            self.committed.emit(self.toPlainText())
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        if not self._done:
            self._done = True
            self.committed.emit(self.toPlainText())
        super().focusOutEvent(event)


# ---------------------------------------------------------------------------
# PageState — per-page annotation + measurement state
# DocumentTab — per-document state held by ImageViewer
# ---------------------------------------------------------------------------

@dataclass
class PageState:
    """All annotation / measurement state that belongs to a single page. An
    image has exactly one page (index 0); a PDF has one PageState per page so
    annotations, scale, origin and history are kept independent per page."""
    origin: Point = field(default_factory=lambda: Point(0.0, 0.0))
    origin_world: Tuple[float, float] = (0.0, 0.0)
    scale_info: ScaleInfo = field(default_factory=lambda: ScaleInfo(1.0, 1.0, "px"))

    temp: List[Point] = field(default_factory=list)
    objects: List[DiagramObject] = field(default_factory=list)
    selection: set = field(default_factory=set)

    undo_stack: List[dict] = field(default_factory=list)
    redo_stack: List[dict] = field(default_factory=list)

    legend_title: str = "Legend"
    legend_visible: bool = True


@dataclass
class DocumentTab:
    """All state that belongs to a single opened document (image or PDF). Page
    annotations live in `pages` (keyed by page index); everything here is shared
    across the document's pages (the open file, current view, PDF handle)."""
    file_path: str = ""
    title: str = ""                     # a blank page's name; files use their own
    pixmap: Optional[QPixmap] = None
    pdf_doc: object = None              # fitz.Document or None
    pdf_page_index: int = 0
    pdf_dpi: int = 150

    zoom: float = 1.0
    pan: QPointF = field(default_factory=QPointF)

    pages: Dict[int, PageState] = field(default_factory=dict)

    session_path: Optional[str] = None

    def page(self, index: int) -> PageState:
        """Return the PageState for `index`, creating it on first access."""
        ps = self.pages.get(index)
        if ps is None:
            ps = PageState()
            self.pages[index] = ps
        return ps

    @property
    def current_page_state(self) -> PageState:
        return self.page(self.pdf_page_index)

    def display_label(self) -> str:
        if self.file_path:
            return os.path.basename(self.file_path)
        return self.title or "Untitled"


# ---------------------------------------------------------------------------
# ImageViewer
# ---------------------------------------------------------------------------

class ImageViewer(QWidget):
    # Informational
    scale_set          = Signal(ScaleInfo)
    origin_set         = Signal(Point)
    mouse_world_pos    = Signal(float, float)
    zoom_changed       = Signal(float)
    live_measure       = Signal(str)

    # State changes
    state_restored        = Signal()
    tool_change_requested = Signal(Tool)
    objects_changed       = Signal()
    selection_changed     = Signal(list)
    delete_requested      = Signal()

    # Tab lifecycle
    tab_changed          = Signal(int)     # active tab index changed (or -1)
    tab_close_requested  = Signal(int)     # user clicked X — MainWindow decides

    def __init__(self, parent=None):
        super().__init__(parent)

        # --- Shared (cross-tab) state ---
        self.current_tool  = Tool.PAN
        self._clipboard: List[DiagramObject] = []
        self._mouse_img: Optional[QPointF] = None

        # Transient interaction state (also cross-tab; cancelled on tab switch)
        self._panning      = False
        self._pan_start_screen = QPointF()
        self._pan_start_pan    = QPointF()
        self._pan_moved        = False

        # Vertex drag (in PAN mode, on selected object)
        self._vtx_drag_obj    = -1
        self._vtx_drag_vtx    = -1
        self._vtx_drag_active = False
        self._vtx_drag_start_img  = QPointF()
        self._vtx_drag_start_pts: list = []
        self._vtx_drag_snap: dict = {}

        # Selection drag (PAN mode, moving whole objects)
        self._sel_press_obj = -1
        self._sel_press_pos: Optional[QPointF] = None
        self._sel_drag_active   = False
        self._sel_drag_start    = QPointF()
        self._sel_drag_start_pts: dict = {}
        self._sel_drag_snap: dict = {}

        # Zoom-rect tool
        self._zoom_rect_start: Optional[QPointF] = None   # screen coords

        # Box-select tool
        self._box_sel_start: Optional[QPointF] = None     # screen coords
        self._box_sel_additive = False                    # Ctrl-drag → add to selection
        self._box_sel_base: set = set()                   # selection at drag start

        # View toggles
        self._show_objects = True
        self._show_labels = True

        # Inline text-box editor (created on demand)
        self._inline_editor: Optional[_InlineTextEditor] = None
        self._inline_obj_idx = -1

        # Contour render cache (rebuilt only when the signature changes)
        self._contour_cache: list = []
        self._contour_cache_sig = None
        self._legend_rect: Optional[QRectF] = None   # last drawn legend bounds (screen)

        # Arrow-key nudge burst tracking
        self._nudge_burst_active = False

        # --- Tabs ---
        self._tabs: List[DocumentTab] = []
        self._active_idx: int = -1
        self._suppress_tab_signal = False

        # Tab bar (positioned at top by resizeEvent)
        self._tab_bar = QTabBar(self)
        self._tab_bar.setObjectName("documentTabs")
        self._tab_bar.setTabsClosable(True)
        self._tab_bar.setElideMode(Qt.TextElideMode.ElideMiddle)
        self._tab_bar.setMovable(True)
        self._tab_bar.setDocumentMode(True)
        self._tab_bar.setExpanding(False)
        self._tab_bar.setDrawBase(False)
        self._tab_bar.setUsesScrollButtons(True)
        self._tab_bar.currentChanged.connect(self._on_tab_bar_current_changed)
        self._tab_bar.tabCloseRequested.connect(self._on_tab_bar_close_requested)
        self._tab_bar.tabMoved.connect(self._on_tab_bar_moved)
        self._tab_bar.hide()

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # The canvas keeps a usable width however far the splitter is dragged:
        # below this a fitted page is too small to measure on.
        self.setMinimumSize(420, 320)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    # ------------------------------------------------------------------
    # Per-tab state — delegating properties
    # ------------------------------------------------------------------

    @property
    def _active(self) -> Optional[DocumentTab]:
        if 0 <= self._active_idx < len(self._tabs):
            return self._tabs[self._active_idx]
        return None

    @property
    def _page(self) -> Optional[PageState]:
        """The active document's currently-shown page state (or None)."""
        a = self._active
        return a.current_page_state if a is not None else None

    @property
    def _pixmap(self) -> Optional[QPixmap]:
        return self._active.pixmap if self._active else None
    @_pixmap.setter
    def _pixmap(self, val):
        if self._active is not None:
            self._active.pixmap = val

    @property
    def _pdf_doc(self):
        return self._active.pdf_doc if self._active else None
    @_pdf_doc.setter
    def _pdf_doc(self, val):
        if self._active is not None:
            self._active.pdf_doc = val

    @property
    def _pdf_page_index(self) -> int:
        return self._active.pdf_page_index if self._active else 0
    @_pdf_page_index.setter
    def _pdf_page_index(self, val):
        if self._active is not None:
            self._active.pdf_page_index = val

    @property
    def _pdf_dpi(self) -> int:
        return self._active.pdf_dpi if self._active else 150
    @_pdf_dpi.setter
    def _pdf_dpi(self, val):
        if self._active is not None:
            self._active.pdf_dpi = val

    @property
    def _zoom(self) -> float:
        return self._active.zoom if self._active else 1.0
    @_zoom.setter
    def _zoom(self, val):
        if self._active is not None:
            self._active.zoom = val

    @property
    def _pan(self) -> QPointF:
        return self._active.pan if self._active else QPointF(0.0, 0.0)
    @_pan.setter
    def _pan(self, val):
        if self._active is not None:
            self._active.pan = val

    @property
    def origin(self) -> Point:
        return self._page.origin if self._page else Point(0.0, 0.0)
    @origin.setter
    def origin(self, val):
        if self._page is not None:
            self._page.origin = val

    @property
    def _origin_world(self) -> Tuple[float, float]:
        return self._page.origin_world if self._page else (0.0, 0.0)
    @_origin_world.setter
    def _origin_world(self, val):
        if self._page is not None:
            self._page.origin_world = val

    @property
    def scale_info(self) -> ScaleInfo:
        return self._page.scale_info if self._page else ScaleInfo(1.0, 1.0, "px")
    @scale_info.setter
    def scale_info(self, val):
        if self._page is not None:
            self._page.scale_info = val

    @property
    def _temp(self) -> List[Point]:
        return self._page.temp if self._page else []
    @_temp.setter
    def _temp(self, val):
        if self._page is not None:
            self._page.temp = val

    @property
    def objects(self) -> List[DiagramObject]:
        return self._page.objects if self._page else []
    @objects.setter
    def objects(self, val):
        if self._page is not None:
            self._page.objects = val

    @property
    def _selection(self) -> set:
        return self._page.selection if self._page else set()
    @_selection.setter
    def _selection(self, val):
        if self._page is not None:
            self._page.selection = val

    @property
    def _undo_stack(self) -> List[dict]:
        return self._page.undo_stack if self._page else []
    @_undo_stack.setter
    def _undo_stack(self, val):
        if self._page is not None:
            self._page.undo_stack = val

    @property
    def _redo_stack(self) -> List[dict]:
        return self._page.redo_stack if self._page else []
    @_redo_stack.setter
    def _redo_stack(self, val):
        if self._page is not None:
            self._page.redo_stack = val

    @property
    def legend_title(self) -> str:
        return self._page.legend_title if self._page else "Legend"
    @legend_title.setter
    def legend_title(self, val):
        if self._page is not None:
            self._page.legend_title = val

    @property
    def legend_visible(self) -> bool:
        return self._page.legend_visible if self._page else True
    @legend_visible.setter
    def legend_visible(self, val):
        if self._page is not None:
            self._page.legend_visible = val

    # ------------------------------------------------------------------
    # Tab management
    # ------------------------------------------------------------------

    @property
    def tab_count(self) -> int:
        return len(self._tabs)

    @property
    def current_tab_index(self) -> int:
        return self._active_idx

    def tab_file_path(self, idx: int) -> str:
        if 0 <= idx < len(self._tabs):
            return self._tabs[idx].file_path
        return ""

    def current_tab_file_path(self) -> str:
        return self._active.file_path if self._active else ""

    def current_tab_label(self) -> str:
        return self._active.display_label() if self._active else ""

    def current_tab_pdf_bytes(self) -> bytes:
        """The active document as PDF bytes, for one with no file on disk."""
        if self._active is None or self._active.pdf_doc is None:
            return b""
        return self._active.pdf_doc.tobytes()

    def current_tab_session_path(self) -> Optional[str]:
        return self._active.session_path if self._active else None

    def set_current_tab_session_path(self, path: Optional[str]):
        if self._active is not None:
            self._active.session_path = path

    def add_tab(self, file_path: str = "", activate: bool = True, title: str = "") -> int:
        """Create a new (empty) tab and optionally make it active."""
        tab = DocumentTab(file_path=file_path, title=title)
        self._tabs.append(tab)
        idx = len(self._tabs) - 1

        self._suppress_tab_signal = True
        self._tab_bar.addTab(self._tab_label_for(tab))
        self._tab_bar.setTabToolTip(idx, file_path or tab.display_label())
        self._tab_bar.setTabButton(idx, QTabBar.ButtonPosition.RightSide,
                                   self._make_close_button())
        self._tab_bar.show()
        self._suppress_tab_signal = False

        if activate:
            self.set_current_tab(idx)
        self._update_geometry()
        return idx

    def close_tab(self, idx: int) -> bool:
        """Close the tab at idx. Returns True if removed."""
        if not (0 <= idx < len(self._tabs)):
            return False
        tab = self._tabs[idx]
        if tab.pdf_doc is not None:
            try:
                tab.pdf_doc.close()
            except Exception:
                pass

        del self._tabs[idx]

        self._suppress_tab_signal = True
        self._tab_bar.removeTab(idx)
        self._suppress_tab_signal = False

        if not self._tabs:
            self._active_idx = -1
            self._tab_bar.hide()
            self._cancel_transient_interactions()
            self.tab_changed.emit(-1)
            self.update()
            self._update_geometry()
            return True

        # Adjust active index to stay valid
        new_active = self._tab_bar.currentIndex()
        if new_active < 0:
            new_active = min(idx, len(self._tabs) - 1)
        self._active_idx = new_active
        self._cancel_transient_interactions()
        self.tab_changed.emit(self._active_idx)
        self.update()
        self._update_geometry()
        return True

    def set_current_tab(self, idx: int):
        if not (0 <= idx < len(self._tabs)):
            return
        if idx == self._active_idx:
            # Make sure tab bar reflects it
            if self._tab_bar.currentIndex() != idx:
                self._suppress_tab_signal = True
                self._tab_bar.setCurrentIndex(idx)
                self._suppress_tab_signal = False
            return
        self._cancel_transient_interactions()
        self._active_idx = idx
        if self._tab_bar.currentIndex() != idx:
            self._suppress_tab_signal = True
            self._tab_bar.setCurrentIndex(idx)
            self._suppress_tab_signal = False
        self.tab_changed.emit(idx)
        self.update()

    def refresh_tab_label(self, idx: int):
        if 0 <= idx < len(self._tabs):
            tab = self._tabs[idx]
            self._tab_bar.setTabText(idx, self._tab_label_for(tab))
            self._tab_bar.setTabToolTip(idx, tab.file_path or tab.display_label())

    def _tab_label_for(self, tab: DocumentTab) -> str:
        label = tab.display_label()
        if tab.pdf_doc is not None and len(tab.pdf_doc) > 1:
            label = f"{label}  [{tab.pdf_page_index + 1}/{len(tab.pdf_doc)}]"
        return label

    def _cancel_transient_interactions(self):
        self._finish_inline_edit()
        self._panning = False
        self._pan_moved = False
        self._vtx_drag_active = False
        self._vtx_drag_obj = -1
        self._vtx_drag_vtx = -1
        self._vtx_drag_start_pts = []
        self._sel_drag_active = False
        self._sel_press_obj = -1
        self._sel_press_pos = None
        self._zoom_rect_start = None
        self._box_sel_start = None
        self._box_sel_base = set()
        self._nudge_burst_active = False

    def _on_tab_bar_current_changed(self, idx: int):
        if self._suppress_tab_signal:
            return
        if 0 <= idx < len(self._tabs):
            self.set_current_tab(idx)

    def _make_close_button(self) -> QToolButton:
        """The tab's close control, in the app's own icon family.

        Qt's built-in closable tab draws the platform style's close glyph,
        which on Fusion is a red cross that belongs to no other part of this
        app. The button is looked up by identity when clicked, because a tab's
        index changes as tabs are closed and dragged.
        """
        button = QToolButton(self._tab_bar)
        button.setIcon(icons.icon("close"))
        button.setIconSize(QSize(T.ICON_SIZE, T.ICON_SIZE))
        button.setAutoRaise(True)
        button.setToolTip("Close this document")
        button.clicked.connect(lambda: self._close_button_clicked(button))
        return button

    def _close_button_clicked(self, button: QToolButton):
        for i in range(self._tab_bar.count()):
            if self._tab_bar.tabButton(
                    i, QTabBar.ButtonPosition.RightSide) is button:
                self._on_tab_bar_close_requested(i)
                return

    def _on_tab_bar_close_requested(self, idx: int):
        # MainWindow decides whether to close (with confirmation if needed).
        self.tab_close_requested.emit(idx)

    def _on_tab_bar_moved(self, from_idx: int, to_idx: int):
        if from_idx == to_idx:
            return
        tab = self._tabs.pop(from_idx)
        self._tabs.insert(to_idx, tab)
        self._active_idx = self._tab_bar.currentIndex()
        self.update()

    # ------------------------------------------------------------------
    # Canvas-area helpers (region below the tab bar)
    # ------------------------------------------------------------------

    def _canvas_top(self) -> int:
        return self._tab_bar.height() if self._tab_bar.isVisible() else 0

    def _canvas_width(self) -> int:
        return self.width()

    def _canvas_height(self) -> int:
        return max(0, self.height() - self._canvas_top())

    def _canvas_center(self) -> Tuple[float, float]:
        top = self._canvas_top()
        return self.width() / 2.0, top + (self.height() - top) / 2.0

    def _update_geometry(self):
        """Reposition the tab bar across the top of the viewer."""
        if self._tabs:
            h = self._tab_bar.sizeHint().height()
            self._tab_bar.setGeometry(0, 0, self.width(), h)
            self._tab_bar.show()
        else:
            self._tab_bar.hide()

    def resizeEvent(self, event):
        self._finish_inline_edit()
        self._update_geometry()
        super().resizeEvent(event)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def objects_visible(self) -> bool:
        return self._show_objects

    def set_objects_visible(self, visible: bool):
        if self._show_objects == visible:
            return
        self._show_objects = visible
        self.update()

    @property
    def labels_visible(self) -> bool:
        return self._show_labels

    def set_labels_visible(self, visible: bool):
        if self._show_labels == visible:
            return
        self._show_labels = visible
        self.update()

    def set_legend_visible(self, visible: bool):
        if self._page is None or self._page.legend_visible == visible:
            return
        self._page.legend_visible = visible
        self.update()

    def edit_legend_title(self):
        if self._active is None:
            return
        dlg = LegendTitleDialog(self.legend_title, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._push_undo()
            self.legend_title = dlg.title() or "Legend"
            self.update()

    @property
    def current_page(self) -> int:
        return self._pdf_page_index

    @property
    def pdf_page_count(self) -> int:
        return len(self._pdf_doc) if self._pdf_doc is not None else 0

    # ------------------------------------------------------------------
    # Coordinate transforms
    # ------------------------------------------------------------------

    def _img_to_screen(self, img_pt: QPointF) -> QPointF:
        cx, cy = self._canvas_center()
        return QPointF(
            (img_pt.x() - self._pan.x()) * self._zoom + cx,
            (img_pt.y() - self._pan.y()) * self._zoom + cy,
        )

    def _screen_to_img(self, screen_pt: QPointF) -> QPointF:
        cx, cy = self._canvas_center()
        return QPointF(
            (screen_pt.x() - cx) / self._zoom + self._pan.x(),
            (screen_pt.y() - cy) / self._zoom + self._pan.y(),
        )

    def img_to_world(self, img_pt: QPointF) -> Tuple[float, float]:
        sf = self.scale_info.scale_factor
        ox, oy = self._origin_world
        return (img_pt.x() - self.origin.x) * sf + ox, -(img_pt.y() - self.origin.y) * sf + oy

    def _world_to_img(self, wx: float, wy: float) -> QPointF:
        sf = self.scale_info.scale_factor
        if sf == 0:
            return QPointF(self.origin.x, self.origin.y)
        ox, oy = self._origin_world
        return QPointF(
            (wx - ox) / sf + self.origin.x,
            -(wy - oy) / sf + self.origin.y,
        )

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def open_in_new_tab(self, path: str) -> int:
        """Open `path` as a brand-new tab. Returns tab index, or -1 on failure."""
        idx = self.add_tab(file_path=path, activate=True)
        if not self.load_file(path):
            # Roll back: remove the failed tab
            self.close_tab(idx)
            return -1
        # Refresh the label (may now reflect PDF page count etc.)
        self.refresh_tab_label(idx)
        return idx

    def open_blank_tab(self, doc, dpi: int, title: str) -> int:
        """Open an in-memory PDF (a blank page) as a new, unsaved tab.
        Returns the tab index, or -1 if the page could not be drawn."""
        idx = self.add_tab(activate=True, title=title)
        tab = self._tabs[idx]
        tab.pdf_dpi = dpi
        tab.pdf_doc = doc
        tab.pdf_page_index = 0
        if not self._render_pdf_page():
            self.close_tab(idx)
            return -1
        self.fit_to_window()
        self.refresh_tab_label(idx)
        return idx

    def load_file(self, path: str) -> bool:
        """Load `path` into the currently-active tab."""
        if self._active is None:
            # Create a tab implicitly
            self.add_tab(file_path=path, activate=True)
        else:
            self._active.file_path = path
        ok = self._load_pdf(path) if path.lower().endswith(".pdf") else self._load_image(path)
        if ok:
            self.fit_to_window()
            if self._active is not None:
                self.refresh_tab_label(self._active_idx)
        return ok

    def _load_image(self, path: str) -> bool:
        px = QPixmap(path)
        if px.isNull():
            return False
        if self._pdf_doc is not None:
            self._pdf_doc.close()
            self._pdf_doc = None
        self._pixmap = px
        return True

    def _load_pdf(self, path: str) -> bool:
        try:
            doc = fitz.open(path)
        except Exception:
            return False
        if self._pdf_doc is not None:
            self._pdf_doc.close()
        self._pdf_doc = doc
        self._pdf_page_index = 0
        return self._render_pdf_page()

    def _render_pdf_page(self) -> bool:
        if self._pdf_doc is None:
            return False
        page = self._pdf_doc[self._pdf_page_index]
        mat = fitz.Matrix(self._pdf_dpi / 72, self._pdf_dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        qimg = QImage.fromData(pix.tobytes("png"))
        if qimg.isNull():
            return False
        self._pixmap = QPixmap.fromImage(qimg)
        return True

    def go_to_page(self, index: int):
        if self._pdf_doc is None:
            return
        clamped = max(0, min(index, len(self._pdf_doc) - 1))
        if clamped == self._pdf_page_index:
            return
        # Commit any in-progress edit and drop drag state that refers to the
        # current page's objects before switching to the new page's state.
        self._cancel_transient_interactions()
        self._pdf_page_index = clamped
        if self._render_pdf_page():
            if self._active is not None:
                self.refresh_tab_label(self._active_idx)
            # The active page's annotations / scale / origin / legend all changed;
            # state_restored prompts the window to resync its panels.
            self.state_restored.emit()
            self.update()

    # ------------------------------------------------------------------
    # View helpers
    # ------------------------------------------------------------------

    def fit_to_window(self):
        if self._pixmap is None:
            return
        iw, ih = self._pixmap.width(), self._pixmap.height()
        if iw == 0 or ih == 0:
            return
        w = self._canvas_width() or 800
        h = self._canvas_height() or 600
        self._zoom = min(w / iw, h / ih) * 0.95
        self._pan  = QPointF(iw / 2, ih / 2)
        self.zoom_changed.emit(self._zoom)
        self.update()

    def set_zoom(self, zoom: float):
        self._zoom = max(0.05, min(20.0, zoom))
        self.zoom_changed.emit(self._zoom)
        self.update()

    def grab_canvas(self) -> QPixmap:
        """Render the current canvas (image + annotations + contours + legend,
        excluding the tab bar) to a pixmap — used for image export."""
        top = self._canvas_top()
        return self.grab(QRect(0, top, self.width(), self.height() - top))

    def _update_cursor_for_pos(self, screen_pos: Optional[QPointF] = None):
        """Set cursor based on tool and what is under screen_pos."""
        if self.current_tool == Tool.ZOOM_RECT:
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        if self.current_tool == Tool.SELECT:
            if self._panning or self._vtx_drag_active or self._sel_drag_active:
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
            if self._box_sel_start is not None:
                self.setCursor(Qt.CursorShape.CrossCursor)
                return
            if screen_pos is not None:
                for i in self._selection:
                    obj = self.objects[i]
                    if obj.kind == "point":
                        continue
                    for vx, vy in obj.points:
                        sp = self._img_to_screen(QPointF(vx, vy))
                        if math.hypot(sp.x() - screen_pos.x(), sp.y() - screen_pos.y()) <= _HIT_R:
                            self.setCursor(Qt.CursorShape.PointingHandCursor)
                            return
                if self._hit_object(screen_pos) >= 0:
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
                    return
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        if self.current_tool != Tool.PAN:
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        if self._panning or self._vtx_drag_active or self._sel_drag_active:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if screen_pos is not None:
            # Vertex handle on a selected object?
            for i in self._selection:
                obj = self.objects[i]
                if obj.kind == "point":
                    continue
                for vx, vy in obj.points:
                    sp = self._img_to_screen(QPointF(vx, vy))
                    if math.hypot(sp.x() - screen_pos.x(), sp.y() - screen_pos.y()) <= _HIT_R:
                        self.setCursor(Qt.CursorShape.PointingHandCursor)
                        return
            # Hovering over any object?
            if self._hit_object(screen_pos) >= 0:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                return
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        top = self._canvas_top()
        canvas_rect = QRectF(0, top, self.width(), max(0, self.height() - top))
        # The document sits on a mat, so the edge of the page stays visible
        # even when the page itself is white.
        painter.fillRect(canvas_rect, QColor(T.mat()))

        if self._pixmap is None:
            # Not a blank rectangle: one tertiary line saying what appears
            # here and which action fills it.
            painter.setPen(QColor(T.ink_hex(T.INK_TERTIARY)))
            if self._active is None:
                msg = ("No document open\n"
                       "Open an image or PDF (Ctrl+O) to start measuring")
            else:
                msg = "Loading…"
            painter.drawText(canvas_rect, Qt.AlignmentFlag.AlignCenter, msg)
            return

        # Clip drawing to the canvas area so nothing bleeds under the tab bar.
        painter.save()
        painter.setClipRect(canvas_rect)

        iw, ih = self._pixmap.width(), self._pixmap.height()
        cx, cy = self._canvas_center()
        x0 = cx - self._pan.x() * self._zoom
        y0 = cy - self._pan.y() * self._zoom
        dest = QRectF(x0, y0, iw * self._zoom, ih * self._zoom)
        painter.drawPixmap(dest, self._pixmap, QRectF(self._pixmap.rect()))

        self._paint_origin(painter)
        if self._show_objects:
            self._paint_contours(painter)
            self._paint_objects(painter)
        self._paint_temp(painter)
        self._paint_zoom_rect(painter)
        self._paint_box_select(painter)

        if self._show_objects:
            self._paint_legend(painter)

        painter.restore()

    def _paint_origin(self, painter: QPainter):
        sp = self._img_to_screen(QPointF(self.origin.x, self.origin.y))
        painter.setPen(QPen(_DATUM_COLOR, 2))
        x, y = int(sp.x()), int(sp.y())
        painter.drawLine(x - 12, y, x + 12, y)
        painter.drawLine(x, y - 12, x, y + 12)

    def _obj_pen(self, obj: DiagramObject, selected: bool) -> QPen:
        """Stroke pen for a line-based object, honoring its color, line width,
        and line style (selection overrides the color)."""
        color = _SEL_COLOR if selected else (
            QColor(obj.color) if obj.color else _KIND_COLOR.get(obj.kind, _LABEL_COLOR)
        )
        width = obj.line_width if obj.line_width and obj.line_width > 0 else 2.0
        pen = QPen(color, width)
        pen.setStyle(_PEN_STYLES.get(obj.line_style, Qt.PenStyle.SolidLine))
        return pen

    def _paint_objects(self, painter: QPainter):
        for i, obj in enumerate(self.objects):
            selected = i in self._selection

            if obj.kind == "point":
                self._paint_point(painter, obj, i, selected)
            elif obj.kind == "distance":
                self._paint_distance(painter, obj, selected)
            elif obj.kind == "angle":
                self._paint_angle(painter, obj, selected)
            elif obj.kind == "polygon":
                self._paint_polygon(painter, obj, selected)
            elif obj.kind == "polyline":
                self._paint_polyline(painter, obj, selected)
            elif obj.kind == "ellipse":
                self._paint_ellipse(painter, obj, selected)
            elif obj.kind == "textbox":
                self._paint_textbox(painter, obj, selected)
            elif obj.kind in ("polyline_contour", "point_contour"):
                self._paint_contour_skeleton(painter, obj, selected)

            if selected and obj.kind not in ("point", "point_contour"):
                self._paint_vertex_handles(painter, obj.points)

    def _label_color(self, obj: DiagramObject, selected: bool) -> QColor:
        """Colour for an object's on-canvas text label: the selection colour when
        selected, otherwise the object's own colour (falling back to the kind
        default, then a neutral label colour)."""
        if selected:
            return _SEL_COLOR
        if obj.color:
            return QColor(obj.color)
        return _KIND_COLOR.get(obj.kind, _LABEL_COLOR)

    def _paint_point(self, painter, obj, idx, selected):
        if not obj.points:
            return
        sp = self._img_to_screen(QPointF(*obj.points[0]))
        base = QColor(obj.color) if obj.color else _KIND_COLOR["point"]
        fill_color = _SEL_COLOR if selected else base
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(fill_color))
        painter.drawEllipse(sp, 5.0, 5.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if not self._show_labels:
            return
        label = obj.name or f"P{idx + 1}"
        painter.setPen(self._label_color(obj, selected))
        painter.drawText(QPointF(sp.x() + 9, sp.y() - 7), label)
        wx, wy = self.img_to_world(QPointF(*obj.points[0]))
        painter.drawText(QPointF(sp.x() + 9, sp.y() + 6), f"({wx:.2f}, {wy:.2f})")

    def _paint_obj_label(self, painter, anchor: QPointF, obj, fallback: str,
                         selected: bool = False):
        """Draw an object's name + all its measurements near `anchor` (baseline
        of the first line). A single measurement reads 'Name: value'; multiple
        measurements are listed one per line under the name. The text is drawn in
        the object's own colour (red when selected)."""
        if not self._show_labels:
            return
        name = obj.name or fallback
        ms = obj.measurements()
        painter.setPen(self._label_color(obj, selected))
        if len(ms) <= 1:
            text = f"{name}: {ms[0][1]}" if ms else name
            painter.drawText(anchor, text)
            return
        line_h = painter.fontMetrics().height()
        painter.drawText(anchor, name)
        for i, (lbl, val) in enumerate(ms, start=1):
            painter.drawText(QPointF(anchor.x(), anchor.y() + i * line_h),
                             f"{lbl}: {val}")

    def _paint_distance(self, painter, obj, selected):
        if len(obj.points) < 2:
            return
        sp0 = self._img_to_screen(QPointF(*obj.points[0]))
        sp1 = self._img_to_screen(QPointF(*obj.points[1]))
        painter.setPen(self._obj_pen(obj, selected))
        painter.drawLine(sp0, sp1)
        mid = QPointF((sp0.x() + sp1.x()) / 2, (sp0.y() + sp1.y()) / 2)
        self._paint_obj_label(painter, QPointF(mid.x() + 5, mid.y() - 5), obj, "Line", selected)

    def _paint_angle(self, painter, obj, selected):
        if len(obj.points) < 3:
            return
        sp = [self._img_to_screen(QPointF(*p)) for p in obj.points]
        painter.setPen(self._obj_pen(obj, selected))
        painter.drawLine(sp[0], sp[1])
        painter.drawLine(sp[2], sp[1])
        self._paint_obj_label(painter, QPointF(sp[1].x() + 5, sp[1].y() - 5), obj, "Angle", selected)

    def _paint_polygon(self, painter, obj, selected):
        if len(obj.points) < 3:
            return
        pen = self._obj_pen(obj, selected)
        sps = [self._img_to_screen(QPointF(*p)) for p in obj.points]
        fill = QColor(pen.color())
        fill.setAlpha(40)
        painter.setBrush(QBrush(fill))
        painter.setPen(pen)
        painter.drawPolygon(QPolygonF(sps))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cx = sum(s.x() for s in sps) / len(sps)
        cy = sum(s.y() for s in sps) / len(sps)
        self._paint_obj_label(painter, QPointF(cx + 5, cy), obj, "Polygon", selected)

    def _paint_polyline(self, painter, obj, selected):
        if len(obj.points) < 2:
            return
        sps = [self._img_to_screen(QPointF(*p)) for p in obj.points]
        painter.setPen(self._obj_pen(obj, selected))
        for i in range(len(sps) - 1):
            painter.drawLine(sps[i], sps[i + 1])
        mid = sps[len(sps) // 2]
        self._paint_obj_label(painter, QPointF(mid.x() + 5, mid.y() - 5), obj, "Polyline", selected)

    def _paint_ellipse(self, painter, obj, selected):
        if len(obj.points) < 2:
            return
        sp0 = self._img_to_screen(QPointF(*obj.points[0]))
        sp1 = self._img_to_screen(QPointF(*obj.points[1]))
        rect = QRectF(sp0, sp1).normalized()
        # thin dashed bounding box
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_SEL_COLOR if selected else _BBOX_COLOR, 1, Qt.PenStyle.DashLine))
        painter.drawRect(rect)
        # the ellipse itself
        painter.setPen(self._obj_pen(obj, selected))
        painter.drawEllipse(rect)
        self._paint_obj_label(painter, QPointF(rect.center().x() + 5, rect.top() - 5),
                              obj, "Ellipse", selected)

    def _paint_textbox(self, painter, obj, selected):
        if len(obj.points) < 2:
            return
        sp0 = self._img_to_screen(QPointF(*obj.points[0]))
        sp1 = self._img_to_screen(QPointF(*obj.points[1]))
        rect = QRectF(sp0, sp1).normalized()

        # fill (optional)
        if obj.fill_color:
            painter.setBrush(QBrush(QColor(obj.fill_color)))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self._obj_pen(obj, selected))
        painter.drawRect(rect)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # text (hidden while this box is being edited in place)
        editing = (
            self._inline_editor is not None
            and 0 <= self._inline_obj_idx < len(self.objects)
            and self.objects[self._inline_obj_idx] is obj
        )
        if obj.text and not editing:
            # save/restore: the zoom-scaled font must not leak into whatever is
            # painted next (later object labels, the legend).
            painter.save()
            painter.setFont(self._textbox_font(obj, painter.font()))
            painter.setPen(QColor(obj.font_color) if obj.font_color else QColor(T.MARK_TEXTBOX))
            align = (_H_ALIGN.get(obj.h_align, Qt.AlignmentFlag.AlignLeft)
                     | _V_ALIGN.get(obj.v_align, Qt.AlignmentFlag.AlignTop))
            painter.drawText(rect.adjusted(4, 2, -4, -2),
                             int(align | Qt.TextFlag.TextWordWrap),
                             obj.text)
            painter.restore()

    def _textbox_font(self, obj: DiagramObject, base: QFont) -> QFont:
        """The text box's font at the current zoom. Its size is in points on
        the page (as in a PDF editor), so it scales with the page: one page
        point is dpi / 72 image pixels."""
        font = QFont(base)
        if obj.font_family:
            font.setFamily(obj.font_family)
        size = obj.font_size if obj.font_size and obj.font_size > 0 else 12
        screen_px = size * self._pdf_dpi / 72.0 * self._zoom
        font.setPointSizeF(max(1.0, screen_px * 72.0 / max(1, self.logicalDpiY())))
        font.setBold(obj.bold)
        font.setItalic(obj.italic)
        font.setUnderline(obj.underline)
        return font

    def _paint_contour_skeleton(self, painter, obj, selected):
        """Thin dashed defining geometry (polyline or single point) of a contour
        object, so it is visible and selectable. The contour rings themselves are
        drawn separately (merged) in _paint_contours. Hidden along with the labels
        unless the object is selected, so the selection stays visible."""
        if not obj.points:
            return
        if not self._show_labels and not selected:
            return
        sps = [self._img_to_screen(QPointF(*p)) for p in obj.points]
        color = _SEL_COLOR if selected else _SKELETON_COLOR
        if obj.kind == "point_contour":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(sps[0], 4.0, 4.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)
        else:
            painter.setPen(QPen(color, 1, Qt.PenStyle.DashLine))
            for i in range(len(sps) - 1):
                painter.drawLine(sps[i], sps[i + 1])
        if self._show_labels and obj.name:
            painter.setPen(color)
            painter.drawText(QPointF(sps[0].x() + 7, sps[0].y() - 6), obj.name)

    def _paint_vertex_handles(self, painter: QPainter, points: list):
        painter.setPen(QPen(_HANDLE_COLOR, 1))
        painter.setBrush(QBrush(_HANDLE_COLOR))
        for px, py in points:
            sp = self._img_to_screen(QPointF(px, py))
            painter.drawEllipse(sp, 6.0, 6.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _paint_temp(self, painter: QPainter):
        if not self._temp:
            return
        pts_screen = [self._img_to_screen(QPointF(p.x, p.y)) for p in self._temp]

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(_PREVIEW_COLOR))
        for sp in pts_screen:
            painter.drawEllipse(sp, 5.0, 5.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        tool    = self.current_tool
        preview = self._preview_screen_pt()

        if tool == Tool.ADD_LINE:
            if len(pts_screen) == 1 and preview:
                painter.setPen(QPen(_PREVIEW_COLOR, 1, Qt.PenStyle.DashLine))
                painter.drawLine(pts_screen[0], preview)

        elif tool == Tool.ADD_ANGLE:
            painter.setPen(QPen(_KIND_COLOR["angle"], 2))
            for i in range(len(pts_screen) - 1):
                painter.drawLine(pts_screen[i], pts_screen[i + 1])
            if preview:
                painter.setPen(QPen(_KIND_COLOR["angle"], 1, Qt.PenStyle.DashLine))
                painter.drawLine(pts_screen[-1], preview)

        elif tool in (Tool.SET_SCALE_DISTANCE, Tool.SET_SCALE_COORDS):
            if len(pts_screen) == 2:
                painter.setPen(QPen(_DATUM_COLOR, 2, Qt.PenStyle.DashLine))
                painter.drawLine(pts_screen[0], pts_screen[1])
            elif len(pts_screen) == 1 and preview:
                painter.setPen(QPen(_DATUM_COLOR, 1, Qt.PenStyle.DashLine))
                painter.drawLine(pts_screen[0], preview)

        elif tool == Tool.ADD_POLYGON:
            all_pts = pts_screen + ([preview] if preview else [])
            painter.setPen(QPen(_KIND_COLOR["polygon"], 2))
            fill = QColor(_KIND_COLOR["polygon"])
            fill.setAlpha(30)
            painter.setBrush(QBrush(fill))
            if len(all_pts) >= 2:
                painter.drawPolygon(QPolygonF(all_pts))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(_KIND_COLOR["polygon"])
            for i, sp in enumerate(pts_screen):
                painter.drawText(QPointF(sp.x() + 7, sp.y() - 4), str(i + 1))

        elif tool in (Tool.ADD_POLYLINE, Tool.ADD_POLYLINE_CONTOUR):
            painter.setPen(QPen(_KIND_COLOR["polyline"], 2))
            for i in range(len(pts_screen) - 1):
                painter.drawLine(pts_screen[i], pts_screen[i + 1])
            if preview and pts_screen:
                painter.setPen(QPen(_PREVIEW_COLOR, 1, Qt.PenStyle.DashLine))
                painter.drawLine(pts_screen[-1], preview)
            painter.setPen(_KIND_COLOR["polyline"])
            for i, sp in enumerate(pts_screen):
                painter.drawText(QPointF(sp.x() + 7, sp.y() - 4), str(i + 1))

        elif tool in (Tool.ADD_ELLIPSE, Tool.ADD_TEXTBOX):
            if len(pts_screen) == 1 and preview:
                rect = QRectF(pts_screen[0], preview).normalized()
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(_BBOX_COLOR, 1, Qt.PenStyle.DashLine))
                painter.drawRect(rect)
                if tool == Tool.ADD_ELLIPSE:
                    painter.setPen(QPen(_KIND_COLOR["ellipse"], 2))
                    painter.drawEllipse(rect)

    def _paint_zoom_rect(self, painter: QPainter):
        if self.current_tool != Tool.ZOOM_RECT or self._zoom_rect_start is None:
            return
        if self._mouse_img is None:
            return
        s0 = self._zoom_rect_start
        s1 = self._img_to_screen(self._mouse_img)
        rect = QRectF(s0, s1).normalized()
        painter.setPen(QPen(_PREVIEW_COLOR, 1, Qt.PenStyle.DashLine))
        fill = QColor(_PREVIEW_COLOR)
        fill.setAlpha(20)
        painter.setBrush(QBrush(fill))
        painter.drawRect(rect)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _paint_box_select(self, painter: QPainter):
        if self.current_tool != Tool.SELECT or self._box_sel_start is None:
            return
        if self._mouse_img is None:
            return
        s0 = self._box_sel_start
        s1 = self._img_to_screen(self._mouse_img)
        rect = QRectF(s0, s1).normalized()
        painter.setPen(QPen(_SEL_COLOR, 1, Qt.PenStyle.DashLine))
        fill = QColor(_SEL_COLOR)
        fill.setAlpha(35)
        painter.setBrush(QBrush(fill))
        painter.drawRect(rect)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    # ------------------------------------------------------------------
    # Contours (merged buffers) + legend
    # ------------------------------------------------------------------

    def _contour_signature(self):
        """Cheap signature of all contour geometry + levels + scale; used to
        avoid recomputing shapely unions on every repaint."""
        sig = [round(self.scale_info.scale_factor, 9)]
        for obj in self.objects:
            if not obj.is_contour:
                continue
            sig.append((
                obj.kind,
                tuple((round(x, 3), round(y, 3)) for x, y in obj.points),
                tuple((str(l.get("reference", "")),
                       round(float(l.get("distance", 0) or 0), 6),
                       round(float(l.get("width", 0) or 0), 3),
                       l.get("color", "")) for l in obj.levels),
            ))
        return tuple(sig)

    def _contour_groups(self) -> list:
        sig = self._contour_signature()
        if sig != self._contour_cache_sig:
            contour_objs = [o for o in self.objects if o.is_contour]
            self._contour_cache = contours.build_contour_groups(
                contour_objs, self.scale_info.scale_factor,
                default_color=T.contour(0),
            )
            self._contour_cache_sig = sig
        return self._contour_cache

    def _draw_ring(self, painter: QPainter, ring_pts: list):
        poly = QPolygonF([self._img_to_screen(QPointF(x, y)) for x, y in ring_pts])
        painter.drawPolyline(poly)

    def _paint_contours(self, painter: QPainter):
        groups = self._contour_groups()
        if not groups:
            return
        painter.setBrush(Qt.BrushStyle.NoBrush)   # no fill, line only
        for g in groups:
            painter.setPen(QPen(QColor(g["color"]), g.get("width", 2)))
            for exterior, interiors in g["polygons"]:
                self._draw_ring(painter, exterior)
                for hole in interiors:
                    self._draw_ring(painter, hole)

    def _paint_legend(self, painter: QPainter):
        self._legend_rect = None
        if self._active is None or not self.legend_visible:
            return
        groups = self._contour_groups()
        if not groups:
            return

        painter.save()
        base_font = painter.font()
        title_font = QFont(base_font)
        title_font.setBold(True)
        fm = QFontMetrics(base_font)
        tfm = QFontMetrics(title_font)
        line_h = fm.height() + 4
        swatch_w = 26
        gap = 6
        pad = 8

        title = self.legend_title or "Legend"
        max_text = tfm.horizontalAdvance(title)
        for g in groups:
            max_text = max(max_text, swatch_w + gap + fm.horizontalAdvance(g["reference"]))

        box_w = pad * 2 + max_text
        box_h = pad * 2 + line_h * (len(groups) + 1)
        margin = 12
        x = self.width() - box_w - margin
        y = self._canvas_top() + margin
        rect = QRectF(x, y, box_w, box_h)
        self._legend_rect = rect

        # The legend is app chrome sitting over the document, so it takes the
        # canvas and the ink ladder rather than a colour of its own. Only the
        # swatches carry colour - they are the data.
        bg = QColor(T.CANVAS)
        bg.setAlpha(235)
        painter.setPen(QPen(QColor(T.ink_hex(T.SURFACE_BORDER_STRONG)), 1))
        painter.setBrush(QBrush(bg))
        painter.drawRect(rect)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        content_x = x + pad
        painter.setFont(title_font)
        painter.setPen(QColor(T.INK))
        painter.drawText(QPointF(content_x, y + pad + tfm.ascent()), title)

        painter.setFont(base_font)
        for idx, g in enumerate(groups, start=1):
            line_top = y + pad + line_h * idx
            # Swatch reflects the contour's width, clamped so a thick line
            # doesn't overflow the legend row.
            sw = max(1.0, min(float(g.get("width", 3) or 3), float(fm.height())))
            painter.setPen(QPen(QColor(g["color"]), sw))
            sw_y = line_top + fm.height() / 2.0
            painter.drawLine(QPointF(content_x, sw_y),
                             QPointF(content_x + swatch_w, sw_y))
            painter.setPen(QColor(T.INK))
            painter.drawText(QPointF(content_x + swatch_w + gap, line_top + fm.ascent()),
                             g["reference"])
        painter.restore()

    def _preview_screen_pt(self) -> Optional[QPointF]:
        if self._mouse_img is None or not self._temp:
            return None
        return self._img_to_screen(self._apply_snap(self._mouse_img))

    def _shift_pressed(self) -> bool:
        return bool(
            QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
        )

    def _apply_snap(self, img_pos: QPointF) -> QPointF:
        if self._shift_pressed() and self._temp:
            base = QPointF(self._temp[-1].x, self._temp[-1].y)
            if self.current_tool == Tool.ADD_ELLIPSE:
                return _square_box(base, img_pos)
            return _snap_cardinal(base, img_pos)
        return img_pos

    # ------------------------------------------------------------------
    # Tool selection
    # ------------------------------------------------------------------

    def set_tool(self, tool: Tool):
        self._finish_inline_edit()
        self._vtx_drag_active = False
        self._vtx_drag_obj    = -1
        self._vtx_drag_vtx    = -1
        self._sel_drag_active = False
        self._sel_press_obj   = -1
        self._zoom_rect_start = None
        self._box_sel_start   = None
        self._box_sel_base    = set()
        self.current_tool = tool
        self._temp.clear()
        self._update_cursor_for_pos()
        self.update()

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if self._active is None:
            return
        self._finish_inline_edit()
        self._nudge_burst_active = False
        pos = QPointF(event.position())
        btn = event.button()

        if btn == Qt.MouseButton.MiddleButton:
            self._start_pan(pos)
            return

        if btn == Qt.MouseButton.LeftButton:
            if self.current_tool == Tool.ZOOM_RECT:
                self._zoom_rect_start = pos
                return

            if self.current_tool in (Tool.PAN, Tool.SELECT):
                # Vertex drag on selected object?
                vtx_obj, vtx_idx = self._hit_selected_vertex(pos)
                if vtx_obj >= 0:
                    self._begin_vtx_drag(vtx_obj, vtx_idx, pos)
                    return
                hit = self._hit_object(pos)
                if hit >= 0:
                    self._sel_press_obj = hit
                    self._sel_press_pos = pos
                elif self.current_tool == Tool.SELECT:
                    # Empty space → start box selection (no left-drag pan in SELECT)
                    self._box_sel_start = pos
                    self._box_sel_additive = bool(
                        event.modifiers() & Qt.KeyboardModifier.ControlModifier
                    )
                    self._box_sel_base = (
                        set(self._selection) if self._box_sel_additive else set()
                    )
                else:
                    self._start_pan(pos)
            else:
                self._left_click(pos)

        elif btn == Qt.MouseButton.RightButton:
            self._right_click(pos)

    def mouseMoveEvent(self, event):
        pos = QPointF(event.position())

        if self._pixmap is not None:
            self._mouse_img = self._screen_to_img(pos)
            wx, wy = self.img_to_world(self._mouse_img)
            self.mouse_world_pos.emit(wx, wy)
            self._emit_live_measure()

        if self._panning:
            delta = pos - self._pan_start_screen
            if math.hypot(delta.x(), delta.y()) > _DRAG_THRESH:
                self._pan_moved = True
            self._pan = QPointF(
                self._pan_start_pan.x() - delta.x() / self._zoom,
                self._pan_start_pan.y() - delta.y() / self._zoom,
            )
            self.update()
            return

        if self._vtx_drag_active:
            img_pos = self._screen_to_img(pos)
            dx = img_pos.x() - self._vtx_drag_start_img.x()
            dy = img_pos.y() - self._vtx_drag_start_img.y()
            obj = self.objects[self._vtx_drag_obj]
            ox, oy = self._vtx_drag_start_pts[self._vtx_drag_vtx]
            new_pt = QPointF(ox + dx, oy + dy)
            # Shift while resizing an ellipse keeps it a circle: constrain the
            # dragged corner square relative to the (fixed) opposite corner.
            if (obj.kind == "ellipse" and self._shift_pressed()
                    and len(self._vtx_drag_start_pts) == 2):
                fx, fy = self._vtx_drag_start_pts[1 - self._vtx_drag_vtx]
                new_pt = _square_box(QPointF(fx, fy), new_pt)
            obj.points[self._vtx_drag_vtx] = [new_pt.x(), new_pt.y()]
            self._recalculate_object(obj)
            self.update()
            return

        if self._sel_press_obj >= 0 and self._sel_press_pos is not None:
            delta = pos - self._sel_press_pos
            if not self._sel_drag_active and math.hypot(delta.x(), delta.y()) > _DRAG_THRESH:
                if self._sel_press_obj not in self._selection:
                    self._selection = {self._sel_press_obj}
                    self.selection_changed.emit(sorted(self._selection))
                self._sel_drag_snap = self._snapshot()
                self._sel_drag_start = self._screen_to_img(self._sel_press_pos)
                self._sel_drag_start_pts = {
                    i: [list(p) for p in self.objects[i].points]
                    for i in self._selection
                }
                self._sel_drag_active = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)

            if self._sel_drag_active:
                img_pos = self._screen_to_img(pos)
                dx = img_pos.x() - self._sel_drag_start.x()
                dy = img_pos.y() - self._sel_drag_start.y()
                for i in self._selection:
                    orig = self._sel_drag_start_pts[i]
                    self.objects[i].points = [[x + dx, y + dy] for x, y in orig]
                    if self.objects[i].kind != "point":
                        self._recalculate_object(self.objects[i])
                self.update()
                return

        if self.current_tool == Tool.ZOOM_RECT and self._zoom_rect_start is not None:
            self.update()
            return

        if self.current_tool == Tool.SELECT and self._box_sel_start is not None:
            self.update()
            return

        # Update the hover cursor. Only repaint when there is a live drawing
        # preview to refresh — idle hover (no in-progress object) doesn't change
        # the canvas, so repainting the whole image every mouse move is wasteful.
        self._update_cursor_for_pos(pos)
        if self._temp:
            self.update()

    def mouseReleaseEvent(self, event):
        btn = event.button()

        if self._panning and btn in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            self._panning = False
            if not self._pan_moved:
                self._selection.clear()
                self.selection_changed.emit([])
            self._update_cursor_for_pos(QPointF(event.position()))
            return

        if self._vtx_drag_active and btn == Qt.MouseButton.LeftButton:
            self._record_undo(self._vtx_drag_snap)
            self._recalculate_object(self.objects[self._vtx_drag_obj])
            self._vtx_drag_active = False
            self._vtx_drag_vtx    = -1
            self._vtx_drag_start_pts = []
            self.objects_changed.emit()
            self._update_cursor_for_pos(QPointF(event.position()))
            self.update()
            return

        if btn == Qt.MouseButton.LeftButton and self.current_tool in (Tool.PAN, Tool.SELECT):
            if self._sel_drag_active:
                self._record_undo(self._sel_drag_snap)
                self._sel_drag_active = False
                self._sel_press_obj   = -1
                self._sel_press_pos   = None
                self.objects_changed.emit()
                self._update_cursor_for_pos(QPointF(event.position()))
                self.update()
            elif self._sel_press_obj >= 0:
                self._handle_selection_click(self._sel_press_obj, event.modifiers())
                self._sel_press_obj = -1
                self._sel_press_pos = None
            elif self.current_tool == Tool.SELECT and self._box_sel_start is not None:
                self._finish_box_select(QPointF(event.position()))

        if btn == Qt.MouseButton.LeftButton and self.current_tool == Tool.ZOOM_RECT:
            self._finish_zoom_rect(QPointF(event.position()))

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.fit_to_window()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        tool = self.current_tool
        if tool in (Tool.PAN, Tool.SELECT) and self._show_objects:
            pos = QPointF(event.position())
            # Double-click the on-canvas legend to edit its title.
            if self._legend_rect is not None and self._legend_rect.contains(pos):
                self.edit_legend_title()
                return
            # Double-click a text box to edit its text in place.
            hit = self._hit_object(pos)
            if hit >= 0 and self.objects[hit].kind == "textbox":
                self._begin_inline_text_edit(hit)
                return
        # The first click of the double-click already added a point via mousePressEvent.
        # Finish with that point included.
        if tool == Tool.ADD_POLYGON and len(self._temp) >= 3:
            self._finish_polygon()
        elif tool == Tool.ADD_POLYLINE and len(self._temp) >= 2:
            self._finish_polyline()
        elif tool == Tool.ADD_POLYLINE_CONTOUR and len(self._temp) >= 2:
            self._finish_polyline_contour()

    def wheelEvent(self, event):
        if self._active is None:
            return
        self._finish_inline_edit()
        pos = QPointF(event.position())
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        mouse_img = self._screen_to_img(pos)
        self._zoom = max(0.05, min(20.0, self._zoom * factor))
        cx, cy = self._canvas_center()
        self._pan = QPointF(
            mouse_img.x() - (pos.x() - cx) / self._zoom,
            mouse_img.y() - (pos.y() - cy) / self._zoom,
        )
        self.zoom_changed.emit(self._zoom)
        self.update()

    def keyPressEvent(self, event):
        key  = event.key()
        mods = event.modifiers()

        if key == Qt.Key.Key_Escape:
            if self._vtx_drag_active:
                self._cancel_vtx_drag()
            elif self._box_sel_start is not None:
                self._box_sel_start = None
                self._box_sel_base = set()
                self.update()
            elif self._selection:
                self._selection.clear()
                self.selection_changed.emit([])
                self.update()
            elif self.current_tool != Tool.PAN:
                self._temp.clear()
                self.tool_change_requested.emit(Tool.PAN)
                self.set_tool(Tool.PAN)
            else:
                self._temp.clear()
                self.update()

        # Arrow-key nudge of the selection (no menu shortcut owns these). Delete,
        # cut/copy/paste and select-all are handled by the Edit-menu shortcuts,
        # which intercept those keys before they reach this widget.
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down) \
                and self.current_tool in (Tool.PAN, Tool.SELECT) and self._selection:
            step = 10.0 if (mods & Qt.KeyboardModifier.ShiftModifier) else 1.0
            dx = -step if key == Qt.Key.Key_Left else step if key == Qt.Key.Key_Right else 0.0
            dy = -step if key == Qt.Key.Key_Up   else step if key == Qt.Key.Key_Down  else 0.0
            self._nudge_selection(dx, dy, autorepeat=event.isAutoRepeat())

        elif key == Qt.Key.Key_Shift:
            self.update()

        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Shift:
            self.update()
        elif event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right,
                              Qt.Key.Key_Up, Qt.Key.Key_Down):
            if not event.isAutoRepeat():
                self._nudge_burst_active = False
        else:
            super().keyReleaseEvent(event)

    # ------------------------------------------------------------------
    # Pan helper
    # ------------------------------------------------------------------

    def _start_pan(self, pos: QPointF):
        self._panning = True
        self._pan_moved = False
        self._pan_start_screen = pos
        self._pan_start_pan    = QPointF(self._pan)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def _handle_selection_click(self, idx: int, mods):
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        if ctrl:
            if idx in self._selection:
                self._selection.discard(idx)
            else:
                self._selection.add(idx)
        else:
            self._selection = {idx}
        self.selection_changed.emit(sorted(self._selection))
        self.update()

    def set_selection(self, indices: list):
        self._selection = set(indices)
        self.update()

    def select_all(self):
        self._selection = set(range(len(self.objects)))
        self.selection_changed.emit(sorted(self._selection))
        self.update()

    # ------------------------------------------------------------------
    # Clipboard
    # ------------------------------------------------------------------

    def copy_selection(self):
        if not self._selection:
            return
        self._clipboard = [deepcopy(self.objects[i]) for i in sorted(self._selection)]

    def cut_selection(self):
        if not self._selection:
            return
        self.copy_selection()
        self._push_undo()
        for i in sorted(self._selection, reverse=True):
            del self.objects[i]
        self._selection.clear()
        self.selection_changed.emit([])
        self.objects_changed.emit()
        self.update()

    def paste(self, screen_pos: Optional[QPointF] = None):
        if not self._clipboard:
            return
        all_pts = [p for obj in self._clipboard for p in obj.points]
        if screen_pos is not None and all_pts:
            img_pos = self._screen_to_img(screen_pos)
            cx = sum(p[0] for p in all_pts) / len(all_pts)
            cy = sum(p[1] for p in all_pts) / len(all_pts)
            off_x = img_pos.x() - cx
            off_y = img_pos.y() - cy
        else:
            off_x = off_y = 0.0

        self._push_undo()
        base = len(self.objects)
        for obj in self._clipboard:
            new_obj = deepcopy(obj)
            new_obj.points = [[x + off_x, y + off_y] for x, y in new_obj.points]
            new_obj.name = self._copy_name(new_obj.name)
            new_obj.timestamp = datetime.now().strftime("%H:%M:%S")
            new_obj.renew_uid()
            self.objects.append(new_obj)

        self._selection = set(range(base, len(self.objects)))
        self.selection_changed.emit(sorted(self._selection))
        self.objects_changed.emit()
        self.update()

    @staticmethod
    def _copy_name(name: str) -> str:
        base = name if name else ""
        return f"{base} - Copy" if base else "Copy"

    def duplicate_selection(self):
        """Duplicate currently-selected objects at the same coordinates."""
        if not self._selection:
            return
        sel_sorted = sorted(self._selection)
        sources = [deepcopy(self.objects[i]) for i in sel_sorted]

        self._push_undo()
        base = len(self.objects)
        for obj in sources:
            new_obj = deepcopy(obj)
            new_obj.name = self._copy_name(new_obj.name)
            new_obj.timestamp = datetime.now().strftime("%H:%M:%S")
            new_obj.renew_uid()
            self.objects.append(new_obj)

        self._selection = set(range(base, len(self.objects)))
        self.selection_changed.emit(sorted(self._selection))
        self.objects_changed.emit()
        self.update()

    def _nudge_selection(self, dx: float, dy: float, autorepeat: bool = False):
        """Shift selected objects by (dx, dy) image pixels. One undo per burst."""
        if not self._selection or (dx == 0.0 and dy == 0.0):
            return
        if not self._nudge_burst_active:
            self._push_undo()
            self._nudge_burst_active = True
        for i in self._selection:
            obj = self.objects[i]
            obj.points = [[x + dx, y + dy] for x, y in obj.points]
            if obj.kind != "point":
                self._recalculate_object(obj)
        self.objects_changed.emit()
        self.update()

    # ------------------------------------------------------------------
    # Reordering
    # ------------------------------------------------------------------

    def move_selected_up(self):
        """Move each selected object one slot earlier in the list."""
        if not self._selection:
            return
        sel_sorted = sorted(self._selection)
        if sel_sorted[0] == 0:
            return
        self._push_undo()
        new_sel = set()
        for i in sel_sorted:
            self.objects[i - 1], self.objects[i] = self.objects[i], self.objects[i - 1]
            new_sel.add(i - 1)
        self._selection = new_sel
        self.selection_changed.emit(sorted(self._selection))
        self.objects_changed.emit()
        self.update()

    def move_selected_down(self):
        """Move each selected object one slot later in the list."""
        if not self._selection:
            return
        sel_sorted = sorted(self._selection, reverse=True)
        if sel_sorted[0] == len(self.objects) - 1:
            return
        self._push_undo()
        new_sel = set()
        for i in sel_sorted:
            self.objects[i + 1], self.objects[i] = self.objects[i], self.objects[i + 1]
            new_sel.add(i + 1)
        self._selection = new_sel
        self.selection_changed.emit(sorted(self._selection))
        self.objects_changed.emit()
        self.update()

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    def delete_selected(self):
        if not self._selection:
            return
        self._push_undo()
        for i in sorted(self._selection, reverse=True):
            del self.objects[i]
        self._selection.clear()
        self.selection_changed.emit([])
        self.objects_changed.emit()
        self.update()

    def clear_all_objects(self):
        if not self.objects:
            return
        self._push_undo()
        self.objects.clear()
        self._selection.clear()
        self.selection_changed.emit([])
        self.objects_changed.emit()
        self.update()

    # ------------------------------------------------------------------
    # Click handlers
    # ------------------------------------------------------------------

    def _left_click(self, screen_pos: QPointF):
        img_pos = self._screen_to_img(screen_pos)
        tool    = self.current_tool

        snapping_tools = {
            Tool.ADD_LINE, Tool.ADD_ANGLE, Tool.ADD_POLYGON, Tool.ADD_POLYLINE,
            Tool.ADD_POLYLINE_CONTOUR, Tool.ADD_ELLIPSE,
            Tool.SET_SCALE_DISTANCE, Tool.SET_SCALE_COORDS,
        }
        if self._shift_pressed() and self._temp and tool in snapping_tools:
            img_pos = self._apply_snap(img_pos)

        img_pt = Point(img_pos.x(), img_pos.y())

        if tool == Tool.SET_ORIGIN:
            dlg = SetOriginDialog(self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                wx, wy = dlg.values()
                self._push_undo()
                self.origin = img_pt
                self._origin_world = (wx, wy)
                self.origin_set.emit(img_pt)
                self.update()

        elif tool in (Tool.SET_SCALE_DISTANCE, Tool.SET_SCALE_COORDS):
            self._temp.append(img_pt)
            if len(self._temp) == 2:
                self._finish_scale()
            self.update()

        elif tool == Tool.ADD_POINT:
            result = self._ask_name_and_color("point")
            if result is None:
                return
            name, color, _lw, _ls = result
            self._push_undo()
            obj = DiagramObject(
                kind="point", name=name, color=color,
                points=[[img_pt.x, img_pt.y]],
            )
            self.objects.append(obj)
            self.objects_changed.emit()
            self.update()

        elif tool == Tool.ADD_POINT_CONTOUR:
            self._finish_point_contour(img_pt)

        elif tool == Tool.ADD_LINE:
            self._temp.append(img_pt)
            if len(self._temp) == 2:
                self._finish_distance()
            self.update()

        elif tool == Tool.ADD_ANGLE:
            self._temp.append(img_pt)
            if len(self._temp) == 3:
                self._finish_angle()
            self.update()

        elif tool == Tool.ADD_ELLIPSE:
            self._temp.append(img_pt)
            if len(self._temp) == 2:
                self._finish_ellipse()
            self.update()

        elif tool == Tool.ADD_TEXTBOX:
            self._temp.append(img_pt)
            if len(self._temp) == 2:
                self._finish_textbox()
            self.update()

        elif tool in (Tool.ADD_POLYGON, Tool.ADD_POLYLINE, Tool.ADD_POLYLINE_CONTOUR):
            self._temp.append(img_pt)
            self.update()

    def _right_click(self, screen_pos: QPointF):
        tool = self.current_tool

        if tool == Tool.PAN:
            self._show_pan_context_menu(screen_pos)
            return

        # Close polygon / finish polyline, or pop last temp point
        if tool == Tool.ADD_POLYGON and len(self._temp) >= 3:
            self._finish_polygon()
            return
        if tool == Tool.ADD_POLYLINE and len(self._temp) >= 2:
            self._finish_polyline()
            return
        if tool == Tool.ADD_POLYLINE_CONTOUR and len(self._temp) >= 2:
            self._finish_polyline_contour()
            return
        if self._temp:
            self._temp.pop()
            self.update()

    # ------------------------------------------------------------------
    # Zoom rect
    # ------------------------------------------------------------------

    def _finish_zoom_rect(self, end_screen: QPointF):
        if self._zoom_rect_start is None:
            return
        start = self._zoom_rect_start
        self._zoom_rect_start = None

        rect = QRectF(start, end_screen).normalized()
        if rect.width() < 4 or rect.height() < 4:
            self.update()
            return

        # Convert rect corners to image coords
        img_tl = self._screen_to_img(rect.topLeft())
        img_br = self._screen_to_img(rect.bottomRight())
        img_w  = abs(img_br.x() - img_tl.x())
        img_h  = abs(img_br.y() - img_tl.y())
        if img_w < 1 or img_h < 1:
            self.update()
            return

        # Zoom so the rect fills 95% of the canvas (the area below the tab bar)
        vw = self._canvas_width() or 800
        vh = self._canvas_height() or 600
        new_zoom = min(vw / img_w, vh / img_h) * 0.95
        new_zoom = max(0.05, min(20.0, new_zoom))

        # Pan so rect centre is at viewport centre
        cx_img = (img_tl.x() + img_br.x()) / 2
        cy_img = (img_tl.y() + img_br.y()) / 2
        self._zoom = new_zoom
        self._pan  = QPointF(cx_img, cy_img)
        self.zoom_changed.emit(self._zoom)
        self.update()

    # ------------------------------------------------------------------
    # Box select (SELECT tool)
    # ------------------------------------------------------------------

    def _finish_box_select(self, end_screen: QPointF):
        if self._box_sel_start is None:
            return
        start = self._box_sel_start
        self._box_sel_start = None

        rect_screen = QRectF(start, end_screen).normalized()
        # If the user merely clicked (no real drag), clear selection
        if rect_screen.width() < _DRAG_THRESH and rect_screen.height() < _DRAG_THRESH:
            if not self._box_sel_additive:
                self._selection = set()
                self.selection_changed.emit([])
            self._box_sel_base = set()
            self.update()
            return

        # Build the image-space rect for vertex containment test
        img_tl = self._screen_to_img(rect_screen.topLeft())
        img_br = self._screen_to_img(rect_screen.bottomRight())
        x_min, x_max = sorted((img_tl.x(), img_br.x()))
        y_min, y_max = sorted((img_tl.y(), img_br.y()))

        picked: set = set()
        for i, obj in enumerate(self.objects):
            for px, py in obj.points:
                if x_min <= px <= x_max and y_min <= py <= y_max:
                    picked.add(i)
                    break

        if self._box_sel_additive:
            new_sel = set(self._box_sel_base) | picked
        else:
            new_sel = picked

        self._selection = new_sel
        self._box_sel_base = set()
        self.selection_changed.emit(sorted(self._selection))
        self.update()

    # ------------------------------------------------------------------
    # PAN-mode context menu
    # ------------------------------------------------------------------

    def _show_pan_context_menu(self, screen_pos: QPointF):
        # --- vertex hit on a selected object? → delete-vertex or insert-vertex menu
        vtx_obj, vtx_idx = self._hit_selected_vertex(screen_pos)
        if vtx_obj >= 0:
            obj = self.objects[vtx_obj]
            min_verts = 3 if obj.kind == "polygon" else 2
            if len(obj.points) > min_verts:
                menu = QMenu(self)
                menu.addAction("Delete Vertex", lambda: self._delete_vertex(vtx_obj, vtx_idx))
                menu.exec(self.mapToGlobal(screen_pos.toPoint()))
            return

        # --- edge hit on a selected area or polyline? → insert vertex
        edge_obj, edge_idx, insert_pt = self._hit_selected_edge(screen_pos)
        if edge_obj >= 0:
            menu = QMenu(self)
            menu.addAction("Insert Vertex Here",
                           lambda: self._insert_vertex(edge_obj, edge_idx, insert_pt))
            menu.exec(self.mapToGlobal(screen_pos.toPoint()))
            return

        # --- regular object / empty context menu
        hit = self._hit_object(screen_pos)
        if hit >= 0 and hit not in self._selection:
            self._selection = {hit}
            self.selection_changed.emit(sorted(self._selection))
            self.update()

        menu = QMenu(self)
        sel  = sorted(self._selection)

        if len(sel) == 1:
            menu.addAction("Edit…", lambda: self._open_edit_dialog(sel[0]))
            menu.addAction("Copy Coordinates", lambda: self._copy_coordinates(sel[0]))
            menu.addSeparator()

        cut_a   = menu.addAction("Cut",   self.cut_selection)
        copy_a  = menu.addAction("Copy",  self.copy_selection)
        paste_a = menu.addAction("Paste", lambda: self.paste(screen_pos))
        dup_a   = menu.addAction("Duplicate", lambda: self.duplicate_selection())
        cut_a.setEnabled(bool(sel))
        copy_a.setEnabled(bool(sel))
        paste_a.setEnabled(bool(self._clipboard))
        dup_a.setEnabled(bool(sel))

        if sel:
            menu.addSeparator()
            menu.addAction("Delete", self.delete_requested.emit)

        img_pt = self._screen_to_img(screen_pos)
        wx, wy = self.img_to_world(img_pt)
        menu.addSeparator()
        menu.addAction(
            f"Copy Cursor Coordinates  ({wx:.6g}, {wy:.6g})",
            lambda: QApplication.clipboard().setText(f"{wx:.6g}\t{wy:.6g}"),
        )

        menu.exec(self.mapToGlobal(screen_pos.toPoint()))

    def _copy_coordinates(self, idx: int):
        obj = self.objects[idx]
        lines = ["x\ty"] + [
            "{:.6g}\t{:.6g}".format(*self.img_to_world(QPointF(x, y)))
            for x, y in obj.points
        ]
        QApplication.clipboard().setText("\n".join(lines))

    # ------------------------------------------------------------------
    # Vertex operations (delete / insert)
    # ------------------------------------------------------------------

    def _delete_vertex(self, obj_idx: int, vtx_idx: int):
        obj = self.objects[obj_idx]
        min_verts = 3 if obj.kind == "polygon" else 2
        if len(obj.points) <= min_verts:
            return
        self._push_undo()
        del obj.points[vtx_idx]
        self._recalculate_object(obj)
        self.objects_changed.emit()
        self.update()

    def _insert_vertex(self, obj_idx: int, edge_idx: int, img_pt: QPointF):
        obj = self.objects[obj_idx]
        self._push_undo()
        obj.points.insert(edge_idx + 1, [img_pt.x(), img_pt.y()])
        self._recalculate_object(obj)
        self.objects_changed.emit()
        self.update()

    # ------------------------------------------------------------------
    # Edit dialog
    # ------------------------------------------------------------------

    def _open_edit_dialog(self, idx: int):
        obj = self.objects[idx]
        if obj.kind == "textbox":
            self._edit_textbox(idx)
            return
        world_pts = [self.img_to_world(QPointF(*p)) for p in obj.points]
        dlg = EditObjectDialog(
            obj.kind, obj.name, world_pts,
            color=obj.color, levels=obj.levels, unit=self.scale_info.unit,
            line_width=obj.line_width, line_style=obj.line_style,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_name, new_world_pts, new_color, new_levels, new_lw, new_ls = dlg.values()
        self._push_undo()
        obj.name   = new_name
        obj.points = [[*(self._world_to_img(wx, wy).toTuple())] for wx, wy in new_world_pts]
        if obj.is_contour:
            obj.levels = new_levels
        else:
            obj.color = new_color
            obj.line_width = new_lw
            obj.line_style = new_ls
            if obj.kind != "point":
                self._recalculate_object(obj)
        self.objects_changed.emit()
        self.update()

    def _edit_textbox(self, idx: int):
        obj = self.objects[idx]
        dlg = TextBoxDialog(
            name=obj.name, text=obj.text, font_family=obj.font_family,
            font_size=obj.font_size, font_color=obj.font_color,
            line_color=obj.color, fill_color=obj.fill_color,
            line_width=obj.line_width, line_style=obj.line_style,
            bold=obj.bold, italic=obj.italic, underline=obj.underline,
            h_align=obj.h_align, v_align=obj.v_align, parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        self._push_undo()
        obj.name = v["name"]
        obj.text = v["text"]
        obj.font_family = v["font_family"]
        obj.font_size = v["font_size"]
        obj.font_color = v["font_color"]
        obj.color = v["line_color"]
        obj.fill_color = v["fill_color"]
        obj.line_width = v["line_width"]
        obj.line_style = v["line_style"]
        obj.bold = v["bold"]
        obj.italic = v["italic"]
        obj.underline = v["underline"]
        obj.h_align = v["h_align"]
        obj.v_align = v["v_align"]
        self.objects_changed.emit()
        self.update()

    def open_edit_dialog_for(self, idx: int):
        self._open_edit_dialog(idx)

    # ------------------------------------------------------------------
    # Inline text-box editing (double-click)
    # ------------------------------------------------------------------

    def _begin_inline_text_edit(self, idx: int):
        obj = self.objects[idx]
        if obj.kind != "textbox" or len(obj.points) < 2:
            return
        self._finish_inline_edit()   # close any prior editor first

        sp0 = self._img_to_screen(QPointF(*obj.points[0]))
        sp1 = self._img_to_screen(QPointF(*obj.points[1]))
        rect = QRectF(sp0, sp1).normalized().toRect()
        canvas = QRect(0, self._canvas_top(), self.width(), self._canvas_height())
        rect = rect.intersected(canvas)
        if rect.width() < 60:
            rect.setWidth(60)
        if rect.height() < 28:
            rect.setHeight(28)

        ed = _InlineTextEditor(self)
        ed.setPlainText(obj.text)
        ed.setFont(self._textbox_font(obj, ed.font()))
        # The editor shows the box's own colours, so what is typed looks like
        # what will be drawn. Set through the palette rather than a stylesheet:
        # theme.py is the only place in the app that calls setStyleSheet.
        palette = ed.palette()
        palette.setColor(QPalette.ColorRole.Text,
                         QColor(obj.font_color or T.MARK_TEXTBOX))
        palette.setColor(QPalette.ColorRole.Base,
                         QColor(obj.fill_color or T.CANVAS))
        ed.setPalette(palette)
        ed.setGeometry(rect)
        ed.committed.connect(self._apply_inline_text)
        ed.cancelled.connect(self._close_inline_editor)

        self._inline_editor = ed
        self._inline_obj_idx = idx
        ed.show()
        ed.setFocus(Qt.FocusReason.MouseFocusReason)
        ed.selectAll()
        self.update()

    def _apply_inline_text(self, text: str):
        idx = self._inline_obj_idx
        if 0 <= idx < len(self.objects) and self.objects[idx].kind == "textbox":
            obj = self.objects[idx]
            if text != obj.text:
                self._push_undo()
                obj.text = text
                self.objects_changed.emit()
        self._close_inline_editor()

    def _close_inline_editor(self):
        ed = self._inline_editor
        self._inline_editor = None
        self._inline_obj_idx = -1
        if ed is not None:
            try:
                ed.blockSignals(True)
            except RuntimeError:
                pass
            ed.deleteLater()
        self.update()

    def _finish_inline_edit(self):
        """Force-commit any active inline editor (before pan/zoom/tab switch)."""
        ed = self._inline_editor
        if ed is None:
            return
        if not ed._done:
            ed._done = True
            self._apply_inline_text(ed.toPlainText())
        else:
            self._close_inline_editor()

    # ------------------------------------------------------------------
    # Hit testing
    # ------------------------------------------------------------------

    def _hit_object(self, screen_pos: QPointF) -> int:
        if not self._show_objects:
            return -1
        for i in range(len(self.objects) - 1, -1, -1):
            if self._obj_hit(self.objects[i], screen_pos):
                return i
        return -1

    def _obj_hit(self, obj: DiagramObject, sp: QPointF) -> bool:
        if not obj.points:
            return False
        img = self._screen_to_img(sp)
        px, py = img.x(), img.y()

        if obj.kind in ("point", "point_contour"):
            spt = self._img_to_screen(QPointF(*obj.points[0]))
            return math.hypot(spt.x() - sp.x(), spt.y() - sp.y()) <= _HIT_R

        if obj.kind == "distance" and len(obj.points) == 2:
            s0 = self._img_to_screen(QPointF(*obj.points[0]))
            s1 = self._img_to_screen(QPointF(*obj.points[1]))
            return _dist_pt_to_seg(sp.x(), sp.y(), s0.x(), s0.y(), s1.x(), s1.y()) <= _HIT_R

        if obj.kind == "angle" and len(obj.points) == 3:
            s = [self._img_to_screen(QPointF(*p)) for p in obj.points]
            d1 = _dist_pt_to_seg(sp.x(), sp.y(), s[0].x(), s[0].y(), s[1].x(), s[1].y())
            d2 = _dist_pt_to_seg(sp.x(), sp.y(), s[2].x(), s[2].y(), s[1].x(), s[1].y())
            return min(d1, d2) <= _HIT_R

        if obj.kind == "polygon" and len(obj.points) >= 3:
            if _point_in_polygon(px, py, obj.points):
                return True
            n = len(obj.points)
            for j in range(n):
                sa = self._img_to_screen(QPointF(*obj.points[j]))
                sb = self._img_to_screen(QPointF(*obj.points[(j + 1) % n]))
                if _dist_pt_to_seg(sp.x(), sp.y(), sa.x(), sa.y(), sb.x(), sb.y()) <= _HIT_R:
                    return True

        if obj.kind in ("polyline", "polyline_contour") and len(obj.points) >= 2:
            n = len(obj.points)
            for j in range(n - 1):
                sa = self._img_to_screen(QPointF(*obj.points[j]))
                sb = self._img_to_screen(QPointF(*obj.points[j + 1]))
                if _dist_pt_to_seg(sp.x(), sp.y(), sa.x(), sa.y(), sb.x(), sb.y()) <= _HIT_R:
                    return True

        if obj.kind in ("ellipse", "textbox") and len(obj.points) >= 2:
            s0 = self._img_to_screen(QPointF(*obj.points[0]))
            s1 = self._img_to_screen(QPointF(*obj.points[1]))
            rect = QRectF(s0, s1).normalized()
            if obj.kind == "textbox":
                return rect.adjusted(-_HIT_R, -_HIT_R, _HIT_R, _HIT_R).contains(sp)
            # ellipse: inside the ellipse, or near its bounding-box outline
            cx, cy = rect.center().x(), rect.center().y()
            rx = max(rect.width() / 2.0, 1e-6)
            ry = max(rect.height() / 2.0, 1e-6)
            if ((sp.x() - cx) / rx) ** 2 + ((sp.y() - cy) / ry) ** 2 <= 1.0:
                return True
            margin = rect.adjusted(-_HIT_R, -_HIT_R, _HIT_R, _HIT_R)
            inner = rect.adjusted(_HIT_R, _HIT_R, -_HIT_R, -_HIT_R)
            if margin.contains(sp) and not inner.contains(sp):
                return True

        return False

    def _hit_selected_vertex(self, screen_pos: QPointF) -> Tuple[int, int]:
        """Return (obj_idx, vtx_idx) for the first vertex handle hit among selected non-point objects."""
        if not self._show_objects:
            return -1, -1
        for i in self._selection:
            obj = self.objects[i]
            if obj.kind in ("point", "point_contour"):
                continue
            for vi, (vx, vy) in enumerate(obj.points):
                sp = self._img_to_screen(QPointF(vx, vy))
                if math.hypot(sp.x() - screen_pos.x(), sp.y() - screen_pos.y()) <= _HIT_R:
                    return i, vi
        return -1, -1

    def _hit_selected_edge(self, screen_pos: QPointF) -> Tuple[int, int, QPointF]:
        """Return (obj_idx, edge_start_idx, img_insert_pt) for first edge hit among selected polygon/polyline objects."""
        for i in self._selection:
            obj = self.objects[i]
            if obj.kind not in ("polygon", "polyline", "polyline_contour"):
                continue
            n = len(obj.points)
            segs = range(n) if obj.kind == "polygon" else range(n - 1)
            for j in segs:
                sa = self._img_to_screen(QPointF(*obj.points[j]))
                sb = self._img_to_screen(QPointF(*obj.points[(j + 1) % n]))
                d = _dist_pt_to_seg(screen_pos.x(), screen_pos.y(),
                                    sa.x(), sa.y(), sb.x(), sb.y())
                if d <= _HIT_R:
                    img_sp = _seg_insert_point(screen_pos, sa, sb)
                    return i, j, self._screen_to_img(img_sp)
        return -1, -1, QPointF()

    # ------------------------------------------------------------------
    # Vertex drag (PAN mode, on selected objects)
    # ------------------------------------------------------------------

    def _begin_vtx_drag(self, obj_idx: int, vtx_idx: int, screen_pos: QPointF):
        obj = self.objects[obj_idx]
        self._vtx_drag_snap      = self._snapshot()
        self._vtx_drag_start_pts = [list(p) for p in obj.points]
        self._vtx_drag_obj       = obj_idx
        self._vtx_drag_vtx       = vtx_idx
        self._vtx_drag_active    = True
        self._vtx_drag_start_img = self._screen_to_img(screen_pos)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _cancel_vtx_drag(self):
        if self._vtx_drag_active and self._vtx_drag_start_pts and self._vtx_drag_obj >= 0:
            obj = self.objects[self._vtx_drag_obj]
            obj.points = [list(p) for p in self._vtx_drag_start_pts]
            self._recalculate_object(obj)
        self._vtx_drag_active = False
        self._vtx_drag_obj    = -1
        self._vtx_drag_vtx    = -1
        self._vtx_drag_start_pts = []
        self._update_cursor_for_pos()
        self.update()

    # ------------------------------------------------------------------
    # Measurement recalculation
    # ------------------------------------------------------------------

    def _recalculate_object(self, obj: DiagramObject, scale_info: Optional[ScaleInfo] = None):
        si = scale_info if scale_info is not None else self.scale_info
        pts = [Point(x, y) for x, y in obj.points]
        sf  = si.scale_factor
        unit = si.unit
        if obj.kind == "distance" and len(pts) == 2:
            length = pts[0].distance_to(pts[1]) * sf
            obj.value = length
            obj.unit = unit
            obj.measures = {"length": length}
        elif obj.kind == "polyline" and len(pts) >= 2:
            length = sum(pts[i].distance_to(pts[i + 1]) for i in range(len(pts) - 1)) * sf
            obj.value = length
            obj.unit = unit
            obj.measures = {"length": length}
        elif obj.kind == "angle" and len(pts) == 3:
            p1, v, p2 = pts
            v1x, v1y = p1.x - v.x, p1.y - v.y
            v2x, v2y = p2.x - v.x, p2.y - v.y
            dot = v1x * v2x + v1y * v2y
            mag = math.hypot(v1x, v1y) * math.hypot(v2x, v2y)
            angle = math.degrees(math.acos(max(-1.0, min(1.0, dot / mag)))) if mag > 0 else 0.0
            obj.value = angle
            obj.unit = "°"
            obj.measures = {"angle": angle}
        elif obj.kind == "polygon" and len(pts) >= 3:
            n = len(pts)
            shoelace = sum(pts[i].x * pts[(i+1)%n].y - pts[(i+1)%n].x * pts[i].y
                           for i in range(n))
            area = abs(shoelace) / 2.0 * (sf ** 2)
            perimeter = sum(pts[i].distance_to(pts[(i+1)%n]) for i in range(n)) * sf
            obj.value = area
            obj.unit = unit
            obj.measures = {"area": area, "perimeter": perimeter}
        elif obj.kind == "ellipse" and len(pts) == 2:
            a = abs(pts[0].x - pts[1].x) / 2.0 * sf
            b = abs(pts[0].y - pts[1].y) / 2.0 * sf
            circ = _ellipse_circumference(a, b)
            obj.value = circ
            obj.unit = unit
            obj.measures = {
                "circumference": circ,
                "diameter_major": 2.0 * max(a, b),
                "diameter_minor": 2.0 * min(a, b),
                "area": math.pi * a * b,
            }

    def _recalculate_all(self):
        for obj in self.objects:
            if obj.kind != "point":
                self._recalculate_object(obj)

    # ------------------------------------------------------------------
    # Live measure status
    # ------------------------------------------------------------------

    def _emit_live_measure(self):
        measure_tools = {
            Tool.ADD_LINE, Tool.ADD_ANGLE, Tool.ADD_POLYGON, Tool.ADD_POLYLINE,
            Tool.ADD_ELLIPSE, Tool.SET_SCALE_DISTANCE, Tool.SET_SCALE_COORDS,
        }
        if not self._temp or self.current_tool not in measure_tools or self._mouse_img is None:
            self.live_measure.emit("")
            return

        tool = self.current_tool
        last = self._temp[-1]
        cur  = self._apply_snap(self._mouse_img)
        sf   = self.scale_info.scale_factor
        unit = self.scale_info.unit

        if tool in (Tool.SET_SCALE_DISTANCE, Tool.SET_SCALE_COORDS):
            d_px = math.hypot(cur.x() - last.x, cur.y() - last.y)
            self.live_measure.emit(f"Dist: {d_px:.1f} px")

        elif tool == Tool.ADD_LINE:
            d_px = math.hypot(cur.x() - last.x, cur.y() - last.y)
            self.live_measure.emit(f"Dist: {d_px * sf:.4g} {unit}")

        elif tool == Tool.ADD_ANGLE:
            if len(self._temp) == 2:
                p1, vertex = self._temp[0], self._temp[1]
                v1x, v1y = p1.x - vertex.x, p1.y - vertex.y
                v2x, v2y = cur.x() - vertex.x, cur.y() - vertex.y
                dot = v1x * v2x + v1y * v2y
                mag = math.hypot(v1x, v1y) * math.hypot(v2x, v2y)
                angle = math.degrees(math.acos(max(-1.0, min(1.0, dot / mag)))) if mag > 0 else 0.0
                self.live_measure.emit(f"Angle: {angle:.2f}°")
            else:
                d_px = math.hypot(cur.x() - last.x, cur.y() - last.y)
                self.live_measure.emit(f"Dist: {d_px * sf:.4g} {unit}")

        elif tool == Tool.ADD_POLYGON:
            if len(self._temp) >= 2:
                pts = [[p.x, p.y] for p in self._temp] + [[cur.x(), cur.y()]]
                n = len(pts)
                shoelace = sum(pts[i][0] * pts[(i+1)%n][1] - pts[(i+1)%n][0] * pts[i][1]
                               for i in range(n))
                perim = sum(math.hypot(pts[(i+1)%n][0] - pts[i][0],
                                       pts[(i+1)%n][1] - pts[i][1]) for i in range(n)) * sf
                self.live_measure.emit(
                    f"Area: {abs(shoelace)/2.0 * (sf**2):.4g} {unit}²  ·  "
                    f"Perimeter: {perim:.4g} {unit}"
                )
            else:
                d_px = math.hypot(cur.x() - last.x, cur.y() - last.y)
                self.live_measure.emit(f"Dist: {d_px * sf:.4g} {unit}")

        elif tool == Tool.ADD_POLYLINE:
            all_pts = [[p.x, p.y] for p in self._temp] + [[cur.x(), cur.y()]]
            total = sum(
                math.hypot(all_pts[i+1][0] - all_pts[i][0], all_pts[i+1][1] - all_pts[i][1])
                for i in range(len(all_pts) - 1)
            )
            self.live_measure.emit(f"Length: {total * sf:.4g} {unit}")

        elif tool == Tool.ADD_ELLIPSE:
            a = abs(cur.x() - last.x) / 2.0 * sf
            b = abs(cur.y() - last.y) / 2.0 * sf
            self.live_measure.emit(
                f"Circumference: {_ellipse_circumference(a, b):.4g} {unit}  ·  "
                f"Area: {math.pi * a * b:.4g} {unit}²"
            )

    # ------------------------------------------------------------------
    # Finish helpers
    # ------------------------------------------------------------------

    def _finish_scale(self):
        pixel_dist = self._temp[0].distance_to(self._temp[1])
        tool = self.current_tool

        if tool == Tool.SET_SCALE_DISTANCE:
            dlg = ScaleDistanceDialog(self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                real_dist, unit = dlg.values()
                self._push_undo()
                self.scale_info = ScaleInfo(pixel_dist, real_dist, unit)
                self._recalculate_all()
                self.scale_set.emit(self.scale_info)
                self.objects_changed.emit()

        elif tool == Tool.SET_SCALE_COORDS:
            dlg = ScaleCoordsDialog(self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                (x1, y1, x2, y2), unit = dlg.values()
                real_dist = math.hypot(x2 - x1, y2 - y1)
                self._push_undo()
                self.scale_info = ScaleInfo(pixel_dist, real_dist, unit)
                self._recalculate_all()
                self.scale_set.emit(self.scale_info)
                self.objects_changed.emit()

        self._temp.clear()
        self.update()

    def _default_object_name(self, kind: str) -> str:
        prefix = {
            "point": "P", "distance": "L", "angle": "A",
            "polygon": "Poly", "polyline": "PL", "ellipse": "E", "textbox": "Text",
            "polyline_contour": "PLC", "point_contour": "PtC",
        }.get(kind, kind.capitalize())
        count = sum(1 for o in self.objects if o.kind == kind) + 1
        return f"{prefix}{count}"

    def _ask_name_and_color(self, kind: str) -> Optional[Tuple[str, str, float, str]]:
        default_color = _KIND_COLOR.get(kind, _LABEL_COLOR).name()
        dlg = NameDialog(kind, self._default_object_name(kind), default_color, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self._temp.clear()
            self.update()
            return None
        return dlg.label(), dlg.color(), dlg.line_width(), dlg.line_style()

    def _ask_contour_levels(self, kind: str):
        """Open the levels dialog for a freshly-placed contour. Returns
        (name, levels) or None if cancelled."""
        kind_label = "Polyline Contour" if kind == "polyline_contour" else "Point Contour"
        dlg = ContourLevelsDialog(
            kind_label, self.scale_info.unit, self._default_object_name(kind),
            None, self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self._temp.clear()
            self.update()
            return None
        name, levels = dlg.values()
        return name, levels

    def _finish_distance(self):
        result = self._ask_name_and_color("distance")
        if result is None:
            return
        name, color, lw, ls = result
        p0, p1 = self._temp[0], self._temp[1]
        obj = DiagramObject(
            kind="distance", name=name, color=color, line_width=lw, line_style=ls,
            points=[[p0.x, p0.y], [p1.x, p1.y]],
            unit=self.scale_info.unit,
        )
        self._recalculate_object(obj)
        self._push_undo()
        self.objects.append(obj)
        self.objects_changed.emit()
        self._temp.clear()
        self.update()

    def _finish_angle(self):
        result = self._ask_name_and_color("angle")
        if result is None:
            return
        name, color, lw, ls = result
        obj = DiagramObject(
            kind="angle", name=name, color=color, line_width=lw, line_style=ls,
            points=[[p.x, p.y] for p in self._temp],
            unit="°",
        )
        self._recalculate_object(obj)
        self._push_undo()
        self.objects.append(obj)
        self.objects_changed.emit()
        self._temp.clear()
        self.update()

    def _finish_polygon(self):
        result = self._ask_name_and_color("polygon")
        if result is None:
            return
        name, color, lw, ls = result
        obj = DiagramObject(
            kind="polygon", name=name, color=color, line_width=lw, line_style=ls,
            points=[[p.x, p.y] for p in self._temp],
            unit=self.scale_info.unit,
        )
        self._recalculate_object(obj)
        self._push_undo()
        self.objects.append(obj)
        self.objects_changed.emit()
        self._temp.clear()
        self.update()

    def _finish_polyline(self):
        result = self._ask_name_and_color("polyline")
        if result is None:
            return
        name, color, lw, ls = result
        obj = DiagramObject(
            kind="polyline", name=name, color=color, line_width=lw, line_style=ls,
            points=[[p.x, p.y] for p in self._temp],
            unit=self.scale_info.unit,
        )
        self._recalculate_object(obj)
        self._push_undo()
        self.objects.append(obj)
        self.objects_changed.emit()
        self._temp.clear()
        self.update()

    def _finish_ellipse(self):
        result = self._ask_name_and_color("ellipse")
        if result is None:
            return
        name, color, lw, ls = result
        p0, p1 = self._temp[0], self._temp[1]
        obj = DiagramObject(
            kind="ellipse", name=name, color=color, line_width=lw, line_style=ls,
            points=[[p0.x, p0.y], [p1.x, p1.y]],
            unit=self.scale_info.unit,
        )
        self._recalculate_object(obj)
        self._push_undo()
        self.objects.append(obj)
        self.objects_changed.emit()
        self._temp.clear()
        self.update()

    def _finish_textbox(self):
        p0, p1 = self._temp[0], self._temp[1]
        dlg = TextBoxDialog(name=self._default_object_name("textbox"), parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self._temp.clear()
            self.update()
            return
        v = dlg.values()
        obj = DiagramObject(
            kind="textbox", name=v["name"],
            points=[[p0.x, p0.y], [p1.x, p1.y]],
            color=v["line_color"], line_width=v["line_width"], line_style=v["line_style"],
            text=v["text"], font_family=v["font_family"], font_size=v["font_size"],
            font_color=v["font_color"], fill_color=v["fill_color"],
            bold=v["bold"], italic=v["italic"], underline=v["underline"],
            h_align=v["h_align"], v_align=v["v_align"],
        )
        self._push_undo()
        self.objects.append(obj)
        self.objects_changed.emit()
        self._temp.clear()
        self.update()

    def _finish_polyline_contour(self):
        pts = [[p.x, p.y] for p in self._temp]
        result = self._ask_contour_levels("polyline_contour")
        if result is None:
            return
        name, levels = result
        obj = DiagramObject(
            kind="polyline_contour", name=name, points=pts,
            unit=self.scale_info.unit, levels=levels,
        )
        self._push_undo()
        self.objects.append(obj)
        self.objects_changed.emit()
        self._temp.clear()
        self.update()

    def _finish_point_contour(self, img_pt: Point):
        result = self._ask_contour_levels("point_contour")
        if result is None:
            return
        name, levels = result
        obj = DiagramObject(
            kind="point_contour", name=name, points=[[img_pt.x, img_pt.y]],
            unit=self.scale_info.unit, levels=levels,
        )
        self._push_undo()
        self.objects.append(obj)
        self.objects_changed.emit()
        self._temp.clear()
        self.update()

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------

    def _snapshot(self) -> dict:
        return {
            "origin":       (self.origin.x, self.origin.y),
            "origin_world": self._origin_world,
            "scale_info":   (self.scale_info.pixel_distance,
                             self.scale_info.real_distance,
                             self.scale_info.unit),
            "objects":      [deepcopy(o.to_dict()) for o in self.objects],
            "legend_title": self.legend_title,
        }

    def _record_undo(self, snap: dict):
        """Push `snap` onto the undo stack (capped at _MAX_UNDO) and clear redo."""
        stack = self._undo_stack
        stack.append(snap)
        if len(stack) > _MAX_UNDO:
            del stack[:len(stack) - _MAX_UNDO]
        self._redo_stack.clear()

    def _push_undo(self):
        self._record_undo(self._snapshot())

    def _restore(self, snap: dict):
        self.origin        = Point(*snap["origin"])
        self._origin_world = snap.get("origin_world", (0.0, 0.0))
        self.scale_info    = ScaleInfo(*snap["scale_info"])
        self.objects       = [DiagramObject.from_dict(d) for d in snap["objects"]]
        self.legend_title  = snap.get("legend_title", "Legend")
        self._temp.clear()
        self._selection.clear()
        self.state_restored.emit()
        self.update()

    def undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        self._restore(self._undo_stack.pop())

    def redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        self._restore(self._redo_stack.pop())

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    @staticmethod
    def _page_state_has_data(ps: PageState) -> bool:
        """True if a page carries any annotation / scale / origin / legend state
        worth preserving (i.e. it differs from a pristine page)."""
        if ps.objects:
            return True
        if ps.origin_world != (0.0, 0.0):
            return True
        if ps.origin.x != 0.0 or ps.origin.y != 0.0:
            return True
        si = ps.scale_info
        if si.unit != "px" or si.pixel_distance != 1.0 or si.real_distance != 1.0:
            return True
        if ps.legend_title != "Legend" or not ps.legend_visible:
            return True
        return False

    @classmethod
    def _tab_has_session_state(cls, tab: DocumentTab) -> bool:
        return any(cls._page_state_has_data(ps) for ps in tab.pages.values())

    def tab_has_session_state(self, idx: int) -> bool:
        if 0 <= idx < len(self._tabs):
            return self._tab_has_session_state(self._tabs[idx])
        return False

    @staticmethod
    def _page_state_to_dict(ps: PageState) -> dict:
        return {
            "scale_info":     ps.scale_info.to_dict(),
            "origin":         ps.origin.to_dict(),
            "origin_world":   list(ps.origin_world),
            "objects":        [o.to_dict() for o in ps.objects],
            "legend_title":   ps.legend_title,
            "legend_visible": ps.legend_visible,
        }

    def session_data(self) -> dict:
        """Serialize the active document: one entry per page that holds state,
        plus the current page and view so a reload restores exactly what was
        on screen."""
        tab = self._active
        if tab is None:
            return {"version": 2, "pages": {}}
        pages = {
            str(idx): self._page_state_to_dict(ps)
            for idx, ps in sorted(tab.pages.items())
            if self._page_state_has_data(ps)
        }
        return {
            "version":      2,
            "current_page": tab.pdf_page_index,
            "zoom":         tab.zoom,
            "pan":          [tab.pan.x(), tab.pan.y()],
            "pages":        pages,
        }

    def export_pages(self) -> List[PageMarkup]:
        """The active document's markup, one entry per page that holds any,
        for writing into a PDF. An open inline text edit is committed first."""
        self._finish_inline_edit()
        tab = self._active
        if tab is None:
            return []
        return [
            PageMarkup(idx, list(ps.objects), ps.scale_info, ps.origin,
                       tuple(ps.origin_world), ps.legend_title, ps.legend_visible)
            for idx, ps in sorted(tab.pages.items())
            if self._page_state_has_data(ps)
        ]

    def current_tab_dpi(self) -> int:
        """Image pixels per inch of the active page: the PDF render resolution,
        and the resolution an image is laid onto a PDF page at."""
        return self._pdf_dpi

    def export_style(self) -> ExportStyle:
        """The theme colours and label font the canvas draws with."""
        return ExportStyle(
            kind_colors={k: c.name() for k, c in _KIND_COLOR.items()},
            contour_color=T.contour(0),
            guide_color=_SKELETON_COLOR.name(),
            text_color=T.MARK_TEXTBOX,
            label_family=self.font().family(),
            label_px=float(QFontInfo(self.font()).pixelSize()),
            legend_ink=T.INK,
            legend_bg=T.CANVAS,
            legend_border=T.ink_hex(T.SURFACE_BORDER_STRONG),
        )

    def _recompute_missing_measures_for(self, ps: PageState):
        """Backfill derived measurements for a page's objects that lack them
        (e.g. loaded from an older session that only stored a single `value`)."""
        for obj in ps.objects:
            if obj.kind in ("point", "textbox") or obj.is_contour:
                continue
            if not obj.measures:
                self._recalculate_object(obj, ps.scale_info)

    def _recompute_missing_measures(self):
        if self._page is not None:
            self._recompute_missing_measures_for(self._page)

    def load_session(self, data: dict, progress=None):
        """Load a session into the active tab. Supports the multi-page v2 format
        as well as the legacy single-page formats. Optional
        `progress(current, total)` callback reports object-load progress."""
        if self._active is None:
            return
        if "pages" in data:
            self._load_multi_page_session(self._active, data, progress)
        else:
            self._load_legacy_session(data, progress)
        self._temp.clear()
        self._selection.clear()
        self.update()

    def _load_multi_page_session(self, tab: DocumentTab, data: dict, progress=None):
        raw_pages = data.get("pages", {}) or {}
        total = sum(len(pd.get("objects", [])) for pd in raw_pages.values())
        done = 0
        tab.pages.clear()
        for key, pd in raw_pages.items():
            try:
                idx = int(key)
            except (TypeError, ValueError):
                continue
            ps = PageState()
            ps.scale_info     = ScaleInfo.from_dict(pd["scale_info"])
            ps.origin         = Point.from_dict(pd["origin"])
            ow                = pd.get("origin_world", [0.0, 0.0])
            ps.origin_world   = (float(ow[0]), float(ow[1]))
            ps.legend_title   = pd.get("legend_title", "Legend")
            ps.legend_visible = bool(pd.get("legend_visible", True))
            for o in pd.get("objects", []):
                ps.objects.append(DiagramObject.from_dict(o))
                done += 1
                if progress is not None and (done % 25 == 0 or done == total):
                    progress(done, total)
            self._recompute_missing_measures_for(ps)
            tab.pages[idx] = ps
        if progress is not None and total == 0:
            progress(0, 0)

        # Restore the viewed page (clamped to the document) and the saved view.
        cur = int(data.get("current_page", 0) or 0)
        if tab.pdf_doc is not None:
            cur = max(0, min(cur, len(tab.pdf_doc) - 1))
        else:
            cur = 0
        tab.pdf_page_index = cur
        self._render_pdf_page()   # no-op for images; re-renders the PDF page
        try:
            tab.zoom = max(0.05, min(20.0, float(data["zoom"])))
        except (KeyError, TypeError, ValueError):
            pass
        pan = data.get("pan")
        if isinstance(pan, (list, tuple)) and len(pan) == 2:
            try:
                tab.pan = QPointF(float(pan[0]), float(pan[1]))
            except (TypeError, ValueError):
                pass
        self.refresh_tab_label(self._active_idx)
        self.zoom_changed.emit(tab.zoom)

    def _load_legacy_session(self, data: dict, progress=None):
        """Load an older single-page session into the active page."""
        self.scale_info    = ScaleInfo.from_dict(data["scale_info"])
        self.origin        = Point.from_dict(data["origin"])
        ow                 = data.get("origin_world", [0.0, 0.0])
        self._origin_world = (float(ow[0]), float(ow[1]))
        self.legend_title  = data.get("legend_title", "Legend")

        if "objects" in data:
            raw = data["objects"]
            total = len(raw)
            self.objects = []
            for i, o in enumerate(raw):
                self.objects.append(DiagramObject.from_dict(o))
                if progress is not None and (i % 25 == 0 or i == total - 1):
                    progress(i + 1, total)
        else:
            raw_pts = data.get("points", [])
            raw_ms  = data.get("measurements", [])
            total = len(raw_pts) + len(raw_ms)
            self.objects = []
            for i, p in enumerate(raw_pts):
                self.objects.append(DiagramObject(
                    kind="point", name=p.get("label", ""),
                    points=[[p["x"], p["y"]]],
                ))
                if progress is not None and (i % 25 == 0 or i == total - 1):
                    progress(i + 1, total)
            for j, m in enumerate(raw_ms):
                self.objects.append(DiagramObject.from_dict(m))
                idx = len(raw_pts) + j
                if progress is not None and (idx % 25 == 0 or idx == total - 1):
                    progress(idx + 1, total)

        self._recompute_missing_measures()
