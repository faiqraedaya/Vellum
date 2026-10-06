"""Render the app icon SVG to a multi-size Windows .ico for the exe.

    uv run python scripts/make_icon.py

The SVG is the source; run this again after changing it. Each size is
rendered from the vector rather than scaled from one bitmap, and stored as a
PNG entry, which every Windows since Vista reads.
"""
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

GUI = Path(__file__).resolve().parent.parent / "src" / "vellum" / "gui"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png_bytes(renderer: QSvgRenderer, size: int) -> bytes:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def main() -> None:
    app = QGuiApplication(sys.argv)  # noqa: F841 - QImage painting needs it
    renderer = QSvgRenderer(str(GUI / "vellum.svg"))
    images = [png_bytes(renderer, size) for size in SIZES]

    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    for size, data in zip(SIZES, images):
        dim = 0 if size >= 256 else size  # 0 means 256 in an ICO entry
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)

    out = GUI / "vellum.ico"
    out.write_bytes(header + entries + b"".join(images))
    print(f"Wrote {out} ({len(SIZES)} sizes)")


if __name__ == "__main__":
    main()
