"""The Commands window: every command in the program, with its shortcut."""

from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QDialog, QLineEdit, QMenu, QMenuBar

from ..core.constants import CANVAS_GESTURES
from . import layout as ly
from .theme import Tokens as T


def _clean(text: str) -> str:
    """A menu label as the user reads it: no mnemonic ampersands or ellipsis."""
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&").rstrip("…").strip()


def menu_commands(menu_bar: QMenuBar) -> list[tuple[str, str, str]]:
    """(Command, shortcut, where) for every action in the menu bar.

    Read from the menus themselves rather than kept as a second list, so a
    command added to a menu shows up here without anyone remembering to.
    Submenus whose entries are file paths (the recent lists) are skipped:
    they are history, not commands.
    """
    rows = []

    def walk(menu: QMenu, where: str):
        for action in menu.actions():
            if action.isSeparator() or not action.text():
                continue
            sub = action.menu()
            if sub is not None:
                if "recent" not in action.text().lower():
                    walk(sub, f"{where} › {_clean(action.text())}")
                continue
            shortcut = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            rows.append((_clean(action.text()), shortcut, where))

    for top in menu_bar.actions():
        if top.menu() is not None:
            walk(top.menu(), _clean(top.text()))
    return rows


class CommandsDialog(QDialog):
    """A filterable list of every command, its shortcut, and where it lives."""

    _HEADERS = ["Command", "Shortcut", "Where"]

    def __init__(self, menu_bar: QMenuBar, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Commands")
        # Wide enough for the longest command beside its shortcut and menu
        # without eliding; tall enough to show a full menu at once.
        self.setMinimumSize(640, 520)
        self.resize(720, 640)

        self._rows = menu_commands(menu_bar) + [
            (command, gesture, "Canvas") for command, gesture in CANVAS_GESTURES
        ]

        layout = ly.window_layout(self)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by command, shortcut or menu")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setMinimumHeight(T.CONTROL_HEIGHT)
        self.filter_edit.textChanged.connect(self._apply_filter)
        layout.addWidget(self.filter_edit)

        self.table = ly.results_table(
            self._HEADERS,
            empty_text="No command matches that filter. Clear it to see them all.",
        )
        layout.addWidget(self.table, 1)

        self.count = ly.caption("")
        layout.addWidget(self.count)

        close_btn = ly.button("Close", on_click=self.accept)
        row = ly.hbox()
        row.addStretch()
        row.addWidget(close_btn)
        layout.addLayout(row)

        self._apply_filter("")
        self.filter_edit.setFocus()

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        rows = [r for r in self._rows
                if not needle or any(needle in cell.lower() for cell in r)]
        ly.fill_table(self.table, rows)
        total = len(self._rows)
        self.count.setText(f"{total} commands" if len(rows) == total
                           else f"{len(rows)} of {total} commands")
