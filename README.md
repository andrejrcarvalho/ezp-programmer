# EZP Programmer

A Qt (PySide6) desktop app for the **EZP2010 / EZP2012 / EZP2013** USB SPI flash and EEPROM
programmers (USB ID `10C4:F5A0`). It is managed with [uv](https://docs.astral.sh/uv/).

Features:

- Connect, then show the firmware version and serial number
- Detect an SPI flash chip by its JEDEC ID, or choose from ~750 chips (25xx SPI flash, 24xx / 25xx / 93xx EEPROM)
- Read, Write, Verify, Erase, Blank check, and **Auto** (erase → write → verify)
- An editable hex view (double-click a byte to change it) that shows verify differences in red
- Open and save `.bin` images, with CRC32 and checksum shown
- A built-in **simulator** (Device → Connect simulator) for trying the app without hardware

## 1. Install the USB driver (Windows, one time)

The app talks to the programmer through libusb, so Windows must bind the **WinUSB** driver to it:

1. Plug in the programmer.
2. Download **Zadig** from <https://zadig.akeo.ie> and run it.
3. Choose *Options → List All Devices*, then pick the device with USB ID `10C4 F5A0`
   (it may show up as "USB Device" or as an unknown device).
4. Set the target driver to **WinUSB** and click **Install Driver** (or **Replace Driver**).

> The vendor's own EZP software uses a different driver. To use that software again, reinstall
> its driver in Device Manager (Update driver → choose its folder).

On **Linux**, you need a udev rule instead to use the programmer without root:

```
SUBSYSTEM=="usb", ATTR{idVendor}=="10c4", ATTR{idProduct}=="f5a0", MODE="0666"
```

## 2. Run

```bash
uv run ezp-programmer
```

uv creates the virtualenv and installs PySide6, pyusb, and libusb-package (which bundles
`libusb-1.0.dll`) on the first run.

## Typical workflow

1. **Connect** (F2).
2. **Detect** (F3) for SPI flash. For EEPROMs, select the chip in the list.
3. **Read** (F4) to back up the chip, then **Save** it to a file. Keep backups.
4. **Open** the image you want to flash, then **Auto** (F9) to erase, write and verify.

Notes:

- SPI flash must be erased before you write to it. Auto does the erase for you.
- If the image is smaller than the chip, it is padded with `0xFF`. A larger image is truncated (the app asks first).
- Cancel (Esc) stops reads and verifies. Writes and erases always run to completion.
- Several parts can share one JEDEC ID (e.g. W25Q80BV / W25X80). They have the same size, so any of them works.

## Safety features (Chip menu, both on by default)

- **Read twice and compare:** every Read runs twice. If the two reads differ, the contact with the chip
  (socket or SOIC test clip) is unreliable. The app warns you and lists the unstable bytes in the
  *Differences* tab. Don't trust that dump.
- **Automatic backups:** every read is saved, and the chip is read and saved before any Write,
  Erase or Auto. Files go to `Documents\EZP Programmer\backups` (change it under File → Choose
  backups folder), named like `W25Q64BV_2026-10-18_204512_before-auto_3E88722C.bin` (the last part
  is the CRC32).
- **Checksums** (View → Checksums, Ctrl+H): CRC32, MD5, SHA-1 and SHA-256 of the buffer, with a
  Copy button.

## Editing (Edit menu)

| Action | Shortcut | What it does |
|---|---|---|
| Find / replace | Ctrl+F | Search for hex bytes (`55 AA`) or text. Replacements must be the same length. |
| Next / previous difference | Ctrl+D / Ctrl+Shift+D | Jump between the ranges from Verify, Compare, or an unstable read |
| Import file at offset | Ctrl+I | Overwrite part of the buffer with a file, e.g. swap one region and keep the rest |
| Export range | Ctrl+E | Save the selection, or any offset and length, to a file |
| Fill range | | Fill the selection, or a range, with one byte value |
| Compare with file | Ctrl+K | List every range where the buffer differs from a file |

Offsets are hex by default (`1000` = 0x1000). Use `#4096` for decimal, or `64K` / `1M`. You can also
open files by dragging them onto the window, or from File → Open recent.

## Analysis tab

After every read or file load, the app scans the image and shows:

- **A usage map:** a strip across the whole chip showing empty (`FF`), zero, text, code/data and
  compressed/encrypted areas. Click it to jump. An all-empty or all-zero map means a bad read or a
  blank chip.
- **Detected structures:** Intel flash descriptor and its regions (BIOS / ME / GbE…), UEFI firmware
  volumes, U-Boot images and version strings, device trees, SquashFS / CramFS / JFFS2 / UBI, TRX,
  Android boot images, ELF, gzip / xz, and Linux kernel version strings. Double-click a row to select
  that range in the hex view.

## Development

```bash
uv run pytest
```

Code layout (`src/ezp_programmer/`):

| File | Purpose |
|---|---|
| `protocol.py` | Command packets and response parsing |
| `transport.py` | USB transport (pyusb/libusb) and the simulated programmer |
| `programmer.py` | High-level operations: detect, read, write, erase, verify |
| `chips.py` + `data/chips.json` | Chip database |
| `analysis.py` | Structure scan, usage map, diffs, hashes (no Qt) |
| `backups.py` | Timestamped automatic backups |
| `main_window.py`, `hexview.py`, `widgets.py`, `theme.py` | Qt GUI |

## Credits & license

The USB protocol and chip database come from the reverse engineering in
[hsorbo/ezp2010](https://github.com/hsorbo/ezp2010) (GPL-2.0), so this project is also
GPL-2.0-or-later.
