"""Regenerate packaging/icon.ico from the app's chip icon.

    uv run --with pillow python packaging/make_icon.py
"""

import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, QSize
from PySide6.QtGui import QGuiApplication

from ezp_programmer import theme

app = QGuiApplication(sys.argv)
pixmap = theme.icon("chip", theme.LIGHT.accent, 256).pixmap(QSize(256, 256))
buf = QBuffer()
buf.open(QIODevice.OpenModeFlag.WriteOnly)
pixmap.toImage().save(buf, "PNG")
image = Image.open(io.BytesIO(bytes(buf.data())))
out = Path(__file__).with_name("icon.ico")
image.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(f"wrote {out}")
