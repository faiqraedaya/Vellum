"""
The application's single icon family.

One set, one stroke weight, one size. The glyphs are Lucide geometry drawn on
Lucide's native 24 px grid and rendered down to the 16 px icon token, with the
stroke widened to 2.25 so it lands at exactly 1.5 px once scaled.

Icons are tinted from the ink ladder rather than shipped as coloured assets,
so a new rung in ``theme.py`` reaches them without touching artwork. A toolbar
icon is neutral: the measurement colours belong to the marks on the canvas,
not to the buttons that place them. No icon here is the sole carrier of its
meaning - every one has a tooltip naming the tool and its shortcut, and a
labelled twin in the Tools menu.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ..core.constants import Tool
from .theme import Tokens

# Lucide paths on a 24x24 grid. Keep new entries in the same idiom: round
# caps and joins, geometric construction, no fills.
_GLYPHS = {
    # -- Navigation / view --------------------------------------------------
    "move": (
        '<path d="M12 2v20"/><path d="M2 12h20"/>'
        '<path d="m15 19-3 3-3-3"/><path d="m9 5 3-3 3 3"/>'
        '<path d="m19 9 3 3-3 3"/><path d="m5 9-3 3 3 3"/>'
    ),
    "pointer": (
        '<path d="M4.04 4.69a.5.5 0 0 1 .65-.65l16 6.5a.5.5 0 0 1-.06.95'
        'l-6.12 1.58a2 2 0 0 0-1.44 1.43l-1.58 6.13a.5.5 0 0 1-.95.06z"/>'
    ),
    "scan-search": (
        '<path d="M3 7V5a2 2 0 0 1 2-2h2"/>'
        '<path d="M17 3h2a2 2 0 0 1 2 2v2"/>'
        '<path d="M21 17v2a2 2 0 0 1-2 2h-2"/>'
        '<path d="M7 21H5a2 2 0 0 1-2-2v-2"/>'
        '<circle cx="11" cy="11" r="3"/><path d="m16 16-2.8-2.8"/>'
    ),

    # -- Setup --------------------------------------------------------------
    "crosshair": (
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M21 12h-4"/><path d="M7 12H3"/>'
        '<path d="M12 7V3"/><path d="M12 21v-4"/>'
    ),
    "ruler": (
        '<path d="M21.3 8.7 8.7 21.3a1 1 0 0 1-1.4 0l-4.6-4.6a1 1 0 0 1 0-1.4'
        'L15.3 2.7a1 1 0 0 1 1.4 0l4.6 4.6a1 1 0 0 1 0 1.4Z"/>'
        '<path d="m7.5 10.5 2 2"/><path d="m10.5 7.5 2 2"/>'
        '<path d="m13.5 4.5 2 2"/><path d="m4.5 13.5 2 2"/>'
    ),
    "axes": (
        '<path d="M4 21V3"/><path d="m1.5 5.5 2.5-3 2.5 3"/>'
        '<path d="M3 20h18"/><path d="m18.5 17.5 3 2.5-3 2.5"/>'
        '<circle cx="14" cy="10" r="2"/>'
    ),

    # -- Measurement objects ------------------------------------------------
    "circle-dot": (
        '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="1.5"/>'
    ),
    "segment": (
        '<circle cx="5" cy="19" r="2.5"/><circle cx="19" cy="5" r="2.5"/>'
        '<path d="M7 17 17 7"/>'
    ),
    "angle": (
        '<path d="M3 20h18"/><path d="M3 20 17 6"/>'
        '<path d="M10 20a7 7 0 0 0-2.05-4.95"/>'
    ),
    "pentagon": (
        '<path d="M10.83 2.38a2 2 0 0 1 2.34 0l8 5.74a2 2 0 0 1 .73 2.25'
        'l-3.04 9.26a2 2 0 0 1-1.9 1.37H7.04a2 2 0 0 1-1.9-1.37L2.1 10.37'
        'a2 2 0 0 1 .73-2.25z"/>'
    ),
    "waypoints": (
        '<path d="m4 17 5-7 5 5 6-9"/>'
        '<circle cx="4" cy="17" r="1.75"/><circle cx="20" cy="6" r="1.75"/>'
    ),
    "ellipse": '<ellipse cx="12" cy="12" rx="9.5" ry="6.5"/>',
    "type": (
        '<path d="M12 4v16"/><path d="M4 7V5h16v2"/><path d="M9 20h6"/>'
    ),
    "target": (
        '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/>'
        '<circle cx="12" cy="12" r="1.5"/>'
    ),
    "path-offset": (
        '<path d="m3 12 5-6 4 4 6.5-7"/><path d="m3 20 5-6 4 4 6.5-7"/>'
    ),

    # -- File / document ----------------------------------------------------
    "file-plus": (
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
        '<path d="M9 15h6"/><path d="M12 18v-6"/>'
    ),
    "folder-open": (
        '<path d="m6 14 1.45-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5'
        'l-1.55 6a2 2 0 0 1-1.94 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.93'
        'a2 2 0 0 1 1.66.9l.82 1.2a2 2 0 0 0 1.66.9H18a2 2 0 0 1 2 2v2"/>'
    ),
    "save": (
        '<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19'
        'a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/>'
        '<path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"/>'
        '<path d="M7 3v4a1 1 0 0 0 1 1h7"/>'
    ),
    "download": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>'
    ),
    "help": (
        '<circle cx="12" cy="12" r="10"/>'
        '<path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>'
    ),
    "close": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-up": '<path d="m18 15-6-6-6 6"/>',
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
}

_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="none" stroke="{colour}" stroke-width="2.25" '
    'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
)

# Which glyph stands for which tool. One entry per Tool member, so a tool with
# no glyph raises at import rather than showing a blank button at runtime.
_TOOL_GLYPH = {
    Tool.PAN: "move",
    Tool.SELECT: "pointer",
    Tool.ZOOM_RECT: "scan-search",
    Tool.SET_ORIGIN: "crosshair",
    Tool.SET_SCALE_DISTANCE: "ruler",
    Tool.SET_SCALE_COORDS: "axes",
    Tool.ADD_POINT: "circle-dot",
    Tool.ADD_LINE: "segment",
    Tool.ADD_ANGLE: "angle",
    Tool.ADD_POLYGON: "pentagon",
    Tool.ADD_POLYLINE: "waypoints",
    Tool.ADD_ELLIPSE: "ellipse",
    Tool.ADD_TEXTBOX: "type",
    Tool.ADD_POINT_CONTOUR: "target",
    Tool.ADD_POLYLINE_CONTOUR: "path-offset",
}

_ACTION_GLYPH = {
    "new": "file-plus",
    "open": "folder-open",
    "save": "save",
    "export": "download",
    "prev": "chevron-left",
    "next": "chevron-right",
}


def _pixmap(name: str, colour: str, size: int, ratio: float) -> QPixmap:
    """Render one glyph at the given device pixel ratio."""
    svg = _SVG.format(colour=colour, body=_GLYPHS[name])
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))

    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    # Render into an explicit logical rect: with no target given, the SVG is
    # laid out against the pixmap's device rect and the glyph overflows its
    # box by the device pixel ratio.
    renderer.setAspectRatioMode(Qt.KeepAspectRatio)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


def pixmap(name: str, colour: str, *, size: int = 0,
           ratio: float = 2.0) -> QPixmap:
    """One glyph, at one ink rung, for callers that need a bare pixmap."""
    if name not in _GLYPHS:
        raise KeyError(
            f"No '{name}' in the icon set. Add it to _GLYPHS in Lucide's "
            f"idiom, or use a text label - never reach for a second family."
        )
    return _pixmap(name, colour, size or Tokens.ICON_SIZE, ratio)


def icon(name: str, *, size: int = 0, ratio: float = 2.0) -> QIcon:
    """An icon that sits at glyph alpha and promotes when active.

    Qt picks the ``On`` pixmap for a checked button and the ``Active`` one
    under the mouse, so the selected tool's icon darkens with its fill
    instead of staying flat while the button around it changes.
    """
    if name not in _GLYPHS:
        raise KeyError(
            f"No '{name}' in the icon set. Add it to _GLYPHS in Lucide's "
            f"idiom, or use a text label - never reach for a second family."
        )
    size = size or Tokens.ICON_SIZE
    rest = Tokens.ink_hex(Tokens.INK_GLYPH)
    active = Tokens.ink_hex(Tokens.INK_SECONDARY)
    selected = Tokens.ink_hex(Tokens.INK_PRIMARY)

    result = QIcon()
    result.addPixmap(_pixmap(name, rest, size, ratio), QIcon.Normal, QIcon.Off)
    result.addPixmap(_pixmap(name, active, size, ratio), QIcon.Active, QIcon.Off)
    result.addPixmap(_pixmap(name, selected, size, ratio), QIcon.Normal, QIcon.On)
    result.addPixmap(_pixmap(name, selected, size, ratio), QIcon.Active, QIcon.On)
    # A selected row gets its own pixmap: left to itself Qt generates one by
    # blending the icon with the highlight colour, which puts a blue-tinted
    # glyph in a set that is otherwise entirely ink.
    result.addPixmap(_pixmap(name, selected, size, ratio), QIcon.Selected, QIcon.Off)
    result.addPixmap(_pixmap(name, selected, size, ratio), QIcon.Selected, QIcon.On)
    result.addPixmap(_pixmap(name, Tokens.ink_hex(Tokens.INK_DISABLED), size, ratio),
                     QIcon.Disabled, QIcon.Off)
    return result


# Which glyph stands for which kind of placed object, so a list row shows
# its kind in the same family as everything else.
_KIND_GLYPH = {
    "point": "circle-dot",
    "distance": "segment",
    "angle": "angle",
    "polygon": "pentagon",
    "polyline": "waypoints",
    "ellipse": "ellipse",
    "textbox": "type",
    "polyline_contour": "path-offset",
    "point_contour": "target",
}


def _app_icon_path() -> Path:
    beside_module = Path(__file__).parent / "vellum.svg"
    if beside_module.is_file():
        return beside_module
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "vellum" / "gui" / "vellum.svg"
    return beside_module


def app_icon() -> QIcon:
    """The application icon, the one asset that keeps its own colours.

    Rendered to a pixmap per size rather than handed to QIcon as a file, so
    it does not depend on Qt's SVG icon-engine plugin being in the bundle.
    """
    renderer = QSvgRenderer(str(_app_icon_path()))
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        result.addPixmap(pixmap)
    return result


def kind_icon(kind: str) -> QIcon:
    """The icon for a placed object of `kind`, for the objects list."""
    return icon(_KIND_GLYPH[kind])


def tool_icon(tool: Tool) -> QIcon:
    """The icon for a measurement tool."""
    return icon(_TOOL_GLYPH[tool])


def action_icon(name: str) -> QIcon:
    """The icon for a file or navigation action."""
    return icon(_ACTION_GLYPH[name])
