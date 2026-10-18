"""Editable hex viewer backed by a bytearray (handles multi-MiB images)."""

from __future__ import annotations

from bisect import bisect_right

from PySide6.QtCore import QAbstractTableModel, QItemSelection, QItemSelectionModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

from . import theme

BYTES_PER_ROW = 16


class HexModel(QAbstractTableModel):
    edited = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.data_buf = bytearray()
        self._diff: list[tuple[int, int]] = []
        self._diff_starts: list[int] = []

    def set_data(self, data: bytes | bytearray) -> None:
        self.beginResetModel()
        self.data_buf = bytearray(data)
        self._diff, self._diff_starts = [], []
        self.endResetModel()

    def replace_bytes(self, offset: int, data: bytes) -> None:
        """Overwrite in place (no resize) and refresh the affected rows."""
        self.data_buf[offset : offset + len(data)] = data
        first, last = offset // BYTES_PER_ROW, (offset + max(len(data), 1) - 1) // BYTES_PER_ROW
        self.dataChanged.emit(self.index(first, 0), self.index(last, BYTES_PER_ROW))
        self.edited.emit()

    @property
    def diff_ranges(self) -> list[tuple[int, int]]:
        return self._diff

    def set_diff(self, ranges: list[tuple[int, int]]) -> None:
        self._diff = sorted(ranges)
        self._diff_starts = [r[0] for r in self._diff]
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, BYTES_PER_ROW))

    def is_diff(self, off: int) -> bool:
        i = bisect_right(self._diff_starts, off) - 1
        return i >= 0 and off < self._diff[i][1]

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else (len(self.data_buf) + BYTES_PER_ROW - 1) // BYTES_PER_ROW

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else BYTES_PER_ROW + 1

    def _offset(self, index: QModelIndex) -> int:
        return index.row() * BYTES_PER_ROW + index.column()

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if col == BYTES_PER_ROW:
            if role == Qt.ItemDataRole.DisplayRole:
                chunk = self.data_buf[row * BYTES_PER_ROW : (row + 1) * BYTES_PER_ROW]
                return "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
            if role == Qt.ItemDataRole.ForegroundRole:
                return QColor(theme.colors.muted)
            return None
        off = self._offset(index)
        if off >= len(self.data_buf):
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return f"{self.data_buf[off]:02X}"
        if role == Qt.ItemDataRole.ForegroundRole:
            if self._diff and self.is_diff(off):
                return QColor(theme.colors.error)
            if self.data_buf[off] == 0xFF:
                return QColor(theme.colors.hex_ff)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or index.column() >= BYTES_PER_ROW:
            return False
        off = self._offset(index)
        try:
            b = int(str(value).strip(), 16)
        except ValueError:
            return False
        if not (0 <= b <= 0xFF) or off >= len(self.data_buf):
            return False
        self.data_buf[off] = b
        self.dataChanged.emit(index, self.index(index.row(), BYTES_PER_ROW))
        self.edited.emit()
        return True

    def flags(self, index: QModelIndex):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() < BYTES_PER_ROW and self._offset(index) < len(self.data_buf):
            f |= Qt.ItemFlag.ItemIsEditable
        return f

    def headerData(self, section: int, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.ForegroundRole and orientation == Qt.Orientation.Vertical:
            return QColor(theme.colors.hex_addr)
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return "ASCII" if section == BYTES_PER_ROW else f"{section:X}"
        return f"{section * BYTES_PER_ROW:08X}"


class HexView(QTableView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.hex_model = HexModel()
        self.setModel(self.hex_model)
        font = theme.mono_font()
        self.setFont(font)
        self.horizontalHeader().setFont(font)
        self.verticalHeader().setFont(font)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ContiguousSelection)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        vh = self.verticalHeader()
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vh.setDefaultSectionSize(self.fontMetrics().height() + 6)
        hh = self.horizontalHeader()
        cell = self.fontMetrics().horizontalAdvance("00") + 14
        for c in range(BYTES_PER_ROW):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            hh.resizeSection(c, cell)
        hh.resizeSection(BYTES_PER_ROW, self.fontMetrics().horizontalAdvance("W" * 16) + 12)
        hh.setStretchLastSection(True)

    def go_to(self, offset: int) -> None:
        idx = self.hex_model.index(offset // BYTES_PER_ROW, offset % BYTES_PER_ROW)
        if idx.isValid():
            self.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
            self.setCurrentIndex(idx)

    def selected_range(self) -> tuple[int, int] | None:
        """Linear ``(start, end)`` byte range spanned by the selection (end exclusive)."""
        offs = [
            i.row() * BYTES_PER_ROW + i.column()
            for i in self.selectionModel().selectedIndexes()
            if i.column() < BYTES_PER_ROW
        ]
        offs = [o for o in offs if o < len(self.hex_model.data_buf)]
        return (min(offs), max(offs) + 1) if offs else None

    def cursor_offset(self) -> int:
        idx = self.currentIndex()
        if not idx.isValid():
            return 0
        return idx.row() * BYTES_PER_ROW + min(idx.column(), BYTES_PER_ROW - 1)

    def select_range(self, start: int, end: int) -> None:
        """Select bytes ``start..end-1`` as a linear run and scroll to it."""
        m = self.hex_model
        end = min(end, len(m.data_buf))
        if end <= start:
            return
        last = end - 1
        r0, c0, r1, c1 = start // BYTES_PER_ROW, start % BYTES_PER_ROW, last // BYTES_PER_ROW, last % BYTES_PER_ROW
        sel = QItemSelection()
        if r0 == r1:
            sel.select(m.index(r0, c0), m.index(r0, c1))
        else:
            sel.select(m.index(r0, c0), m.index(r0, BYTES_PER_ROW - 1))
            if r1 - r0 > 1:
                sel.select(m.index(r0 + 1, 0), m.index(r1 - 1, BYTES_PER_ROW - 1))
            sel.select(m.index(r1, 0), m.index(r1, c1))
        sm = self.selectionModel()
        sm.select(sel, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        sm.setCurrentIndex(m.index(r0, c0), QItemSelectionModel.SelectionFlag.NoUpdate)
        self.scrollTo(m.index(r0, c0), QAbstractItemView.ScrollHint.PositionAtCenter)

    def find(self, needle: bytes, forward: bool = True) -> int | None:
        """Find ``needle`` after (or before) the cursor, wrapping around."""
        buf = self.hex_model.data_buf
        if not needle or not buf:
            return None
        here = self.cursor_offset()
        if forward:
            i = buf.find(needle, here + 1)
            if i == -1:
                i = buf.find(needle, 0)
        else:
            i = buf.rfind(needle, 0, max(here, 0) + len(needle) - 1)
            if i == -1 or i >= here:
                i = buf.rfind(needle)
        if i == -1:
            return None
        self.select_range(i, i + len(needle))
        return i
