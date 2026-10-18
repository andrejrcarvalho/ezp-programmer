"""Render the EZP Programmer icon (PNG + multi-size ICO) with Qt.

    uv run --group build python packaging/make_icon.py
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPen,
)

app = QGuiApplication(sys.argv[:1])
OUT = Path(__file__).resolve().parents[1] / "src" / "ezp_programmer" / "assets"


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256

    # Tile: blue gradient rounded square
    tile = QRectF(8 * s, 8 * s, 240 * s, 240 * s)
    grad = QLinearGradient(tile.topLeft(), tile.bottomRight())
    grad.setColorAt(0, QColor("#3b82f6"))
    grad.setColorAt(1, QColor("#1d4ed8"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(tile, 52 * s, 52 * s)

    # Chip: SOIC-8 body with 4 pins per side
    body = QRectF(70 * s, 58 * s, 116 * s, 140 * s)
    pin_w, pin_h, pin_len = 34 * s, 14 * s, 0
    p.setBrush(QColor("#e5e7eb"))
    for i in range(4):
        y = body.top() + (22 + i * 32) * s
        p.drawRoundedRect(QRectF(body.left() - pin_w + 6 * s, y, pin_w, pin_h), 3 * s, 3 * s)
        p.drawRoundedRect(QRectF(body.right() - 6 * s, y, pin_w, pin_h), 3 * s, 3 * s)
    p.setBrush(QColor("#111827"))
    p.setPen(QPen(QColor("#0b1220"), 3 * s))
    p.drawRoundedRect(body, 12 * s, 12 * s)

    # Pin-1 marker
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#facc15"))
    p.drawEllipse(QPointF(body.left() + 22 * s, body.top() + 22 * s), 9 * s, 9 * s)

    # Label + a "data" bar, only where it stays legible
    if size >= 48:
        font = QFont("Segoe UI", -1, QFont.Weight.Black)
        font.setPixelSize(max(1, int(34 * s)))
        p.setFont(font)
        p.setPen(QColor("#f9fafb"))
        p.drawText(body.adjusted(0, 18 * s, 0, 0), Qt.AlignmentFlag.AlignCenter, "EZP")
        p.setPen(QPen(QColor("#22d3ee"), 6 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(body.left() + 26 * s, body.bottom() - 26 * s), QPointF(body.right() - 26 * s, body.bottom() - 26 * s))
    p.end()
    return img


def to_pil(img: QImage) -> Image.Image:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    import io

    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")


OUT.mkdir(parents=True, exist_ok=True)
render(512).save(str(OUT / "ezp-programmer.png"))
sizes = [16, 24, 32, 48, 64, 128, 256]
frames = [to_pil(render(sz)) for sz in sizes]  # render each size natively for crisp small icons
frames[-1].save(OUT / "ezp-programmer.ico", sizes=[(sz, sz) for sz in sizes], append_images=frames[:-1])
print(f"wrote {OUT / 'ezp-programmer.png'} and .ico")
