import json
import os

from PySide6.QtCore import Qt, QPointF, QSettings, QSize, Slot
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QMainWindow, QMenu, QMessageBox,
    QListWidgetItem, QProgressBar, QSizePolicy, QStackedWidget, QToolBar, QWidget,
)

from ..core import pages
from ..core.constants import Tool, TOOL_HELP, TOOL_LABELS, TOOL_SHORTCUTS
from . import icons
from . import layout as ly
from .commands import CommandsDialog
from .dialogs import ExportDialog
from .home import HomePage
from .new_page import NewPageDialog
from ..core.fonts import FontResolver
from ..core.models import DiagramObject, Point, ScaleInfo
from ..core.pdf_export import export_pdf
from .panel import RightPanel
from .theme import FONTS_DIR, Tokens as T
from .viewer import ImageViewer


class MainWindow(QMainWindow):
    # Derived from the narrowest arrangement that does not clip: the tool
    # palette needs ~700 px before it folds into an overflow button, and the
    # objects column will not go below its own minimum, leaving the canvas a
    # usable width. Height covers the toolbar, a legible canvas, and the bar.
    MIN_WIDTH = RightPanel.MIN_WIDTH + 712
    MIN_HEIGHT = 640

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vellum")
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.resize(1400, 860)

        self.viewer      = ImageViewer()
        self.right_panel = RightPanel()

        # The canvas runs flush to its pane; the objects column carries the
        # window margins so its content is not welded to the splitter.
        panel_holder = QWidget()
        holder_layout = ly.vbox(panel_holder, margin=T.MARGIN_WINDOW)
        holder_layout.addWidget(self.right_panel)

        splitter = ly.splitter(self.viewer, panel_holder,
                               sizes=[1060, 340], stretch=[1, 0])

        # The home page stands in for the workspace whenever no document is
        # open, so an empty window always offers a way to start.
        self.home = HomePage()
        self.home.new_requested.connect(self.new_document)
        self.home.open_requested.connect(self.open_file)
        self.home.help_requested.connect(self.show_commands)
        self._stack = QStackedWidget()
        self._stack.addWidget(self.home)
        self._stack.addWidget(splitter)
        self._workspace = splitter

        central = QWidget()
        central.setObjectName("centralWidget")
        central_layout = ly.hbox(central, margin=0)
        central_layout.addWidget(self._stack)
        self.setCentralWidget(central)
        self._commands_dialog = None
        self._untitled_count = 0

        self._build_menus()
        self._build_toolbar()
        self._build_status_bar()
        self._connect_signals()

        self._set_tool(Tool.PAN)
        self._syncing_selection = False
        self._last_open_dir = ""

        settings = QSettings("Vellum", "Vellum")
        self._recent_files: list[str] = settings.value("recentFiles", [])
        if isinstance(self._recent_files, str):
            self._recent_files = [self._recent_files]
        self._recent_sessions: list[str] = settings.value("recentSessions", [])
        if isinstance(self._recent_sessions, str):
            self._recent_sessions = [self._recent_sessions]

        # Map: image/pdf file path -> last-attached session path
        raw_map = settings.value("fileSessionMap", "")
        try:
            self._file_session_map: dict[str, str] = (
                json.loads(raw_map) if raw_map else {}
            )
            if not isinstance(self._file_session_map, dict):
                self._file_session_map = {}
        except (json.JSONDecodeError, TypeError):
            self._file_session_map = {}

        self._update_recent_menu()
        self._update_recent_session_menu()
        self._refresh_ui_for_active_tab()

    # ------------------------------------------------------------------
    # Menus
    # ------------------------------------------------------------------

    def _build_menus(self):
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("&File")
        self._add_action(file_menu, "&New page…",     "Ctrl+N",        self.new_document)
        self._add_action(file_menu, "&Open…",         "Ctrl+O",        self.open_file)
        self._recent_menu = file_menu.addMenu("Open &recent")
        file_menu.addSeparator()
        self._add_action(file_menu, "&Save session",     "Ctrl+S",       self.save_session)
        self._add_action(file_menu, "Save session &as…", "Ctrl+Shift+S", self.save_session_as)
        self._add_action(file_menu, "&Load session…",    "Ctrl+Shift+O", self.load_session)
        self._recent_session_menu = file_menu.addMenu("Load &recent session")
        file_menu.addSeparator()
        self._add_action(file_menu, "&Export data…",  "Ctrl+E",        self.show_export)
        self._add_action(file_menu, "Export as &PDF with markups…", "Ctrl+Shift+P", self.export_markup_pdf)
        self._add_action(file_menu, "Export &view as image…", "Ctrl+Shift+E", self.export_view_image)
        self._add_action(file_menu, "Snapshot view to &clipboard", "Ctrl+Shift+C", self.snapshot_view_to_clipboard)
        file_menu.addSeparator()
        self._add_action(file_menu, "&Quit",          "Ctrl+Q",        self.close)

        # Edit
        edit_menu = mb.addMenu("&Edit")
        self._add_action(edit_menu, "&Undo",          "Ctrl+Z",        self.viewer.undo)
        self._add_action(edit_menu, "&Redo",          "Ctrl+Y",        self.viewer.redo)
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Cu&t",           "Ctrl+X",        self.viewer.cut_selection)
        self._add_action(edit_menu, "&Copy",          "Ctrl+C",        self.viewer.copy_selection)
        self._add_action(edit_menu, "&Paste",         "Ctrl+V",        self.viewer.paste)
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Select &all",    "Ctrl+A",        self.viewer.select_all)
        self._add_action(edit_menu, "&Delete selected", "Del",         self._on_delete_selected)
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Clear &all",     None,            self._on_clear_all)

        # View
        view_menu = mb.addMenu("&View")
        self._add_action(view_menu, "Fit to &window", "Ctrl+0",        self.viewer.fit_to_window)
        self._add_action(view_menu, "Zoom &in",       "Ctrl+=",
                         lambda: self.viewer.set_zoom(self.viewer.zoom * 1.25))
        self._add_action(view_menu, "Zoom &out",      "Ctrl+-",
                         lambda: self.viewer.set_zoom(self.viewer.zoom / 1.25))
        view_menu.addSeparator()
        self._show_objects_act = QAction("Show all &objects", self)
        self._show_objects_act.setCheckable(True)
        self._show_objects_act.setChecked(True)
        self._show_objects_act.setShortcut(QKeySequence("Ctrl+H"))
        self._show_objects_act.toggled.connect(self.viewer.set_objects_visible)
        view_menu.addAction(self._show_objects_act)

        self._show_labels_act = QAction("Show &labels", self)
        self._show_labels_act.setCheckable(True)
        self._show_labels_act.setChecked(True)
        self._show_labels_act.setShortcut(QKeySequence("Ctrl+L"))
        self._show_labels_act.toggled.connect(self.viewer.set_labels_visible)
        view_menu.addAction(self._show_labels_act)

        view_menu.addSeparator()
        self._show_legend_act = QAction("Show le&gend", self)
        self._show_legend_act.setCheckable(True)
        self._show_legend_act.setChecked(True)
        self._show_legend_act.toggled.connect(self.viewer.set_legend_visible)
        view_menu.addAction(self._show_legend_act)
        self._add_action(view_menu, "Edit legend &title…", None,
                         self.viewer.edit_legend_title)

        # Tools
        tools_menu = mb.addMenu("&Tools")
        for tool in Tool:
            act = QAction(TOOL_LABELS[tool], self)
            act.setShortcut(QKeySequence(TOOL_SHORTCUTS[tool]))
            act.triggered.connect(lambda checked, t=tool: self._set_tool(t))
            tools_menu.addAction(act)

        # Help
        help_menu = mb.addMenu("&Help")
        self._add_action(help_menu, "&Commands…", "F1", self.show_commands)
        help_menu.addSeparator()
        self._add_action(help_menu, "&About", None, self.show_about)

    def _add_action(self, menu, label: str, shortcut, slot):
        act = QAction(label, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(lambda checked=False, s=slot: s())
        menu.addAction(act)

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _build_toolbar(self):
        tb = QToolBar("Tools", self)
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setIconSize(QSize(T.ICON_SIZE, T.ICON_SIZE))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        self._toolbar = tb

        # File / document actions. Each tooltip names the action and its
        # shortcut, and every one has a labelled twin in the menus - the glyph
        # is never the only thing saying what a button does.
        new_act = tb.addAction(icons.action_icon("new"), "New")
        new_act.setToolTip("New blank page  (Ctrl+N)")
        new_act.triggered.connect(self.new_document)
        open_act = tb.addAction(icons.action_icon("open"), "Open")
        open_act.setToolTip("Open image or PDF  (Ctrl+O)")
        open_act.triggered.connect(self.open_file)
        save_act = tb.addAction(icons.action_icon("save"), "Save session")
        save_act.setToolTip("Save session  (Ctrl+S)")
        save_act.triggered.connect(self.save_session)
        export_act = tb.addAction(icons.action_icon("export"), "Export")
        export_act.setToolTip("Export data  (Ctrl+E)")
        export_act.triggered.connect(self.show_export)
        tb.addSeparator()

        # Tool actions — checkable and mutually exclusive
        self._tool_actions: dict[Tool, QAction] = {}
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)

        groups = [
            [Tool.PAN, Tool.SELECT, Tool.ZOOM_RECT],
            [Tool.SET_ORIGIN, Tool.SET_SCALE_DISTANCE, Tool.SET_SCALE_COORDS],
            [Tool.ADD_POINT, Tool.ADD_LINE, Tool.ADD_ANGLE, Tool.ADD_POLYGON,
             Tool.ADD_POLYLINE, Tool.ADD_ELLIPSE, Tool.ADD_TEXTBOX],
            [Tool.ADD_POINT_CONTOUR, Tool.ADD_POLYLINE_CONTOUR],
        ]
        for gi, group in enumerate(groups):
            for tool in group:
                act = QAction(icons.tool_icon(tool), TOOL_LABELS[tool], self)
                act.setCheckable(True)
                act.setToolTip(f"{TOOL_LABELS[tool]}  ({TOOL_SHORTCUTS[tool]})")
                act.triggered.connect(lambda checked, t=tool: self._set_tool(t))
                self._tool_group.addAction(act)
                tb.addAction(act)
                self._tool_actions[tool] = act
            if gi < len(groups) - 1:
                tb.addSeparator()

        # PDF navigation — hidden unless a multi-page PDF is active
        self._pdf_sep = tb.addSeparator()
        self._pdf_prev_act = tb.addAction(icons.action_icon("prev"), "Previous page")
        self._pdf_prev_act.setToolTip("Previous page of this PDF")
        self._pdf_prev_act.triggered.connect(self._go_prev_page)
        self._pdf_page_lbl = QLabel("1 / 1")
        self._pdf_page_lbl_act = tb.addWidget(self._pdf_page_lbl)
        self._pdf_next_act = tb.addAction(icons.action_icon("next"), "Next page")
        self._pdf_next_act.setToolTip("Next page of this PDF")
        self._pdf_next_act.triggered.connect(self._go_next_page)
        for a in (self._pdf_sep, self._pdf_prev_act,
                  self._pdf_page_lbl_act, self._pdf_next_act):
            a.setVisible(False)

    def _update_recent_menu(self):
        self._recent_menu.clear()
        for path in self._recent_files:
            act = QAction(path, self)
            act.triggered.connect(lambda checked, p=path: self._open_recent(p))
            self._recent_menu.addAction(act)
        self._recent_menu.setEnabled(bool(self._recent_files))

    def _open_recent(self, path: str):
        if not os.path.exists(path):
            QMessageBox.warning(self, "Open recent", f"File not found:\n{path}")
            self._recent_files = [p for p in self._recent_files if p != path]
            self._save_recents()
            self._update_recent_menu()
            return
        self._load_path(path)

    def _load_path(self, path: str):
        """Open `path` as a brand-new tab in the viewer."""
        idx = self.viewer.open_in_new_tab(path)
        if idx < 0:
            QMessageBox.warning(self, "Open file", f"Could not open:\n{path}")
            return

        self._last_open_dir = os.path.dirname(path)
        if path in self._recent_files:
            self._recent_files.remove(path)
        self._recent_files.insert(0, path)
        self._recent_files = self._recent_files[:10]
        self._save_recents()
        self._update_recent_menu()

        # Offer to also load the last-attached session for this file.
        self._maybe_offer_associated_session(path)

        # Refresh dependent UI for the now-active tab.
        self._refresh_ui_for_active_tab()

    def _maybe_offer_associated_session(self, file_path: str):
        norm = os.path.normcase(os.path.abspath(file_path))
        session_path = self._file_session_map.get(norm)
        if not session_path or not os.path.exists(session_path):
            if session_path and not os.path.exists(session_path):
                # Stale association — clean up
                del self._file_session_map[norm]
                self._save_file_session_map()
            return
        reply = QMessageBox.question(
            self, "Open associated session",
            f"Vellum last opened this file with the session:\n\n"
            f"{session_path}\n\n"
            "Open that session too?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._do_load_session(session_path)

    def _save_recents(self):
        QSettings("Vellum", "Vellum").setValue("recentFiles", self._recent_files)

    def _update_recent_session_menu(self):
        self._recent_session_menu.clear()
        for path in self._recent_sessions:
            act = QAction(path, self)
            act.triggered.connect(lambda checked, p=path: self._open_recent_session(p))
            self._recent_session_menu.addAction(act)
        self._recent_session_menu.setEnabled(bool(self._recent_sessions))

    def _open_recent_session(self, path: str):
        if not os.path.exists(path):
            QMessageBox.warning(self, "Load recent session", f"File not found:\n{path}")
            self._recent_sessions = [p for p in self._recent_sessions if p != path]
            self._save_recent_sessions()
            self._update_recent_session_menu()
            return
        self._do_load_session(path)

    def _do_load_session(self, path: str):
        if self.viewer.current_tab_index < 0:
            QMessageBox.information(
                self, "Load session",
                "Open an image or PDF first, then load a session into its tab.",
            )
            return

        # Rebuilding a session has to run on the UI thread - it constructs the
        # viewer's own objects - so the controls that would re-enter it are
        # disabled for the duration instead, and the status bar carries the
        # progress rather than a modal dialog stealing the window.
        self._set_inputs_enabled(False)
        self.set_busy(True, "Loading session…")
        self._progress.setRange(0, 0)
        QApplication.processEvents()

        def on_progress(cur: int, total: int):
            if total > 0:
                self._progress.setRange(0, total)
                self._progress.setValue(cur)
                self.set_status(f"Loading objects… ({cur} of {total})")
            QApplication.processEvents()

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.viewer.load_session(data, progress=on_progress)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            QMessageBox.critical(self, "Load session", f"Could not load session:\n{e}")
            self.set_status(f"Could not load {os.path.basename(path)}: {e}")
            return
        finally:
            # Released on failure as well as on success - a stuck busy state
            # would leave the whole window dead.
            self.set_busy(False)
            self._progress.setRange(0, 0)
            self._set_inputs_enabled(True)
        self._refresh_ui_for_active_tab()
        self.viewer.set_current_tab_session_path(path)
        self._remember_file_session_link(self.viewer.current_tab_file_path(), path)
        self.set_status(f"Session loaded from {path}")
        if path in self._recent_sessions:
            self._recent_sessions.remove(path)
        self._recent_sessions.insert(0, path)
        self._recent_sessions = self._recent_sessions[:10]
        self._save_recent_sessions()
        self._update_recent_session_menu()

    def _save_recent_sessions(self):
        QSettings("Vellum", "Vellum").setValue("recentSessions", self._recent_sessions)

    # ------------------------------------------------------------------
    # File ↔ session association memory
    # ------------------------------------------------------------------

    def _remember_file_session_link(self, file_path: str, session_path: str):
        if not file_path or not session_path:
            return
        norm = os.path.normcase(os.path.abspath(file_path))
        self._file_session_map[norm] = session_path
        self._save_file_session_map()

    def _save_file_session_map(self):
        QSettings("Vellum", "Vellum").setValue(
            "fileSessionMap", json.dumps(self._file_session_map),
        )

    # ------------------------------------------------------------------
    # Tab events
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_tab_changed(self, idx: int):
        self._refresh_ui_for_active_tab()

    @Slot(int)
    def _on_tab_close_requested(self, idx: int):
        if self.viewer.tab_has_session_state(idx):
            tab_path = self.viewer.tab_file_path(idx) or "Untitled"
            reply = QMessageBox.question(
                self, "Close tab",
                f"Close “{os.path.basename(tab_path)}”?\n\n"
                "Unsaved measurements in this tab will be lost.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.viewer.close_tab(idx)

    def _refresh_ui_for_active_tab(self):
        """Sync all dependent panels (objects list, scale, origin, zoom, title, PDF nav)
        to reflect the current tab — call after a tab switch or session load."""
        self._rebuild_objects_list()

        has_document = self.viewer.current_tab_index >= 0
        self._stack.setCurrentWidget(self._workspace if has_document else self.home)

        if not has_document:
            self.setWindowTitle("Vellum")
            self._status_scale.setText("Scale: 1 px = 1 px")
            self._status_origin.setText("Origin: (0, 0)")
            self._status_zoom.setText("100%")
            self.set_status("")
            self._update_pdf_nav()
            return

        self.setWindowTitle(f"Vellum — {self.viewer.current_tab_label()}")

        si = self.viewer.scale_info
        self._status_scale.setText(f"Scale: 1 px = {si.scale_factor:.6g} {si.unit}")

        ox, oy = self.viewer._origin_world
        self._status_origin.setText(f"Origin: ({ox:.4g}, {oy:.4g})")

        pct = f"{self.viewer.zoom * 100:.0f}%"
        self._status_zoom.setText(pct)

        self._show_legend_act.blockSignals(True)
        self._show_legend_act.setChecked(self.viewer.legend_visible)
        self._show_legend_act.blockSignals(False)

        self._update_pdf_nav()

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _build_status_bar(self):
        sb = self.statusBar()

        self._status_msg = QLabel("")
        self._status_msg.setSizePolicy(QSizePolicy.Policy.Expanding,
                                       QSizePolicy.Policy.Preferred)
        sb.addWidget(self._status_msg, 1)

        # Exists only while something is running, and appears at its final
        # position rather than animating into place.
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        sb.addWidget(self._progress)

        # The live readout is a measurement, so it takes primary ink; the
        # rest of the bar is reference state and stays tertiary.
        self._status_live   = QLabel("")
        self._status_live.setProperty("role", "value")
        self._status_scale  = QLabel("Scale: 1 px = 1 px")
        self._status_origin = QLabel("Origin: (0, 0)")
        self._status_coords = QLabel("x: —  y: —")
        self._status_zoom   = QLabel("100%")

        # Rules go between unrelated segments only - never between a value
        # and the unit that gives it meaning.
        segments = [self._status_live, self._status_scale, self._status_origin,
                    self._status_coords, self._status_zoom]
        for i, widget in enumerate(segments):
            if i:
                sb.addPermanentWidget(ly.vseparator())
            sb.addPermanentWidget(widget)

    # ------------------------------------------------------------------
    # Status protocol - any child widget reaches this through window()
    # ------------------------------------------------------------------

    def set_status(self, message: str) -> None:
        """Say what just happened, in the user's terms."""
        self._status_msg.setText(message)

    def set_busy(self, busy: bool, message: str = "") -> None:
        """Show or clear the running indicator, and say what is running."""
        self._progress.setVisible(busy)
        if message:
            self._status_msg.setText(message)

    def _set_inputs_enabled(self, enabled: bool) -> None:
        """Enable or disable everything that could re-enter a running job."""
        self._toolbar.setEnabled(enabled)
        self.menuBar().setEnabled(enabled)
        self.right_panel.setEnabled(enabled)
        self.viewer.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Signal connections
    # ------------------------------------------------------------------

    def _connect_signals(self):
        self.viewer.scale_set.connect(self._on_scale_set)
        self.viewer.origin_set.connect(self._on_origin_set)
        self.viewer.mouse_world_pos.connect(self._on_mouse_pos)
        self.viewer.zoom_changed.connect(self._on_zoom_changed)
        self.viewer.live_measure.connect(self._status_live.setText)
        self.viewer.state_restored.connect(self._refresh_ui_for_active_tab)
        self.viewer.tool_change_requested.connect(self._set_tool)
        self.viewer.objects_changed.connect(self._rebuild_objects_list)
        self.viewer.selection_changed.connect(self._on_viewer_selection_changed)
        self.viewer.delete_requested.connect(self._on_delete_selected)

        self.right_panel.objects_list.itemSelectionChanged.connect(self._on_panel_selection_changed)
        self.right_panel.objects_list.itemDoubleClicked.connect(self._on_object_double_clicked)
        self.right_panel.objects_list.customContextMenuRequested.connect(self._on_list_context_menu)
        self.right_panel.del_obj_btn.clicked.connect(self._on_delete_selected)
        self.right_panel.clear_all_btn.clicked.connect(self._on_clear_all)
        self.right_panel.export_btn.clicked.connect(self.show_export)
        self.right_panel.move_up_btn.clicked.connect(self.viewer.move_selected_up)
        self.right_panel.move_down_btn.clicked.connect(self.viewer.move_selected_down)

        self.viewer.tab_changed.connect(self._on_tab_changed)
        self.viewer.tab_close_requested.connect(self._on_tab_close_requested)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot(Tool)
    def _set_tool(self, tool: Tool):
        self.viewer.set_tool(tool)
        act = self._tool_actions.get(tool)
        if act is not None and not act.isChecked():
            act.setChecked(True)
        self.set_status(TOOL_HELP[tool])

    @Slot(ScaleInfo)
    def _on_scale_set(self, si: ScaleInfo):
        text = f"1 px = {si.scale_factor:.6g} {si.unit}"
        self._status_scale.setText(f"Scale: {text}")
        self.set_status(f"Scale set: {text}")
        self._rebuild_objects_list()

    @Slot(Point)
    def _on_origin_set(self, pt: Point):
        ox, oy = self.viewer._origin_world
        self._status_origin.setText(f"Origin: ({ox:.4g}, {oy:.4g})")
        self.set_status(
            f"Origin set at image ({pt.x:.1f}, {pt.y:.1f}) "
            f"= world ({ox:.4g}, {oy:.4g})"
        )
        self._rebuild_objects_list()

    @Slot(float, float)
    def _on_mouse_pos(self, wx: float, wy: float):
        self._status_coords.setText(f"x: {wx:.4f}  y: {wy:.4f}")

    @Slot(float)
    def _on_zoom_changed(self, zoom: float):
        self._status_zoom.setText(f"{zoom * 100:.0f}%")

    # ------------------------------------------------------------------
    # Objects list (unified)
    # ------------------------------------------------------------------

    def _rebuild_objects_list(self):
        self._syncing_selection = True
        self.right_panel.objects_list.clear()
        for obj in self.viewer.objects:
            item = QListWidgetItem(icons.kind_icon(obj.kind),
                                   self._object_list_label(obj))
            self.right_panel.objects_list.addItem(item)
        ly.list_item_tooltips(self.right_panel.objects_list)
        for i in self.viewer._selection:
            item = self.right_panel.objects_list.item(i)
            if item:
                item.setSelected(True)
        self._syncing_selection = False
        self.right_panel.set_object_count(len(self.viewer.objects))
        self._refresh_action_state()

    def _refresh_action_state(self):
        """Keep the objects column and the tool palette honest about what applies."""
        has_objects = bool(self.viewer.objects)
        self.right_panel.set_action_state(has_objects,
                                          bool(self.viewer._selection))
        # Every measurement tool needs a document to draw on. Without one they
        # would stay clickable and do nothing.
        has_document = self.viewer.current_tab_index >= 0
        for action in self._tool_actions.values():
            action.setEnabled(has_document)

    def _object_list_label(self, obj: DiagramObject) -> str:
        # Points show their world coordinates; everything else uses the model's
        # own label (which already lists all of an object's measurements).
        if obj.kind == "point" and obj.points:
            name = obj.name if obj.name else "Point"
            wx, wy = self.viewer.img_to_world(QPointF(*obj.points[0]))
            return f"{name}  ({wx:.4f}, {wy:.4f})"
        return obj.list_label()

    # ------------------------------------------------------------------
    # Right-panel list context menu
    # ------------------------------------------------------------------

    def _on_list_context_menu(self, pos):
        item = self.right_panel.objects_list.itemAt(pos)
        menu = QMenu(self)

        if item is not None:
            idx = self.right_panel.objects_list.row(item)
            if idx not in self.viewer._selection:
                self.viewer.set_selection([idx])
                self.selection_changed_via_panel(idx)
            menu.addAction("Edit…", lambda: self.viewer.open_edit_dialog_for(idx))
            menu.addAction("Copy coordinates", lambda: self.viewer._copy_coordinates(idx))
            menu.addSeparator()

        sel = sorted(self.viewer._selection)
        copy_a = menu.addAction("Copy", self.viewer.copy_selection)
        paste_a = menu.addAction("Paste", lambda: self.viewer.paste())
        dup_a = menu.addAction("Duplicate", lambda: self.viewer.duplicate_selection())
        copy_a.setEnabled(bool(sel))
        paste_a.setEnabled(bool(self.viewer._clipboard))
        dup_a.setEnabled(bool(sel))

        if item is not None:
            menu.addSeparator()
            menu.addAction("Delete", lambda: self._delete_single(
                self.right_panel.objects_list.row(item)))

        menu.exec(self.right_panel.objects_list.mapToGlobal(pos))

    def selection_changed_via_panel(self, idx: int):
        """Sync right-panel list selection to a single row (used by context menu)."""
        self._syncing_selection = True
        self.right_panel.objects_list.clearSelection()
        item = self.right_panel.objects_list.item(idx)
        if item:
            item.setSelected(True)
        self._syncing_selection = False
        self.viewer.update()

    def _delete_single(self, idx: int):
        reply = QMessageBox.question(
            self, "Delete object", "Delete this object?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.viewer.set_selection([idx])
            self.viewer.delete_selected()

    # ------------------------------------------------------------------
    # Selection sync (two-way, guarded by _syncing_selection)
    # ------------------------------------------------------------------

    @Slot(list)
    def _on_viewer_selection_changed(self, indices: list):
        if self._syncing_selection:
            return
        self._syncing_selection = True
        self.right_panel.objects_list.clearSelection()
        for i in indices:
            item = self.right_panel.objects_list.item(i)
            if item:
                item.setSelected(True)
        self._syncing_selection = False
        self._refresh_action_state()

    def _on_panel_selection_changed(self):
        if self._syncing_selection:
            return
        rows = [self.right_panel.objects_list.row(item)
                for item in self.right_panel.objects_list.selectedItems()]
        self._syncing_selection = True
        self.viewer.set_selection(rows)
        self._syncing_selection = False
        self._refresh_action_state()
        self.viewer.update()

    def _on_object_double_clicked(self, item):
        idx = self.right_panel.objects_list.row(item)
        self.viewer.open_edit_dialog_for(idx)

    # ------------------------------------------------------------------
    # Delete / Clear
    # ------------------------------------------------------------------

    def _on_delete_selected(self):
        n = len(self.viewer._selection)
        if n == 0:
            return
        reply = QMessageBox.question(
            self, "Delete objects",
            f"Delete {n} selected object{'s' if n > 1 else ''}?\nThis can be undone with Ctrl+Z.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.viewer.delete_selected()

    def _on_clear_all(self):
        n = len(self.viewer.objects)
        if n == 0:
            return
        reply = QMessageBox.question(
            self, "Clear all",
            f"Delete all {n} object{'s' if n > 1 else ''}?\nThis can be undone with Ctrl+Z.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.viewer.clear_all_objects()

    # ------------------------------------------------------------------
    # Page navigation
    # ------------------------------------------------------------------

    def _go_prev_page(self):
        self.viewer.go_to_page(self.viewer.current_page - 1)
        self._update_pdf_nav()

    def _go_next_page(self):
        self.viewer.go_to_page(self.viewer.current_page + 1)
        self._update_pdf_nav()

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def new_document(self):
        """Ask for a page size, then open a blank page of it in a new tab."""
        name = f"Untitled {self._untitled_count + 1}"
        dlg = NewPageDialog(name, self)
        if dlg.exec() != NewPageDialog.DialogCode.Accepted:
            return
        w_px, h_px = dlg.pixel_size()
        doc = pages.blank_pdf(w_px, h_px, dlg.dpi())
        if self.viewer.open_blank_tab(doc, dlg.dpi(), dlg.page_name()) < 0:
            QMessageBox.warning(self, "New page", "Could not create the blank page.")
            return
        self._untitled_count += 1
        self._refresh_ui_for_active_tab()
        self.set_status(f"New page: {w_px:,} × {h_px:,} px at {dlg.dpi()} px/in")

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open image or PDF", self._last_open_dir,
            "Images & PDF (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.pdf);;All Files (*)",
        )
        if path:
            self._load_path(path)

    def _update_pdf_nav(self):
        count = self.viewer.pdf_page_count
        multi = count > 1
        for a in (self._pdf_sep, self._pdf_prev_act,
                  self._pdf_page_lbl_act, self._pdf_next_act):
            a.setVisible(multi)
        if multi:
            self._pdf_page_lbl.setText(f"{self.viewer.current_page + 1} / {count}")

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    def save_session(self):
        current = self.viewer.current_tab_session_path()
        if current and os.path.exists(current):
            self._do_save_session(current)
        else:
            self.save_session_as()

    def save_session_as(self):
        if self.viewer.current_tab_index < 0:
            QMessageBox.information(
                self, "Save session", "Open an image or PDF first.",
            )
            return
        start_dir = self.viewer.current_tab_session_path() or ""
        path, _ = QFileDialog.getSaveFileName(self, "Save session as", start_dir, "JSON Files (*.json)")
        if not path:
            return
        self._do_save_session(path)

    def _do_save_session(self, path: str):
        if self.viewer.current_tab_index < 0:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.viewer.session_data(), f, indent=2)
        except OSError as e:
            QMessageBox.critical(self, "Save session", f"Could not save session:\n{e}")
            return
        self.viewer.set_current_tab_session_path(path)
        self._remember_file_session_link(self.viewer.current_tab_file_path(), path)
        self.set_status(f"Session saved to {path}")
        if path in self._recent_sessions:
            self._recent_sessions.remove(path)
        self._recent_sessions.insert(0, path)
        self._recent_sessions = self._recent_sessions[:10]
        self._save_recent_sessions()
        self._update_recent_session_menu()

    def load_session(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load session", "", "JSON Files (*.json)")
        if path:
            self._do_load_session(path)

    # ------------------------------------------------------------------
    # Export / About
    # ------------------------------------------------------------------

    def show_export(self):
        to_world = lambda x, y: self.viewer.img_to_world(QPointF(x, y))
        ExportDialog(self.viewer.objects, to_world, self).exec()

    def export_view_image(self):
        if self.viewer.current_tab_index < 0:
            QMessageBox.information(self, "Export view", "Open an image or PDF first.")
            return
        tab_path = self.viewer.current_tab_file_path()
        base = os.path.splitext(os.path.basename(tab_path))[0] if tab_path else "view"
        start = os.path.join(self._last_open_dir, f"{base}.png") if self._last_open_dir else f"{base}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export view as image", start,
            "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;All Files (*)",
        )
        if not path:
            return
        pixmap = self.viewer.grab_canvas()
        if pixmap.isNull() or not pixmap.save(path):
            QMessageBox.critical(self, "Export view", f"Could not save image to:\n{path}")
            return
        self.set_status(f"View exported to {path}")

    def _font_resolver(self) -> FontResolver:
        """Installed fonts plus the bundled Inter, under the family name the
        canvas draws labels with. Built once: reading the font registry is
        not free."""
        if getattr(self, "_fonts", None) is None:
            self._fonts = FontResolver()
            for path in FONTS_DIR.glob("*.ttf"):
                self._fonts.register(T.FONT_FAMILY, str(path),
                                     italic="italic" in path.stem.lower())
        return self._fonts

    def export_markup_pdf(self):
        """Write the document with its markups as native PDF annotations that
        Bluebeam, Acrobat and other editors can edit. An image is placed on a
        PDF page first."""
        if self.viewer.current_tab_index < 0:
            QMessageBox.information(self, "Export PDF", "Open an image or PDF first.")
            return
        source = self.viewer.current_tab_file_path()
        if source:
            if not os.path.isfile(source):
                QMessageBox.information(self, "Export PDF", "The document's file is no longer on disk.")
                return
            base = os.path.splitext(os.path.basename(source))[0]
            start_dir = os.path.dirname(source)
        else:
            # A blank page lives only in memory; export it from its own bytes.
            source = self.viewer.current_tab_pdf_bytes()
            base = self.viewer.current_tab_label()
            start_dir = self._last_open_dir
        markup = self.viewer.export_pages()
        start = os.path.join(start_dir, f"{base} - markups.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Export as PDF with markups", start,
                                              "PDF Files (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        if isinstance(source, str) and \
                os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(source)):
            QMessageBox.warning(self, "Export PDF",
                                "Choose a different file: the open document can't be overwritten.")
            return
        self.set_busy(True, "Exporting PDF…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        report = error = None
        try:
            report = export_pdf(source, path, markup, self.viewer.current_tab_dpi(),
                                self.viewer.export_style(), self._font_resolver())
        except Exception as e:
            error = e
        finally:
            QApplication.restoreOverrideCursor()
        if error is not None:
            self.set_busy(False, "Export failed")
            QMessageBox.critical(self, "Export PDF", f"Could not export to:\n{path}\n\n{error}")
            return
        n = report.annotations
        self.set_busy(False, f"Exported {n} markup{'s' if n != 1 else ''} to {path}")
        if report.warnings:
            QMessageBox.warning(self, "Export PDF", "\n".join(report.warnings))

    def snapshot_view_to_clipboard(self):
        if self.viewer.current_tab_index < 0:
            QMessageBox.information(self, "Snapshot view", "Open an image or PDF first.")
            return
        pixmap = self.viewer.grab_canvas()
        if pixmap.isNull():
            QMessageBox.critical(self, "Snapshot view", "Could not capture the current view.")
            return
        QApplication.clipboard().setPixmap(pixmap)
        self.set_status("View copied to clipboard")

    def show_commands(self):
        """Every command and its shortcut, in one non-modal window."""
        if self._commands_dialog is None:
            self._commands_dialog = CommandsDialog(self.menuBar(), self)
        self._commands_dialog.show()
        self._commands_dialog.raise_()
        self._commands_dialog.activateWindow()

    def show_about(self):
        QMessageBox.about(
            self, "About Vellum",
            "<b>Vellum v2.0</b><br>"
            "Mark up images and PDFs: measurements, annotations and "
            "contours, to scale.<br><br>"
            "Features:<br>"
            "• Open images (PNG, JPEG, BMP, TIFF) and multi-page PDFs<br>"
            "• Start from a blank page: paper and screen presets, or any size and resolution<br>"
            "• Pan and zoom · middle-click or scroll · Zoom rectangle (Z)<br>"
            "• Set origin and scale (by distance or coordinates)<br>"
            "• Add labelled points, lines, angles, polygons, polylines, ellipses, text<br>"
            "• Draw polyline / point risk contours with merged same-label levels<br>"
            "• On-canvas legend (editable title) · toggle labels · per-object colours<br>"
            "• Annotations persist on canvas with labels<br>"
            "• Select, move, cut, copy and paste objects in pan / zoom mode<br>"
            "• Drag vertex handles directly when an object is selected<br>"
            "• Right-click a vertex to delete it · right-click an edge to insert<br>"
            "• Shift-lock to cardinal directions while measuring<br>"
            "• Double-click to finish polygon or polyline<br>"
            "• Undo and redo · save and load sessions · export CSV/JSON<br>"
            "• Export as PDF with native, editable markups<br><br>"
            "Built with PySide6 and PyMuPDF.",
        )

