"""Visual theme: Fusion style, light/dark palettes, stylesheet and line icons."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Colors:
    dark: bool
    window: str
    surface: str  # cards, inputs
    surface_alt: str  # alternating rows, headers
    border: str
    text: str
    muted: str
    accent: str
    accent_text: str
    ok: str
    warn: str
    error: str
    hex_ff: str
    hex_addr: str


LIGHT = Colors(
    dark=False, window="#f3f4f6", surface="#ffffff", surface_alt="#f7f8fa", border="#dfe2e7",
    text="#1f2328", muted="#6b7280", accent="#2563eb", accent_text="#ffffff",
    ok="#16a34a", warn="#d97706", error="#dc2626", hex_ff="#b4bac4", hex_addr="#2563eb",
)
DARK = Colors(
    dark=True, window="#17191d", surface="#1f2227", surface_alt="#25292f", border="#33383f",
    text="#e6e8eb", muted="#9aa1ab", accent="#4f8cff", accent_text="#ffffff",
    ok="#3fb950", warn="#e3a008", error="#f85149", hex_ff="#5b626c", hex_addr="#6ea2ff",
)

colors: Colors = LIGHT


def _system_is_dark() -> bool:
    hints = QGuiApplication.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    return scheme is not None and scheme() == Qt.ColorScheme.Dark


def apply(app: QApplication) -> Colors:
    global colors
    colors = DARK if _system_is_dark() else LIGHT
    c = colors
    app.setStyle("Fusion")

    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: c.window,
        QPalette.ColorRole.WindowText: c.text,
        QPalette.ColorRole.Base: c.surface,
        QPalette.ColorRole.AlternateBase: c.surface_alt,
        QPalette.ColorRole.Text: c.text,
        QPalette.ColorRole.Button: c.surface,
        QPalette.ColorRole.ButtonText: c.text,
        QPalette.ColorRole.Highlight: c.accent,
        QPalette.ColorRole.HighlightedText: c.accent_text,
        QPalette.ColorRole.ToolTipBase: c.surface,
        QPalette.ColorRole.ToolTipText: c.text,
        QPalette.ColorRole.PlaceholderText: c.muted,
        QPalette.ColorRole.Link: c.accent,
        QPalette.ColorRole.Mid: c.border,
        QPalette.ColorRole.Midlight: c.surface_alt,
    }
    for role, value in roles.items():
        pal.setColor(role, QColor(value))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(c.muted))
    app.setPalette(pal)
    app.setStyleSheet(_stylesheet(c, _arrow_file(c.muted)))
    return c


def _arrow_file(color: str) -> str:
    """Stylesheets can only load images from files, so write the combo arrow to one."""
    path = Path(tempfile.gettempdir()) / f"ezp-programmer-arrow-{color.lstrip('#')}.svg"
    if not path.exists():
        path.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12"><path d="M3 4.5l3 3 3-3" '
            f'fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
            "utf-8",
        )
    return path.as_posix()


def _stylesheet(c: Colors, arrow: str) -> str:
    return f"""
    QMainWindow, QDialog {{ background: {c.window}; }}
    QToolTip {{ background: {c.surface}; color: {c.text}; border: 1px solid {c.border}; padding: 4px 6px; }}

    QToolBar {{ background: {c.surface}; border: none; border-bottom: 1px solid {c.border}; padding: 4px 8px; spacing: 2px; }}
    QToolBar::separator {{ background: {c.border}; width: 1px; margin: 6px 6px; }}
    QToolButton {{ border: 1px solid transparent; border-radius: 6px; padding: 4px 8px; color: {c.text}; }}
    QToolButton:hover {{ background: {c.surface_alt}; border-color: {c.border}; }}
    QToolButton:pressed {{ background: {c.border}; }}
    QToolButton:disabled {{ color: {c.muted}; }}
    QToolButton#primary {{ background: {c.accent}; color: {c.accent_text}; }}
    QToolButton#primary:hover {{ background: {QColor(c.accent).lighter(112).name()}; }}
    QToolButton#primary:disabled {{ background: {c.surface_alt}; color: {c.muted}; }}

    QMenuBar {{ background: {c.surface}; }}
    QMenuBar::item {{ padding: 4px 10px; background: transparent; }}
    QMenuBar::item:selected {{ background: {c.surface_alt}; border-radius: 4px; }}
    QMenu {{ background: {c.surface}; border: 1px solid {c.border}; padding: 4px; }}
    QMenu::item {{ padding: 5px 24px 5px 20px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {c.accent}; color: {c.accent_text}; }}
    QMenu::separator {{ height: 1px; background: {c.border}; margin: 4px 8px; }}

    QFrame#card {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 10px; }}
    QLabel#cardTitle {{ color: {c.muted}; font-weight: 600; letter-spacing: 0.5px; }}
    QLabel#muted {{ color: {c.muted}; }}
    QLabel#chipName {{ font-size: 15px; font-weight: 600; }}
    QLabel#pill {{ border-radius: 10px; padding: 2px 10px; font-weight: 600; }}

    QLineEdit, QComboBox, QSpinBox {{
        background: {c.surface}; border: 1px solid {c.border}; border-radius: 6px; padding: 4px 8px; min-height: 20px;
    }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {c.accent}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox::down-arrow {{ image: url({arrow}); width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{ background: {c.surface}; border: 1px solid {c.border}; selection-background-color: {c.accent}; }}

    QListWidget {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 6px; padding: 2px; outline: none; }}
    QListWidget::item {{ padding: 4px 6px; border-radius: 4px; }}
    QListWidget::item:hover {{ background: {c.surface_alt}; }}
    QListWidget::item:selected {{ background: {c.accent}; color: {c.accent_text}; }}

    QTableView {{ background: {c.surface}; alternate-background-color: {c.surface_alt}; border: none;
                  selection-background-color: {c.accent}; selection-color: {c.accent_text}; gridline-color: {c.border}; }}
    QHeaderView::section {{ background: {c.surface_alt}; color: {c.muted}; border: none;
                            border-bottom: 1px solid {c.border}; padding: 3px 4px; }}
    QTableCornerButton::section {{ background: {c.surface_alt}; border: none; border-bottom: 1px solid {c.border}; }}

    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{ background: transparent; color: {c.muted}; padding: 4px 12px; margin-right: 4px;
                    border: none; border-bottom: 2px solid transparent; font-weight: 600; }}
    QTabBar::tab:selected {{ color: {c.text}; border-bottom-color: {c.accent}; }}
    QTabBar::tab:hover {{ color: {c.text}; }}
    QPushButton {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 6px; padding: 4px 12px; }}
    QPushButton:hover {{ background: {c.surface_alt}; }}

    QPlainTextEdit#log {{ background: {c.surface}; border: none; color: {c.text}; padding: 4px; }}

    QSplitter::handle {{ background: transparent; }}
    QSplitter::handle:horizontal {{ width: 8px; }}
    QSplitter::handle:vertical {{ height: 8px; }}

    QStatusBar {{ background: {c.surface}; border-top: 1px solid {c.border}; color: {c.muted}; }}
    QStatusBar::item {{ border: none; }}
    QProgressBar {{ background: {c.surface_alt}; border: 1px solid {c.border}; border-radius: 6px;
                    text-align: center; min-height: 16px; color: {c.text}; }}
    QProgressBar::chunk {{ background: {c.accent}; border-radius: 5px; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle {{ background: {c.border}; border-radius: 3px; min-height: 24px; min-width: 24px; }}
    QScrollBar::handle:hover {{ background: {c.muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}
    """


# ---------------------------------------------------------------- icons
# Simple 24x24 line icons drawn for this app (stroke = currentColor).

_ICONS = {
    "plug": '<path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0zM12 18v4"/>',
    "unplug": '<path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0zM12 18v4M3 3l18 18"/>',
    "open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "save": '<path d="M5 3h11l4 4v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 1-2zM8 3v5h7V3M8 21v-7h8v7"/>',
    "detect": '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
    "read": '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
    "write": '<path d="M12 15V3M7 8l5-5 5 5M5 21h14"/>',
    "verify": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    "erase": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    "blank": '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6"/>',
    "auto": '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    "cancel": '<circle cx="12" cy="12" r="9"/><path d="M15 9l-6 6M9 9l6 6"/>',
    "chip": '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
}


def icon(name: str, color: str | None = None, size: int = 20) -> QIcon:
    col = color or colors.text
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{col}" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{_ICONS[name]}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    result = QIcon()
    for scale in (1, 2):
        pm = QPixmap(QSize(size * scale, size * scale))
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        renderer.render(painter, QRectF(0, 0, size * scale, size * scale))
        painter.end()
        pm.setDevicePixelRatio(scale)
        result.addPixmap(pm)
    return result


def mono_font():
    from PySide6.QtGui import QFont, QFontDatabase

    for family in ("Consolas", "Cascadia Mono", "DejaVu Sans Mono", "Menlo"):
        if family in QFontDatabase.families():
            font = QFont(family)
            font.setStyleHint(QFont.StyleHint.Monospace)
            return font
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)


def app_icon() -> QIcon:
    return icon("chip", colors.accent, 64)
