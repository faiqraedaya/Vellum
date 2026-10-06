"""The home page, shown whenever no document is open."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QSizePolicy, QToolButton, QWidget

from . import icons
from . import layout as ly
from .theme import Tokens as T

# Every card is the same size, so the row reads as three equal choices.
# Wide enough for the longest title at label size with the card's padding.
_CARD_W = 168
_CARD_H = 112


def _card(title: str, glyph: str, tooltip: str, on_click) -> QToolButton:
    card = QToolButton()
    card.setProperty("variant", "card")
    card.setText(title)
    card.setIcon(icons.icon(glyph))
    card.setIconSize(QSize(T.ICON_SIZE, T.ICON_SIZE))
    card.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    card.setToolTip(tooltip)
    card.setMinimumSize(_CARD_W, _CARD_H)
    card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    card.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    card.setCursor(Qt.CursorShape.PointingHandCursor)
    card.clicked.connect(on_click)
    return card


class HomePage(QWidget):
    """Welcome, and the three ways to start: a blank page, a file, or help."""

    new_requested = Signal()
    open_requested = Signal()
    help_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homePage")

        outer = ly.vbox(self, margin=T.MARGIN_WINDOW, spacing=0)
        outer.addStretch(2)

        title = ly.title("Welcome to Vellum")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(title)
        outer.addSpacing(T.SPACING_ROW)

        subtitle = ly.caption("Mark up images and PDFs, to scale.")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(subtitle)
        outer.addSpacing(T.SPACING_SECTION)

        self.new_card = _card("New", "file-plus",
                              "Create a blank page  (Ctrl+N)",
                              self.new_requested.emit)
        self.open_card = _card("Open", "folder-open",
                               "Open an image or PDF  (Ctrl+O)",
                               self.open_requested.emit)
        self.help_card = _card("Help", "help",
                               "List every command and shortcut  (F1)",
                               self.help_requested.emit)

        row = ly.hbox(spacing=T.MARGIN_GROUP)
        row.addStretch()
        for card in (self.new_card, self.open_card, self.help_card):
            row.addWidget(card)
        row.addStretch()
        outer.addLayout(row)

        outer.addStretch(3)
