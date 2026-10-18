import os

from ezp_programmer.chips import ChipType, find_by_name, load_chips
from ezp_programmer.programmer import Programmer, fit_to_chip
from ezp_programmer.transport import SimulatedTransport


def make():
    return Programmer(SimulatedTransport())


def test_database_loads():
    chips = load_chips()
    assert len(chips) > 700
    assert {c.chip_type for c in chips} == set(ChipType)


def test_info():
    prog = make()
    assert "simulated" in prog.version()
    assert prog.serial() == "SIM00000000001"


def test_detect_finds_w25q80():
    res = make().detect()
    assert (res.manufacturer_id, res.device_id) == (0xEF, 0x13)
    assert any(c.name == "W25Q80BV" for c in res.matches)


def test_write_read_verify_erase():
    chip = find_by_name("W25Q80BV")
    prog = make()
    data = fit_to_chip(os.urandom(300_000), chip)
    prog.write(chip, data)
    assert prog.read(chip) == data
    assert prog.verify(chip, data).mismatches == 0
    assert prog.blank_check(chip).mismatches > 0
    prog.erase()
    assert prog.blank_check(chip).mismatches == 0


def test_read_cmd_layout():
    from ezp_programmer import protocol as p

    chip = find_by_name("W25Q80BV")
    assert p.read_cmd(chip).hex() == "110a01000000000010000003000000"
