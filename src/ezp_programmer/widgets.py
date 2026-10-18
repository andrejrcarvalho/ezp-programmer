"""Supporting widgets: find bar, range dialog, analysis and difference panels."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .analysis import Block, Finding
from .chips import format_size


def parse_int(text: str) -> int:
    """Parse ``0x1F``, ``1F`` (hex by default), ``#123`` (decimal) or ``64K`` / ``1M``."""
    t = text.strip().replace("_", "").replace(" ", "")
    if not t:
        raise ValueError("empty")
    mult = 1
    if t[-1] in "kK":
        mult, t = 1024, t[:-1]
    elif t[-1] in "mM":
        mult, t = 1024 * 1024, t[:-1]
    if t.startswith("#"):
        return int(t[1:], 10) * mult
    if mult != 1:
        return int(t, 0) * mult if t.lower().startswith("0x") else int(t, 10) * mult
    return int(t, 16)


def parse_pattern(text: str, mode: str) -> bytes:
    if mode == "Text":
        return text.encode("latin-1", errors="replace")
    clean = "".join(text.split()).removeprefix("0x")
    if len(clean) % 2:
        raise ValueError("hex needs an even number of digits")
    return bytes.fromhex(clean)


class FindBar(QWidget):
    """Find / replace strip shown above the hex view (Ctrl+F)."""

    find_requested = Signal(bytes, bool)  # pattern, forward
    replace_requested = Signal(bytes, bytes, bool)  # pattern, replacement, all
    closed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["Hex", "Text"])
        self.txt_find = QLineEdit(placeholderText="Find (e.g. 55 AA or text)")
        self.txt_replace = QLineEdit(placeholderText="Replace with (same length)")
        self.lbl_msg = QLabel(objectName="muted")
        b_prev, b_next = QToolButton(text="◀"), QToolButton(text="▶")
        b_prev.setToolTip("Previous match (Shift+Enter)")
        b_next.setToolTip("Next match (Enter)")
        b_rep, b_all = QPushButton("Replace"), QPushButton("Replace all")
        b_close = QToolButton(text="✕")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        for w in (self.cmb_mode, self.txt_find, b_prev, b_next, self.txt_replace, b_rep, b_all, self.lbl_msg):
            lay.addWidget(w)
        lay.addStretch(1)
        lay.addWidget(b_close)
        self.txt_find.setMinimumWidth(180)
        self.txt_replace.setMinimumWidth(160)

        b_next.clicked.connect(lambda: self._find(True))
        b_prev.clicked.connect(lambda: self._find(False))
        self.txt_find.returnPressed.connect(lambda: self._find(True))
        b_rep.clicked.connect(lambda: self._replace(False))
        b_all.clicked.connect(lambda: self._replace(True))
        b_close.clicked.connect(self._close)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self._close()
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._find(False)
        else:
            super().keyPressEvent(e)

    def open(self, mode: str | None = None) -> None:
        if mode:
            self.cmb_mode.setCurrentText(mode)
        self.show()
        self.txt_find.setFocus()
        self.txt_find.selectAll()

    def _close(self) -> None:
        self.hide()
        self.closed.emit()

    def message(self, text: str, error: bool = False) -> None:
        self.lbl_msg.setStyleSheet(f"color: {theme.colors.error if error else theme.colors.muted};")
        self.lbl_msg.setText(text)

    def _pattern(self, text: str) -> bytes | None:
        try:
            p = parse_pattern(text, self.cmb_mode.currentText())
        except ValueError as e:
            self.message(str(e), True)
            return None
        if not p:
            self.message("Enter something to find", True)
            return None
        return p

    def _find(self, forward: bool) -> None:
        if (p := self._pattern(self.txt_find.text())) is not None:
            self.find_requested.emit(p, forward)

    def _replace(self, all_: bool) -> None:
        p = self._pattern(self.txt_find.text())
        if p is None:
            return
        try:
            r = parse_pattern(self.txt_replace.text(), self.cmb_mode.currentText())
        except ValueError as e:
            self.message(str(e), True)
            return
        if len(r) != len(p):
            self.message(f"Replacement must be {len(p)} bytes (got {len(r)})", True)
            return
        self.replace_requested.emit(p, r, all_)


class RangeDialog(QDialog):
    """Ask for an offset (+ optional length / fill value). Numbers are hex unless suffixed."""

    def __init__(self, parent, title: str, offset: int = 0, length: int | None = None,
                 value: bool = False, max_size: int = 0) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.max_size = max_size
        self.txt_off = QLineEdit(f"0x{offset:X}")
        self.txt_len = QLineEdit(f"0x{length:X}" if length is not None else "")
        self.txt_val = QLineEdit("FF")
        form = QFormLayout(self)
        form.addRow("Offset:", self.txt_off)
        if length is not None:
            form.addRow("Length:", self.txt_len)
        if value:
            form.addRow("Fill byte (hex):", self.txt_val)
        hint = QLabel("Hex by default (1000 = 0x1000). Use #4096 for decimal, or 64K / 1M.", objectName="muted")
        hint.setWordWrap(True)
        form.addRow(hint)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self._has_len, self._has_val = length is not None, value
        self.offset = self.length = self.value = 0

    def _ok(self) -> None:
        try:
            self.offset = parse_int(self.txt_off.text())
            if self._has_len:
                self.length = parse_int(self.txt_len.text())
            if self._has_val:
                self.value = int(self.txt_val.text().strip().removeprefix("0x"), 16)
                if not 0 <= self.value <= 0xFF:
                    raise ValueError
        except ValueError:
            self.txt_off.setFocus()
            self.setWindowTitle(self.windowTitle().split(" —")[0] + " — invalid number")
            return
        if self.max_size and (self.offset >= self.max_size or self.offset + self.length > self.max_size):
            self.setWindowTitle(self.windowTitle().split(" —")[0] + " — outside the buffer")
            return
        self.accept()


def block_color(kind: Block) -> QColor:
    c = theme.colors
    return QColor({
        Block.EMPTY: c.surface_alt,
        Block.ZERO: c.border,
        Block.TEXT: c.ok,
        Block.DATA: c.accent,
        Block.PACKED: c.warn,
    }[kind])


class UsageMap(QWidget):
    """Horizontal strip, one cell per block of the image. Click to jump."""

    clicked = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.blocks: list[Block] = []
        self.size = 0
        self.setMinimumHeight(26)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_map(self, blocks: list[Block], size: int) -> None:
        self.blocks, self.size = blocks, size
        self.update()

    def _block_at(self, x: float) -> int | None:
        if not self.blocks or self.width() <= 0:
            return None
        return min(int(x / self.width() * len(self.blocks)), len(self.blocks) - 1)

    def _offset(self, i: int) -> int:
        return i * -(-self.size // len(self.blocks))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QColor(theme.colors.border))
        p.setBrush(QColor(theme.colors.surface_alt))
        p.drawRoundedRect(r, 5, 5)
        if self.blocks:
            w = r.width() / len(self.blocks)
            p.setPen(Qt.PenStyle.NoPen)
            for i, kind in enumerate(self.blocks):
                if kind is not Block.EMPTY:
                    p.setBrush(block_color(kind))
                    p.drawRect(QRectF(r.left() + i * w, r.top() + 2, max(w, 1.0), r.height() - 4))
        p.end()

    def mouseMoveEvent(self, e) -> None:
        i = self._block_at(e.position().x())
        if i is not None:
            start = self._offset(i)
            self.setToolTip(f"0x{start:08X}  —  {self.blocks[i].value}")

    def mousePressEvent(self, e) -> None:
        i = self._block_at(e.position().x())
        if i is not None:
            self.clicked.emit(self._offset(i))


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().hide()
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setShowGrid(False)
    t.setAlternatingRowColors(True)
    t.horizontalHeader().setStretchLastSection(True)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    t.verticalHeader().setDefaultSectionSize(24)
    return t


def _item(text: str, data=None, mono: bool = False) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    if data is not None:
        it.setData(Qt.ItemDataRole.UserRole, data)
    if mono:
        it.setFont(theme.mono_font())
    return it


class AnalysisPanel(QWidget):
    """Usage map, composition summary and detected structures."""

    jump = Signal(int, int)  # start, end

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.map = UsageMap()
        self.legend = QLabel(objectName="muted")
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        self.table = _table(["Offset", "End", "Structure", "Details"])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.addWidget(self.map)
        lay.addWidget(self.legend)
        lay.addWidget(self.table, 1)
        self.map.clicked.connect(lambda off: self.jump.emit(off, off + 1))
        self.table.itemDoubleClicked.connect(self._on_double)
        self.table.itemActivated.connect(self._on_double)

    def clear(self) -> None:
        self.map.set_map([], 0)
        self.legend.setText("Read a chip or open a file to analyse it.")
        self.table.setRowCount(0)

    def show_result(self, blocks: list[Block], size: int, shares: dict[Block, float], findings: list[Finding]) -> None:
        self.map.set_map(blocks, size)
        parts = []
        for kind in Block:
            share = shares.get(kind, 0)
            if share:
                sw = block_color(kind).name()
                parts.append(f"<span style='color:{sw}'>■</span> {kind.value} {share:.0%}")
        self.legend.setText("&nbsp;&nbsp;&nbsp;".join(parts) + "&nbsp;&nbsp;·&nbsp;&nbsp;click the map to jump")
        self.table.setRowCount(0)
        for f in findings:
            row = self.table.rowCount()
            self.table.insertRow(row)
            end = f.end if f.end is not None else f.offset + 1
            self.table.setItem(row, 0, _item(f"0x{f.offset:08X}", (f.offset, end), mono=True))
            self.table.setItem(row, 1, _item(f"0x{f.end - 1:08X}" if f.end else "", mono=True))
            self.table.setItem(row, 2, _item(f.kind))
            self.table.setItem(row, 3, _item(f.detail))
        if not findings:
            self.table.insertRow(0)
            self.table.setItem(0, 2, _item("No known structures found"))

    def _on_double(self, item: QTableWidgetItem) -> None:
        rng = self.table.item(item.row(), 0)
        if rng and rng.data(Qt.ItemDataRole.UserRole):
            self.jump.emit(*rng.data(Qt.ItemDataRole.UserRole))


class DiffPanel(QWidget):
    """List of differing ranges from Verify / Compare."""

    jump = Signal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.title = QLabel("No comparison yet. Use Verify or Edit → Compare with file.", objectName="muted")
        self.table = _table(["Start", "End", "Length"])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.addWidget(self.title)
        lay.addWidget(self.table, 1)
        self.table.itemDoubleClicked.connect(self._on_double)
        self.table.itemActivated.connect(self._on_double)

    def show_ranges(self, what: str, ranges: list[tuple[int, int]]) -> None:
        total = sum(e - s for s, e in ranges)
        if not ranges:
            self.title.setText(f"{what}: identical.")
        else:
            self.title.setText(
                f"{what}: {total:,} bytes differ in {len(ranges):,} range(s). Double-click to jump; Ctrl+D = next difference."
            )
        self.table.setRowCount(0)
        shown = ranges[:5000]
        self.table.setRowCount(len(shown))
        for row, (s, e) in enumerate(shown):
            self.table.setItem(row, 0, _item(f"0x{s:08X}", (s, e), mono=True))
            self.table.setItem(row, 1, _item(f"0x{e - 1:08X}", mono=True))
            self.table.setItem(row, 2, _item(f"{e - s:,} B" if e - s < 1024 else f"{e - s:,} B ({format_size(e - s)})"))

    def _on_double(self, item: QTableWidgetItem) -> None:
        rng = self.table.item(item.row(), 0)
        if rng and rng.data(Qt.ItemDataRole.UserRole):
            self.jump.emit(*rng.data(Qt.ItemDataRole.UserRole))
