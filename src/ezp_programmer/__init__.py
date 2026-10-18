"""Qt GUI for EZP2010/EZP2012/EZP2013 USB SPI flash / EEPROM programmers."""

__version__ = "0.1.0"


def main() -> None:
    import sys

    from .main_window import run

    sys.exit(run())
