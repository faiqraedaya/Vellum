"""The objects column: everything placed on the current document, in order."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from . import layout as ly
from .theme import Tokens as T


class RightPanel(QWidget):
    """Right column: the unified objects list with selection and reordering.

    No group box: this column already sits in its own pane beside the canvas,
    and a second outline around the same content would put three boundaries on
    one list. A heading plus spacing groups it without drawing another line.
    """

    # Derived from the widest row this panel has to hold without clipping:
    # the two delete buttons side by side plus the window's group margins.
    MIN_WIDTH = 288

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(self.MIN_WIDTH)

        outer = ly.vbox(self, margin=0, spacing=T.SPACING_ROW)

        outer.addWidget(ly.heading("Objects"))
        self.count_label = ly.caption("")
        outer.addWidget(self.count_label)

        self.objects_list = ly.list_widget(
            empty_text="Measurements you place appear here.\n"
                       "Pick a tool from the toolbar to add one."
        )
        self.objects_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.objects_list.setToolTip(
            "Click to select · Ctrl+click to toggle · Shift+click for range\n"
            "Double-click to edit · Right-click for the context menu"
        )
        outer.addWidget(self.objects_list, 1)

        # Reordering acts on the list directly above it, so it sits tight to
        # it; the destructive pair and the export action are further away.
        move_row = ly.hbox()
        self.move_up_btn = ly.button("Move up", tooltip="Move the selection earlier in the drawing order")
        self.move_down_btn = ly.button("Move down", tooltip="Move the selection later in the drawing order")
        move_row.addWidget(self.move_up_btn)
        move_row.addWidget(self.move_down_btn)
        outer.addLayout(move_row)

        del_row = ly.hbox()
        self.del_obj_btn = ly.button("Delete selected", variant="danger")
        self.clear_all_btn = ly.button("Delete all", variant="danger")
        del_row.addWidget(self.del_obj_btn)
        del_row.addWidget(self.clear_all_btn)
        outer.addLayout(del_row)

        outer.addSpacing(T.SPACING_ROW)
        self.export_btn = ly.button("Export…", variant="primary",
                                    tooltip="Export every object as CSV or JSON  (Ctrl+E)")
        outer.addLayout(ly.action_row(self.export_btn))

    def set_object_count(self, count: int) -> None:
        """Say how many objects the list holds, once there are any.

        Empty, it says nothing: the list's own empty state is directly below
        and says more.
        """
        self.count_label.setText(
            f"{count} object{'s' if count != 1 else ''}" if count else "")
        self.count_label.setVisible(bool(count))

    def set_action_state(self, has_objects: bool, has_selection: bool) -> None:
        """Disable the actions that have nothing to act on.

        A live button that silently does nothing is a trap; hiding it instead
        would make the column jump every time the selection changed. Each
        disabled button says in its tooltip what would make it available.
        """
        for button in (self.move_up_btn, self.move_down_btn, self.del_obj_btn):
            button.setEnabled(has_selection)
        for button in (self.clear_all_btn, self.export_btn):
            button.setEnabled(has_objects)

        selection_reason = "Select an object in the list or on the drawing first"
        self.move_up_btn.setToolTip(
            "Move the selection earlier in the drawing order"
            if has_selection else selection_reason)
        self.move_down_btn.setToolTip(
            "Move the selection later in the drawing order"
            if has_selection else selection_reason)
        self.del_obj_btn.setToolTip(
            "Delete the selected objects  (Del)"
            if has_selection else selection_reason)
        self.clear_all_btn.setToolTip(
            "Delete every object on this document"
            if has_objects else "There is nothing to delete yet")
        self.export_btn.setToolTip(
            "Export every object as CSV or JSON  (Ctrl+E)"
            if has_objects else "There is nothing to export yet")
