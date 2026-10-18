"""End-to-end tests of the main window driven against the simulated programmer."""

import struct
from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog, QFileDialog

from ezp_programmer import self_check, widgets
from ezp_programmer.chips import find_by_name
from ezp_programmer.transport import SimulatedTransport

CHIP = "W25Q80BV"  # what the simulator reports (EF 13), 1 MiB


def firmware() -> bytes:
    img = bytearray(b"\xff" * SimulatedTransport.SIZE)
    hdr = bytearray(64)
    hdr[0:4] = b"\x27\x05\x19\x56"
    struct.pack_into(">I", hdr, 12, 0x1000)
    hdr[32:41] = b"Linux-5.4"
    img[0x20000 : 0x20040] = hdr
    img[0x20040 : 0x21040] = bytes(range(256)) * 16
    img[0x1000 : 0x1000 + 26] = b"bootcmd=bootm 0x9f020000\n\x00"
    return bytes(img)


def connect(w, chip: str = CHIP):
    w.on_connect_sim()
    w.wait()
    assert w.programmer is not None
    w.select_chip(find_by_name(chip))
    return w.programmer


def test_self_check():
    assert self_check() == 0


def test_app_icon_loads(qapp):
    from ezp_programmer import theme

    icon = theme.app_icon()
    assert not icon.isNull()
    assert {16, 32, 256} <= {s.width() for s in icon.availableSizes()}


def test_connect_shows_programmer_info(window):
    connect(window)
    assert "simulated" in window.lbl_version.text()
    assert window.lbl_serial.text() == "SIM00000000001"
    assert window.a_disconnect.isEnabled() and not window.a_connect.isEnabled()
    window.on_disconnect()
    assert window.programmer is None


def test_detect_selects_matching_chip(window):
    connect(window)
    window.select_chip(find_by_name("A25L010"))
    window.on_detect()
    window.wait()
    chip = window.selected_chip()
    assert (chip.manufacturer_id, chip.device_id) == (0xEF, 0x13)


def test_auto_then_read_round_trip_with_backups(window, dialogs, tmp_path):
    connect(window)
    image = firmware()
    window.set_buffer(image, "fw.bin")
    window.on_auto()
    window.wait()
    assert any("Verify OK" in m for m in dialogs.info), dialogs.warnings
    assert window.programmer.t.memory == image

    window.set_buffer(b"", "empty")
    window.on_read()
    window.wait()
    assert bytes(window.buffer) == image
    assert not dialogs.warnings
    names = sorted(p.name for p in (tmp_path / "backups").glob("*.bin"))
    assert any("_before-auto_" in n for n in names) and any("_read_" in n for n in names)


def test_unstable_read_is_reported(window, dialogs):
    prog = connect(window)
    real, calls = prog.read, []

    def flaky(chip, progress=None):
        data = bytearray(real(chip, progress))
        calls.append(1)
        if len(calls) == 2:
            data[0x1234] ^= 0xFF
        return bytes(data)

    prog.read = flaky
    window.on_read()
    window.wait()
    assert window.hex.hex_model.diff_ranges == [(0x1234, 0x1235)]
    assert any("Unstable read" in m for m in dialogs.warnings)


def test_verify_failure_lists_differences(window, dialogs):
    connect(window)
    image = bytearray(firmware())
    window.set_buffer(bytes(image), "fw.bin")
    window.on_auto()
    window.wait()
    image[0x100:0x104] = b"\x00\x11\x22\x33"
    window.set_buffer(bytes(image), "fw-modified.bin")
    window.on_verify()
    window.wait()
    assert window.hex.hex_model.diff_ranges == [(0x100, 0x104)]
    assert window.diff_panel.table.rowCount() == 1
    assert any("Verify FAILED" in m for m in dialogs.warnings)


def test_erase_and_blank_check(window, dialogs):
    connect(window)
    window.programmer.t.memory[:16] = b"\x00" * 16
    window.on_erase()
    window.wait()
    window.on_blank()
    window.wait()
    assert any("blank" in m.lower() for m in dialogs.info), dialogs.warnings


def test_analysis_finds_uimage(window):
    window.set_buffer(firmware(), "fw.bin")
    table = window.analysis_panel.table
    kinds = [table.item(r, 2).text() for r in range(table.rowCount())]
    assert "U-Boot image (uImage)" in kinds


def test_find_and_replace(window):
    window.set_buffer(firmware(), "fw.bin")
    window.on_find()
    bar = window.find_bar
    bar.cmb_mode.setCurrentText("Text")
    bar.txt_find.setText("bootm")
    bar._find(True)
    assert window.hex.selected_range() == (0x1008, 0x100D)
    bar.txt_replace.setText("BOOTM")
    bar._replace(True)
    assert bytes(window.buffer[0x1008:0x100D]) == b"BOOTM"
    bar.txt_replace.setText("toolong")
    bar._replace(True)
    assert "must be 5 bytes" in bar.lbl_msg.text()


@pytest.fixture
def auto_accept(monkeypatch):
    def ex(self):
        self._ok()
        return self.result() == QDialog.DialogCode.Accepted

    monkeypatch.setattr(widgets.RangeDialog, "exec", ex)


def test_fill_export_import_compare(window, auto_accept, monkeypatch, tmp_path):
    window.set_buffer(firmware(), "fw.bin")

    window.hex.select_range(0x1000, 0x1004)  # "boot" -> FF FF FF FF
    window.on_fill_range()
    assert bytes(window.buffer[0x1000:0x1004]) == b"\xff" * 4

    out = tmp_path / "export.bin"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    window.hex.select_range(0x20000, 0x20040)
    window.on_export_range()
    assert out.read_bytes()[:4] == b"\x27\x05\x19\x56" and out.stat().st_size == 0x40

    patch = tmp_path / "patch.bin"
    patch.write_bytes(b"PATCH")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(patch), "")))
    window.hex.go_to(0x300)
    window.on_import_at()
    assert bytes(window.buffer[0x300:0x305]) == b"PATCH"

    original = tmp_path / "original.bin"
    original.write_bytes(firmware())
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(original), "")))
    window.on_compare_file()
    starts = [s for s, _ in window.hex.hex_model.diff_ranges]
    assert 0x300 in starts and 0x1000 in starts


def test_open_file_and_recent_list(window, tmp_path):
    f = tmp_path / "dump.bin"
    f.write_bytes(firmware())
    window.load_file(f)
    assert window.buffer_source == "dump.bin" and len(window.buffer) == len(firmware())
    assert window._recent()[0] == str(f)
    assert window.m_recent.isEnabled()


def test_settings_are_sandboxed(window, tmp_path_factory):
    from PySide6.QtCore import QSettings

    assert window.settings.format() == QSettings.Format.IniFormat
    assert "pytest" in window.settings.fileName().replace("\\", "/").lower()


def test_hex_edit_updates_buffer(window):
    window.set_buffer(b"\x00" * 32, "t")
    model = window.hex.hex_model
    assert model.setData(model.index(1, 2), "ab")
    assert window.buffer[0x12] == 0xAB
    assert not model.setData(model.index(0, 0), "zz")
