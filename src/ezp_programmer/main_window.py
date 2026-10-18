"""Main window of the EZP programmer GUI."""

from __future__ import annotations

import html
import time
import traceback
import zlib
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from . import __version__, analysis, backups, theme
from .chips import Chip, ChipType, format_size, load_chips
from .hexview import HexView
from .programmer import Cancelled, Programmer, fit_to_chip
from .transport import SimulatedTransport, UsbTransport
from .widgets import AnalysisPanel, DiffPanel, FindBar, RangeDialog

ROLE_CHIP = Qt.ItemDataRole.UserRole


class Worker(QThread):
    """Runs one programmer operation off the GUI thread."""

    progress = Signal(int, int)
    message = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable, parent=None) -> None:
        super().__init__(parent)
        self.fn = fn

    def run(self) -> None:
        try:
            self.succeeded.emit(self.fn(self))
        except Cancelled as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001 - surface every failure in the log
            traceback.print_exc()
            self.failed.emit(f"{type(e).__name__}: {e}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"EZP Programmer {__version__}")
        self.resize(1200, 780)
        # Honour QSettings.setDefaultFormat/setPath so tests can sandbox settings
        # (the plain (org, app) constructor always uses the registry on Windows).
        self.settings = QSettings(
            QSettings.defaultFormat(), QSettings.Scope.UserScope, "ezp-programmer", "ezp-programmer"
        )
        self.programmer: Programmer | None = None
        self.worker: Worker | None = None
        self.file_path: Path | None = None
        self.chips = load_chips()

        self._build_actions()
        self._build_ui()
        self._populate_filters()
        self._restore_chip()
        self._update_buffer_info()
        self._fill_recent_menu()
        self.setAcceptDrops(True)
        self._update_enabled()
        self.log("Ready. Connect the programmer, select or detect a chip, then read or write. "
                 "Drop a .bin file here to open it.")

    # ------------------------------------------------------------------ UI

    def _act(
        self, text: str, slot, shortcut: str | None = None, tip: str = "", icon: str | None = None
    ) -> QAction:
        a = QAction(text, self)
        if icon:
            a.setIcon(theme.icon(icon))
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setToolTip(tip or text)
        a.setStatusTip(tip or text)
        return a

    def _build_actions(self) -> None:
        self.a_connect = self._act("Connect", self.on_connect, "F2", "Connect to the USB programmer", icon="plug")
        self.a_sim = self._act("Connect simulator", self.on_connect_sim, tip="Use a simulated programmer (no hardware)")
        self.a_disconnect = self._act("Disconnect", self.on_disconnect, icon="unplug")
        self.a_detect = self._act("Detect", self.on_detect, "F3", "Read the SPI flash JEDEC ID and select the chip", icon="detect")
        self.a_read = self._act("Read", self.on_read, "F4", "Read the chip into the buffer", icon="read")
        self.a_write = self._act("Write", self.on_write, "F5", "Program the buffer into the chip", icon="write")
        self.a_verify = self._act("Verify", self.on_verify, "F6", "Compare the chip with the buffer", icon="verify")
        self.a_erase = self._act("Erase", self.on_erase, "F7", "Erase the chip", icon="erase")
        self.a_blank = self._act("Blank check", self.on_blank, "F8", "Check that the chip is erased (all 0xFF)", icon="blank")
        self.a_auto = self._act("Auto", self.on_auto, "F9", "Erase, write and verify", icon="auto")
        self.a_cancel = self._act("Cancel", self.on_cancel, "Esc", "Cancel the running read/verify", icon="cancel")
        self.a_selftest = self._act("Self test", self.on_self_test)
        self.a_open = self._act("Open…", self.on_open, "Ctrl+O", "Load a binary image into the buffer", icon="open")
        self.a_save = self._act("Save…", self.on_save, "Ctrl+S", "Save the buffer to a file", icon="save")
        self.a_new = self._act("New (fill 0xFF)", self.on_new, "Ctrl+N", "Create a blank buffer sized for the chip")
        self.a_goto = self._act("Go to offset…", self.on_goto, "Ctrl+G")
        self.a_quit = self._act("Quit", self.close, "Ctrl+Q")
        self.a_about = self._act("About", self.on_about)
        self.a_find = self._act("Find / replace…", self.on_find, "Ctrl+F", "Search the buffer for hex bytes or text")
        self.a_next_diff = self._act("Next difference", lambda: self._jump_diff(True), "Ctrl+D")
        self.a_prev_diff = self._act("Previous difference", lambda: self._jump_diff(False), "Ctrl+Shift+D")
        self.a_import = self._act("Import file at offset…", self.on_import_at, "Ctrl+I", "Overwrite part of the buffer with a file")
        self.a_export = self._act("Export range…", self.on_export_range, "Ctrl+E", "Save the selection or a range to a file")
        self.a_fill = self._act("Fill range…", self.on_fill_range, tip="Fill the selection or a range with one byte value")
        self.a_compare = self._act("Compare with file…", self.on_compare_file, "Ctrl+K", "List the differences between the buffer and a file")
        self.a_checksums = self._act("Checksums…", self.on_checksums, "Ctrl+H", "CRC32, MD5, SHA-1 and SHA-256 of the buffer")
        self.a_backups_open = self._act("Open backups folder", self.on_open_backups)
        self.a_backups_choose = self._act("Choose backups folder…", self.on_choose_backups)
        self.a_read_twice = QAction("Read twice and compare", self, checkable=True)
        self.a_read_twice.setToolTip("Detects a bad chip contact: both reads must be identical")
        self.a_backup = QAction("Automatic backups", self, checkable=True)
        self.a_backup.setToolTip("Save every read, and back up the chip before Write / Erase / Auto")
        for a, key in ((self.a_read_twice, "read_twice"), (self.a_backup, "auto_backup")):
            a.setChecked(self.settings.value(key, True, type=bool))
            a.toggled.connect(lambda on, key=key: self.settings.setValue(key, on))

        mb = self.menuBar()
        m = mb.addMenu("&File")
        for a in (self.a_new, self.a_open):
            m.addAction(a)
        self.m_recent = m.addMenu("Open recent")
        for a in (self.a_save, None, self.a_backups_open, self.a_backups_choose, None, self.a_quit):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("&Edit")
        for a in (self.a_find, self.a_next_diff, self.a_prev_diff, None, self.a_import, self.a_export,
                  self.a_fill, None, self.a_compare):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("&Device")
        for a in (self.a_connect, self.a_sim, self.a_disconnect, None, self.a_selftest):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("&Chip")
        for a in (self.a_detect, None, self.a_read, self.a_write, self.a_verify, self.a_erase,
                  self.a_blank, self.a_auto, None, self.a_read_twice, self.a_backup, None, self.a_cancel):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("&View")
        m.addAction(self.a_goto)
        m.addAction(self.a_checksums)
        mb.addMenu("&Help").addAction(self.a_about)

        tb = QToolBar("Main")
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        tb.setIconSize(QSize(20, 20))
        for a in (self.a_connect, self.a_disconnect, None, self.a_open, self.a_save, None, self.a_detect, self.a_read,
                  self.a_write, self.a_verify, self.a_erase, self.a_blank, self.a_auto, None, self.a_cancel):
            tb.addSeparator() if a is None else tb.addAction(a)
        tb.widgetForAction(self.a_auto).setObjectName("primary")
        for a in (self.a_connect, self.a_disconnect, self.a_auto):
            tb.widgetForAction(a).setMinimumWidth(72)
        self.addToolBar(tb)

    def _card(self, title: str | None = None) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(objectName="card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)
        if title:
            lbl = QLabel(title.upper(), objectName="cardTitle")
            lay.addWidget(lbl)
        return card, lay

    def _build_ui(self) -> None:
        # Programmer card
        dev_card, dv = self._card("Programmer")
        self.lbl_status = QLabel(objectName="pill")
        self.lbl_status.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.lbl_device = QLabel("No programmer connected", objectName="muted")
        self.lbl_device.setWordWrap(True)
        self.lbl_version = QLabel("–")
        self.lbl_serial = QLabel("–")
        for w in (self.lbl_version, self.lbl_serial, self.lbl_device):
            w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        f = QFormLayout()
        f.setContentsMargins(0, 0, 0, 0)
        f.setHorizontalSpacing(12)
        f.addRow(self._muted("Firmware"), self.lbl_version)
        f.addRow(self._muted("Serial"), self.lbl_serial)
        dv.addWidget(self.lbl_status)
        dv.addWidget(self.lbl_device)
        dv.addLayout(f)
        self._set_status(False)

        # Chip card
        chip_card, v = self._card("Chip")
        self.cmb_type = QComboBox()
        self.cmb_vendor = QComboBox()
        self.txt_search = QLineEdit(placeholderText="Search part number…")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.addAction(theme.icon("detect", theme.colors.muted, 16), QLineEdit.ActionPosition.LeadingPosition)
        self.lst_chips = QListWidget()
        self.lst_chips.setUniformItemSizes(True)
        self.lbl_chip_name = QLabel(objectName="chipName")
        self.lbl_chip = QLabel(objectName="muted")
        self.lbl_chip.setWordWrap(True)
        self.lbl_chip.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        filters = QHBoxLayout()
        filters.addWidget(self.cmb_type, 3)
        filters.addWidget(self.cmb_vendor, 2)
        v.addLayout(filters)
        v.addWidget(self.txt_search)
        v.addWidget(self.lst_chips, 1)
        sep = QFrame(frameShape=QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {theme.colors.border};")
        v.addWidget(sep)
        v.addWidget(self.lbl_chip_name)
        v.addWidget(self.lbl_chip)

        self.cmb_type.currentIndexChanged.connect(self._on_type_changed)
        self.cmb_vendor.currentIndexChanged.connect(self._refill_chips)
        self.txt_search.textChanged.connect(self._refill_chips)
        self.lst_chips.currentItemChanged.connect(self._on_chip_changed)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        lv.addWidget(dev_card)
        lv.addWidget(chip_card, 1)

        # Buffer card
        buf_card, bv = self._card()
        head = QHBoxLayout()
        head.addWidget(QLabel("BUFFER", objectName="cardTitle"))
        head.addStretch(1)
        self.lbl_buffer = QLabel(objectName="muted")
        self.lbl_buffer.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        head.addWidget(self.lbl_buffer)
        self.lbl_buffer.setToolTip("View → Checksums (Ctrl+H) for MD5 / SHA hashes")
        self.hex = HexView()
        self.hex.hex_model.edited.connect(self._update_buffer_info)
        self.find_bar = FindBar()
        self.find_bar.hide()
        self.find_bar.find_requested.connect(self._on_find)
        self.find_bar.replace_requested.connect(self._on_replace)
        self.find_bar.closed.connect(self.hex.setFocus)
        bv.addLayout(head)
        bv.addWidget(self.find_bar)
        bv.addWidget(self.hex, 1)

        # Bottom card: activity log, analysis, differences
        log_card, lgv = self._card()
        self.txt_log = QPlainTextEdit(readOnly=True, objectName="log")
        self.txt_log.setMaximumBlockCount(5000)
        self.txt_log.setFont(theme.mono_font())
        self.analysis_panel = AnalysisPanel()
        self.analysis_panel.jump.connect(self.hex.select_range)
        self.analysis_panel.clear()
        self.diff_panel = DiffPanel()
        self.diff_panel.jump.connect(self.hex.select_range)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.txt_log, "Activity")
        self.tabs.addTab(self.analysis_panel, "Analysis")
        self.tabs.addTab(self.diff_panel, "Differences")
        lgv.addWidget(self.tabs)

        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(buf_card)
        right.addWidget(log_card)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 2)
        right.setSizes([470, 260])

        main = QSplitter(Qt.Orientation.Horizontal)
        main.addWidget(left)
        main.addWidget(right)
        main.setStretchFactor(0, 0)
        main.setStretchFactor(1, 1)
        main.setSizes([330, 870])
        outer = QWidget()
        ol = QVBoxLayout(outer)
        ol.setContentsMargins(10, 10, 10, 10)
        ol.addWidget(main)
        self.setCentralWidget(outer)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(240)
        self.progress.setTextVisible(True)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)

    def _muted(self, text: str) -> QLabel:
        return QLabel(text, objectName="muted")

    def _set_status(self, connected: bool, detail: str = "") -> None:
        c = theme.colors
        color = c.ok if connected else c.muted
        bg = QColor(color)
        bg.setAlpha(40)
        self.lbl_status.setText(f"●  {'Connected' if connected else 'Not connected'}")
        self.lbl_status.setStyleSheet(
            f"color: {color}; background: rgba({bg.red()},{bg.green()},{bg.blue()},{bg.alpha()});"
        )
        self.lbl_device.setText(detail or "No programmer connected")

    # ------------------------------------------------------------- chips

    def _populate_filters(self) -> None:
        self.cmb_type.blockSignals(True)
        self.cmb_type.addItem("All types", None)
        for t in ChipType:
            self.cmb_type.addItem(t.label, t)
        self.cmb_type.blockSignals(False)
        self._on_type_changed()

    def _on_type_changed(self) -> None:
        t = self.cmb_type.currentData()
        vendors = sorted({c.vendor for c in self.chips if t is None or c.chip_type == t}, key=str.upper)
        current = self.cmb_vendor.currentText()
        self.cmb_vendor.blockSignals(True)
        self.cmb_vendor.clear()
        self.cmb_vendor.addItem("All vendors", None)
        for name in vendors:
            self.cmb_vendor.addItem(name, name)
        i = self.cmb_vendor.findText(current)
        self.cmb_vendor.setCurrentIndex(max(i, 0))
        self.cmb_vendor.blockSignals(False)
        self._refill_chips()

    def _refill_chips(self) -> None:
        t = self.cmb_type.currentData()
        vendor = self.cmb_vendor.currentData()
        q = self.txt_search.text().strip().upper()
        selected = self.selected_chip()
        self.lst_chips.blockSignals(True)
        self.lst_chips.clear()
        keep = None
        for c in self.chips:
            if t is not None and c.chip_type != t:
                continue
            if vendor is not None and c.vendor != vendor:
                continue
            if q and q not in c.name.upper() and q not in c.vendor.upper():
                continue
            item = QListWidgetItem(f"{c.name}  —  {c.vendor}, {format_size(c.size)}")
            item.setData(ROLE_CHIP, c)
            self.lst_chips.addItem(item)
            if c == selected:
                keep = item
        if keep is not None:
            self.lst_chips.setCurrentItem(keep)
        self.lst_chips.blockSignals(False)
        self._on_chip_changed()

    def selected_chip(self) -> Chip | None:
        item = self.lst_chips.currentItem() if hasattr(self, "lst_chips") else None
        return item.data(ROLE_CHIP) if item else None

    def select_chip(self, chip: Chip) -> None:
        # Make sure the chip is visible under the current filters.
        self.txt_search.blockSignals(True)
        self.txt_search.clear()
        self.txt_search.blockSignals(False)
        self.cmb_type.setCurrentIndex(self.cmb_type.findData(chip.chip_type))
        self.cmb_vendor.setCurrentIndex(max(self.cmb_vendor.findData(chip.vendor), 0))
        for i in range(self.lst_chips.count()):
            if self.lst_chips.item(i).data(ROLE_CHIP) == chip:
                self.lst_chips.setCurrentRow(i)
                self.lst_chips.scrollToItem(self.lst_chips.item(i))
                break

    def _on_chip_changed(self, *_) -> None:
        c = self.selected_chip()
        if c is None:
            self.lbl_chip_name.setText("No chip selected")
            self.lbl_chip.setText("Pick a chip from the list or click Detect.")
        else:
            ids = f"{c.manufacturer_id:02X} {c.device_id:02X}" if c.has_id else "—"
            self.lbl_chip_name.setText(f"{c.name}  <span style='font-weight:400; color:{theme.colors.muted}'>{c.vendor}</span>")
            self.lbl_chip.setText(
                "<table cellspacing='0' cellpadding='1'>"
                f"<tr><td>Type&nbsp;&nbsp;</td><td style='color:{theme.colors.text}'>{c.chip_type.label}</td></tr>"
                f"<tr><td>Size</td><td style='color:{theme.colors.text}'>{format_size(c.size)} ({c.size:,} bytes)</td></tr>"
                f"<tr><td>Voltage</td><td style='color:{theme.colors.text}'>{c.voltage_label}</td></tr>"
                f"<tr><td>JEDEC ID</td><td style='color:{theme.colors.text}'>{ids}</td></tr>"
                "</table>"
            )
            self.settings.setValue("chip", f"{c.vendor}|{c.name}")
        self._update_enabled()

    def _restore_chip(self) -> None:
        saved = str(self.settings.value("chip", ""))
        for c in self.chips:
            if f"{c.vendor}|{c.name}" == saved:
                self.select_chip(c)
                return

    # ----------------------------------------------------------- helpers

    def log(self, text: str) -> None:
        c = theme.colors
        if "FAILED" in text or "NOT " in text or "unknown" in text:
            color = c.error
        elif " OK" in text or text.startswith("Connected"):
            color = c.ok
        else:
            color = c.text
        self.txt_log.appendHtml(
            f"<span style='color:{c.muted}'>{time.strftime('%H:%M:%S')}</span>&nbsp;&nbsp;"
            f"<span style='color:{color}'>{html.escape(text)}</span>"
        )
        self.statusBar().showMessage(text, 8000)

    @property
    def buffer(self) -> bytearray:
        return self.hex.hex_model.data_buf

    def set_buffer(self, data: bytes, source: str) -> None:
        self.hex.hex_model.set_data(data)
        self.buffer_source = source
        self.diff_panel.show_ranges("Cleared (new buffer)", [])
        self._update_buffer_info()
        self._analyze()

    def _update_buffer_info(self) -> None:
        data = self.buffer
        if not data:
            self.lbl_buffer.setText("Empty — read a chip or open a file")
        else:
            src = getattr(self, "buffer_source", "")
            t = theme.colors.text
            self.lbl_buffer.setText(
                f"<span style='color:{t}'>{html.escape(src)}</span>  ·  {format_size(len(data))}  ·  "
                f"CRC32 <span style='color:{t}'>{zlib.crc32(data):08X}</span>  ·  "
                f"Sum <span style='color:{t}'>{sum(data) & 0xFFFFFFFF:08X}</span>"
            )
        self._update_enabled()

    def _busy(self) -> bool:
        return self.worker is not None

    def _update_enabled(self) -> None:
        if not hasattr(self, "a_cancel"):
            return
        busy = self._busy()
        conn = self.programmer is not None
        chip = self.selected_chip() is not None
        has_buf = bool(self.buffer) if hasattr(self, "hex") else False
        self.a_connect.setEnabled(not busy and not conn)
        self.a_sim.setEnabled(not busy and not conn)
        self.a_disconnect.setEnabled(not busy and conn)
        self.a_connect.setVisible(not conn)
        self.a_disconnect.setVisible(conn)
        self.a_selftest.setEnabled(not busy and conn)
        self.a_detect.setEnabled(not busy and conn)
        for a in (self.a_read, self.a_erase, self.a_blank):
            a.setEnabled(not busy and conn and chip)
        for a in (self.a_write, self.a_verify, self.a_auto):
            a.setEnabled(not busy and conn and chip and has_buf)
        self.a_cancel.setEnabled(busy)
        for a in (self.a_open, self.a_new):
            a.setEnabled(not busy)
        self.a_save.setEnabled(not busy and has_buf)
        for a in (self.a_find, self.a_export, self.a_fill, self.a_compare, self.a_checksums):
            a.setEnabled(not busy and has_buf)
        self.a_import.setEnabled(not busy)
        has_diff = has_buf and bool(self.hex.hex_model.diff_ranges)
        self.a_next_diff.setEnabled(has_diff)
        self.a_prev_diff.setEnabled(has_diff)
        if hasattr(self, "lst_chips"):
            for w in (self.lst_chips, self.cmb_type, self.cmb_vendor, self.txt_search):
                w.setEnabled(not busy)

    def _on_progress(self, done: int, total: int) -> None:
        if total <= 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            self.progress.setFormat(f"%p%  ({format_size(done) if done % 1024 == 0 else done})")

    def run_task(self, title: str, fn: Callable, on_done: Callable | None = None) -> None:
        if self._busy():
            return
        self.log(f"{title}…")
        started = time.monotonic()
        w = Worker(fn, self)
        self.worker = w
        w.progress.connect(self._on_progress)
        w.message.connect(self.log)

        def finished_ok(result) -> None:
            self.log(f"{title} finished in {time.monotonic() - started:.1f} s")
            if on_done:
                on_done(result)

        w.succeeded.connect(finished_ok)
        w.failed.connect(lambda msg: self._task_failed(title, msg))
        w.finished.connect(self._task_finished)
        self.progress.setRange(0, 0)
        self.progress.show()
        self._update_enabled()
        w.start()

    def _task_failed(self, title: str, msg: str) -> None:
        self.log(f"{title} FAILED: {msg}")
        QMessageBox.warning(self, title, msg)

    def _task_finished(self) -> None:
        self.worker.deleteLater()
        self.worker = None
        self.progress.hide()
        self._update_enabled()

    def _require_chip(self) -> Chip | None:
        chip = self.selected_chip()
        if chip is None:
            QMessageBox.information(self, "No chip", "Select a chip type first.")
        return chip

    def _confirm(self, title: str, text: str) -> bool:
        return (
            QMessageBox.question(self, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            == QMessageBox.StandardButton.Yes
        )

    def _image_for(self, chip: Chip) -> bytes | None:
        data = bytes(self.buffer)
        if len(data) != chip.size:
            if not self._confirm(
                "Size mismatch",
                f"The buffer is {len(data):,} bytes but the {chip.name} holds {chip.size:,} bytes.\n\n"
                + ("The image will be padded with 0xFF." if len(data) < chip.size else "The image will be TRUNCATED.")
                + "\n\nContinue?",
            ):
                return None
        return fit_to_chip(data, chip)

    # ----------------------------------------------------------- device

    def _connect(self, factory) -> None:
        def task(w: Worker):
            prog = Programmer(factory())
            info = {"name": prog.name}
            for key, fn in (("version", prog.version), ("serial", prog.serial)):
                try:
                    info[key] = fn()
                except Exception as e:  # noqa: BLE001
                    w.message.emit(f"Could not read {key}: {e}")
            return prog, info

        def done(result) -> None:
            self.programmer, info = result
            self._set_status(True, info["name"])
            self.lbl_version.setText(info.get("version", "?"))
            self.lbl_serial.setText(info.get("serial", "?"))
            self.log(f"Connected: {info['name']}, firmware {info.get('version', '?')}")
            self._update_enabled()

        self.run_task("Connect", task, done)

    def on_connect(self) -> None:
        self._connect(UsbTransport)

    def on_connect_sim(self) -> None:
        self._connect(SimulatedTransport)

    def on_disconnect(self) -> None:
        if self.programmer:
            try:
                self.programmer.close()
            except Exception as e:  # noqa: BLE001
                self.log(f"Close error: {e}")
        self.programmer = None
        self._set_status(False)
        self.lbl_version.setText("–")
        self.lbl_serial.setText("–")
        self.log("Disconnected")
        self._update_enabled()

    def on_self_test(self) -> None:
        prog = self.programmer
        self.run_task("Self test", lambda w: prog.self_test(), lambda r: self.log(f"Self test: {r}"))

    def on_cancel(self) -> None:
        if self.programmer and self._busy():
            self.programmer.cancel_requested = True
            self.log("Cancelling… (writes and erases always run to completion)")

    # ------------------------------------------------------------- chip ops

    def _backup_dir(self) -> Path:
        return Path(str(self.settings.value("backup_dir", str(backups.default_dir()))))

    def _backup_target(self) -> Path | None:
        """Backup folder if auto-backup is on. Call on the GUI thread, before starting a task."""
        return self._backup_dir() if self.a_backup.isChecked() else None

    @staticmethod
    def _backup_step(prog: Programmer, chip: Chip, w: Worker, reason: str, folder: Path | None) -> None:
        """Read the chip and save it before a destructive operation."""
        if folder is None:
            return
        w.message.emit(f"Backing up {chip.name} before {reason}…")
        data = prog.read(chip, w.progress.emit)
        path = backups.save(data, chip.name, f"before-{reason}", folder)
        w.message.emit(f"Backup saved: {path}")

    def on_detect(self) -> None:
        prog = self.programmer

        def done(res) -> None:
            ids = f"manufacturer {res.manufacturer_id:02X}, device {res.device_id:02X}"
            if not res.matches:
                self.log(f"Detected unknown chip ({ids}). Select it manually.")
                return
            names = ", ".join(str(c) for c in res.matches)
            self.log(f"Detected {ids}: {names}")
            current = self.selected_chip()
            if current not in res.matches:
                self.select_chip(res.matches[0])
            if len(res.matches) > 1:
                self.log("Several parts share this ID; pick the exact one if it matters (sizes are equal).")

        self.run_task("Detect", lambda w: prog.detect(), done)

    def on_read(self) -> None:
        chip = self._require_chip()
        if not chip:
            return
        prog = self.programmer
        twice = self.a_read_twice.isChecked()
        folder = self._backup_target()

        def task(w: Worker):
            data = prog.read(chip, w.progress.emit)
            unstable: list[tuple[int, int]] = []
            if twice:
                w.message.emit("Reading again to check the connection…")
                unstable = analysis.diff_ranges(data, prog.read(chip, w.progress.emit))
            path = None
            if folder is not None:
                path = backups.save(data, chip.name, "read-UNSTABLE" if unstable else "read", folder)
            return data, unstable, path

        def done(result) -> None:
            data, unstable, path = result
            self.set_buffer(data, f"read from {chip.name}")
            if path:
                self.log(f"Backup saved: {path}")
            if unstable:
                total = sum(e - s for s, e in unstable)
                self._show_diff("Read 1 vs read 2", unstable)
                msg = (
                    f"The two reads differ in {total:,} bytes ({len(unstable)} ranges).\n\n"
                    "The connection to the chip is unreliable: check the chip seating or test clip, "
                    "then read again. Do not trust this dump."
                )
                self.log(f"Read check FAILED: reads differ in {total:,} bytes")
                QMessageBox.warning(self, "Unstable read", msg)
            elif twice:
                self.log("Read check OK: both reads are identical")

        self.run_task(f"Read {chip.name}", task, done)

    def on_write(self) -> None:
        chip = self._require_chip()
        if not chip:
            return
        data = self._image_for(chip)
        if data is None:
            return
        if chip.chip_type == ChipType.SPI and not self._confirm(
            "Write", f"Program {format_size(len(data))} into the {chip.name}?\n\n"
            "SPI flash must be erased first, otherwise bits can only go from 1 to 0. "
            "Use Auto to erase, write and verify in one go."
        ):
            return
        prog = self.programmer
        folder = self._backup_target()

        def task(w: Worker):
            self._backup_step(prog, chip, w, "write", folder)
            prog.write(chip, data, w.progress.emit)

        self.run_task(f"Write {chip.name}", task)

    def on_verify(self) -> None:
        chip = self._require_chip()
        if not chip:
            return
        expected = fit_to_chip(bytes(self.buffer), chip)
        prog = self.programmer

        def task(w: Worker):
            return analysis.diff_ranges(prog.read(chip, w.progress.emit), expected)

        self.run_task(f"Verify {chip.name}", task, lambda r: self._show_verify(r))

    def _show_diff(self, what: str, ranges: list[tuple[int, int]]) -> None:
        self.hex.hex_model.set_diff(ranges)
        self.diff_panel.show_ranges(what, ranges)
        self._update_enabled()
        if ranges:
            self.tabs.setCurrentWidget(self.diff_panel)
            self.hex.select_range(*ranges[0])

    def _show_verify(self, ranges: list[tuple[int, int]]) -> None:
        self._show_diff("Chip vs buffer", ranges)
        if not ranges:
            self.log("Verify OK: chip matches the buffer")
            QMessageBox.information(self, "Verify", "Verify OK — the chip matches the buffer.")
            return
        total = sum(e - s for s, e in ranges)
        msg = f"Verify FAILED: {total:,} bytes differ in {len(ranges):,} ranges, first at 0x{ranges[0][0]:08X}"
        self.log(msg)
        QMessageBox.warning(self, "Verify", msg + "\n\nSee the Differences tab.")

    def on_erase(self) -> None:
        chip = self._require_chip()
        if not chip or not self._confirm("Erase", f"Erase the entire {chip.name}? This cannot be undone."):
            return
        prog = self.programmer
        folder = self._backup_target()

        def task(w: Worker):
            self._backup_step(prog, chip, w, "erase", folder)
            if chip.chip_type == ChipType.SPI:
                prog.erase(w.progress.emit)
            else:
                # EEPROMs have no bulk erase; fill them with 0xFF instead.
                prog.write(chip, b"\xff" * chip.size, w.progress.emit)

        self.run_task(f"Erase {chip.name}", task)

    def on_blank(self) -> None:
        chip = self._require_chip()
        if not chip:
            return
        prog = self.programmer

        def done(res) -> None:
            if res.mismatches == 0:
                self.log(f"Blank check OK: {chip.name} is erased")
                QMessageBox.information(self, "Blank check", "The chip is blank (all 0xFF).")
            else:
                msg = f"Chip is NOT blank: {res.mismatches:,} non-0xFF bytes, first at 0x{res.first_offset:08X}"
                self.log(msg)
                QMessageBox.warning(self, "Blank check", msg)

        self.run_task(f"Blank check {chip.name}", lambda w: prog.blank_check(chip, w.progress.emit), done)

    def on_auto(self) -> None:
        chip = self._require_chip()
        if not chip:
            return
        data = self._image_for(chip)
        if data is None or not self._confirm(
            "Auto", f"Erase, program and verify the {chip.name} with the buffer contents?"
        ):
            return
        prog = self.programmer
        folder = self._backup_target()

        def task(w: Worker):
            self._backup_step(prog, chip, w, "auto", folder)
            if chip.chip_type == ChipType.SPI:
                w.message.emit("Erasing…")
                prog.erase(w.progress.emit)
            w.message.emit("Writing…")
            prog.write(chip, data, w.progress.emit)
            w.message.emit("Verifying…")
            return analysis.diff_ranges(prog.read(chip, w.progress.emit), data)

        self.run_task(f"Auto {chip.name}", task, self._show_verify)

    # ----------------------------------------------------------- analysis

    def _analyze(self) -> None:
        data = bytes(self.buffer)
        if not data:
            self.analysis_panel.clear()
            return
        findings = analysis.scan(data)
        self.analysis_panel.show_result(analysis.usage_map(data, 512), len(data), analysis.summary(data), findings)
        if findings:
            kinds = sorted({f.kind.split(":")[0] for f in findings})
            self.log(f"Analysis: {len(findings)} structure(s) found — {', '.join(kinds[:6])}")

    def on_checksums(self) -> None:
        data = bytes(self.buffer)
        if not data:
            return
        text = "\n".join(f"{k:<8} {v}" for k, v in analysis.hashes(data).items())
        dlg = QDialog(self)
        dlg.setWindowTitle("Checksums")
        lay = QVBoxLayout(dlg)
        lay.addWidget(self._muted(f"{getattr(self, 'buffer_source', '')}  ·  {len(data):,} bytes"))
        box = QPlainTextEdit(text, readOnly=True)
        box.setFont(theme.mono_font())
        box.setMinimumSize(560, 110)
        lay.addWidget(box)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy = bb.addButton("Copy", QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.exec()

    # ----------------------------------------------------------- editing

    def on_find(self) -> None:
        if self.buffer:
            self.find_bar.open()

    def _on_find(self, pattern: bytes, forward: bool) -> None:
        hit = self.hex.find(pattern, forward)
        if hit is None:
            self.find_bar.message("Not found", True)
        else:
            count = bytes(self.buffer).count(pattern)
            self.find_bar.message(f"0x{hit:08X}  ·  {count:,} match{'es' if count != 1 else ''}")

    def _on_replace(self, pattern: bytes, repl: bytes, all_: bool) -> None:
        buf = self.buffer
        if all_:
            n = bytes(buf).count(pattern)
            if not n:
                self.find_bar.message("Not found", True)
                return
            self.hex.hex_model.set_data(bytes(buf).replace(pattern, repl))
            self._update_buffer_info()
            self.find_bar.message(f"Replaced {n:,} occurrence(s)")
            self.log(f"Replaced {n:,} occurrence(s) of {pattern.hex(' ').upper()}")
            return
        sel = self.hex.selected_range()
        if sel and bytes(buf[sel[0] : sel[1]]) == pattern:
            self.hex.hex_model.replace_bytes(sel[0], repl)
            self.find_bar.message(f"Replaced at 0x{sel[0]:08X}")
        self._on_find(pattern, True)

    def _jump_diff(self, forward: bool) -> None:
        ranges = self.hex.hex_model.diff_ranges
        if not ranges:
            return
        here = self.hex.cursor_offset()
        if forward:
            nxt = next((r for r in ranges if r[0] > here), ranges[0])
        else:
            nxt = next((r for r in reversed(ranges) if r[0] < here), ranges[-1])
        self.hex.select_range(*nxt)

    def _ensure_buffer(self) -> bool:
        if self.buffer:
            return True
        chip = self._require_chip()
        if chip:
            self.set_buffer(b"\xff" * chip.size, f"blank for {chip.name}")
        return bool(chip)

    def on_import_at(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import file at offset", self._last_dir(), "All files (*)")
        if not path or not self._ensure_buffer():
            return
        data = Path(path).read_bytes()
        dlg = RangeDialog(self, "Import at offset", offset=self.hex.cursor_offset(), max_size=len(self.buffer))
        if not dlg.exec():
            return
        room = len(self.buffer) - dlg.offset
        if len(data) > room:
            if not self._confirm("Import", f"The file is {len(data):,} bytes but only {room:,} fit. Truncate it?"):
                return
            data = data[:room]
        self.hex.hex_model.replace_bytes(dlg.offset, data)
        self.hex.select_range(dlg.offset, dlg.offset + len(data))
        self._analyze()
        self.log(f"Imported {Path(path).name} ({len(data):,} bytes) at 0x{dlg.offset:08X}")

    def _range_from_selection(self) -> tuple[int, int]:
        sel = self.hex.selected_range()
        if sel and sel[1] - sel[0] > 1:
            return sel[0], sel[1] - sel[0]
        return 0, len(self.buffer)

    def on_export_range(self) -> None:
        off, length = self._range_from_selection()
        dlg = RangeDialog(self, "Export range", offset=off, length=length, max_size=len(self.buffer))
        if not dlg.exec() or dlg.length <= 0:
            return
        suggested = Path(self._last_dir()) / f"export_{dlg.offset:08X}_{dlg.length:X}.bin"
        path, _ = QFileDialog.getSaveFileName(self, "Export range", str(suggested), "Binary (*.bin);;All files (*)")
        if path:
            Path(path).write_bytes(bytes(self.buffer[dlg.offset : dlg.offset + dlg.length]))
            self.log(f"Exported 0x{dlg.offset:08X}+{dlg.length:,} bytes to {path}")

    def on_fill_range(self) -> None:
        off, length = self._range_from_selection()
        dlg = RangeDialog(self, "Fill range", offset=off, length=length, value=True, max_size=len(self.buffer))
        if not dlg.exec() or dlg.length <= 0:
            return
        self.hex.hex_model.replace_bytes(dlg.offset, bytes([dlg.value]) * dlg.length)
        self._analyze()
        self.log(f"Filled 0x{dlg.offset:08X}+{dlg.length:,} bytes with 0x{dlg.value:02X}")

    def on_compare_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Compare buffer with file", self._last_dir(), "All files (*)")
        if not path:
            return
        other = Path(path).read_bytes()
        ranges = analysis.diff_ranges(bytes(self.buffer), other)
        self._show_diff(f"Buffer vs {Path(path).name}", ranges)
        total = sum(e - s for s, e in ranges)
        self.log(f"Compare with {Path(path).name}: " + (f"{total:,} bytes differ" if ranges else "identical OK"))

    # ----------------------------------------------------------- files

    def _last_dir(self) -> str:
        return str(self.settings.value("last_dir", str(Path.home())))

    def _recent(self) -> list[str]:
        value = self.settings.value("recent", [])
        return [value] if isinstance(value, str) else list(value or [])

    def _add_recent(self, path: Path) -> None:
        items = [str(path)] + [p for p in self._recent() if p != str(path)]
        self.settings.setValue("recent", items[:8])
        self._fill_recent_menu()

    def _fill_recent_menu(self) -> None:
        self.m_recent.clear()
        items = self._recent()
        for p in items:
            a = self.m_recent.addAction(p)
            a.triggered.connect(lambda _=False, p=p: self.load_file(Path(p)))
        if items:
            self.m_recent.addSeparator()
            self.m_recent.addAction("Clear list", lambda: (self.settings.setValue("recent", []), self._fill_recent_menu()))
        self.m_recent.setEnabled(bool(items))

    def load_file(self, p: Path) -> None:
        if self._busy():
            return
        try:
            data = p.read_bytes()
        except OSError as e:
            QMessageBox.warning(self, "Open", f"Cannot read {p}:\n{e}")
            return
        self.settings.setValue("last_dir", str(p.parent))
        self._add_recent(p)
        self.set_buffer(data, p.name)
        self.log(f"Loaded {p} ({len(data):,} bytes)")
        chip = self.selected_chip()
        if chip and len(data) != chip.size:
            self.log(f"Note: file size differs from {chip.name} size ({chip.size:,} bytes)")

    def on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open image", self._last_dir(), "Binary images (*.bin *.rom *.img *.hex);;All files (*)"
        )
        if path:
            self.load_file(Path(path))

    def on_save(self) -> None:
        chip = self.selected_chip()
        suggested = Path(self._last_dir()) / (f"{chip.name}.bin" if chip else "dump.bin")
        path, _ = QFileDialog.getSaveFileName(self, "Save image", str(suggested), "Binary images (*.bin);;All files (*)")
        if not path:
            return
        p = Path(path)
        p.write_bytes(bytes(self.buffer))
        self.settings.setValue("last_dir", str(p.parent))
        self._add_recent(p)
        self.log(f"Saved {len(self.buffer):,} bytes to {p}")

    def on_new(self) -> None:
        chip = self._require_chip()
        if chip:
            self.set_buffer(b"\xff" * chip.size, f"blank for {chip.name}")

    def on_open_backups(self) -> None:
        folder = self._backup_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def on_choose_backups(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Backups folder", str(self._backup_dir()))
        if folder:
            self.settings.setValue("backup_dir", folder)
            self.log(f"Backups folder: {folder}")

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls() and len(e.mimeData().urls()) == 1 and not self._busy():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        url = e.mimeData().urls()[0]
        if url.isLocalFile():
            self.load_file(Path(url.toLocalFile()))

    def on_goto(self) -> None:
        text, ok = QInputDialog.getText(self, "Go to offset", "Offset (hex):")
        if ok and text.strip():
            try:
                self.hex.go_to(int(text.strip().removeprefix("0x"), 16))
            except ValueError:
                self.log(f"Invalid offset: {text}")

    def on_about(self) -> None:
        QMessageBox.about(
            self,
            "About EZP Programmer",
            f"<b>EZP Programmer {__version__}</b><br>"
            "Qt front-end for EZP2010 / EZP2012 / EZP2013 USB programmers (USB 10C4:F5A0).<br><br>"
            "Protocol and chip database from the "
            "<a href='https://github.com/hsorbo/ezp2010'>hsorbo/ezp2010</a> project (GPL-2.0).",
        )

    def closeEvent(self, event) -> None:
        if self._busy():
            QMessageBox.information(self, "Busy", "Wait for the current operation to finish.")
            event.ignore()
            return
        if self.programmer:
            self.on_disconnect()
        super().closeEvent(event)


def run() -> int:
    import sys

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("EZP Programmer")
    theme.apply(app)
    app.setWindowIcon(theme.app_icon())
    win = MainWindow()
    win.show()
    return app.exec()
