"""Qt GUI for EZP2010/EZP2012/EZP2013 USB SPI flash / EEPROM programmers."""

__version__ = "0.1.0"


def self_check() -> int:
    """Verify bundled data and the libusb backend load (used by CI on the built exe)."""
    from .chips import load_chips
    from .transport import _backend

    chips = load_chips()
    backend = _backend()
    ok = len(chips) > 700 and backend is not None
    print(f"ezp-programmer {__version__}: {len(chips)} chips, libusb backend {'OK' if backend else 'MISSING'}")
    return 0 if ok else 1


def main() -> None:
    import sys

    if "--version" in sys.argv:
        print(__version__)
        sys.exit(0)
    if "--self-check" in sys.argv:
        sys.exit(self_check())

    from .main_window import run

    sys.exit(run())
