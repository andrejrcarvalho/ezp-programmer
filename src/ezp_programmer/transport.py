"""Byte transports: real USB (libusb via pyusb) and an in-memory simulator."""

from __future__ import annotations

import struct
import sys
from collections import deque
from typing import Protocol

from . import protocol as p

VENDOR_ID = 0x10C4
PRODUCT_ID = 0xF5A0
TIMEOUT_MS = 10_000


class TransportError(Exception):
    pass


class Transport(Protocol):
    name: str

    def write(self, data: bytes, timeout_ms: int = TIMEOUT_MS) -> int: ...
    def read(self, size: int, timeout_ms: int = TIMEOUT_MS) -> bytes: ...
    def close(self) -> None: ...


def _backend():
    import libusb_package

    return libusb_package.get_libusb1_backend()


def list_devices() -> list[str]:
    """Describe attached programmers (empty if none are visible to libusb)."""
    import usb.core

    found = usb.core.find(
        find_all=True, idVendor=VENDOR_ID, idProduct=PRODUCT_ID, backend=_backend()
    )
    return [f"Bus {d.bus:03d} Device {d.address:03d}" for d in found]


class UsbTransport:
    def __init__(self, vid: int = VENDOR_ID, pid: int = PRODUCT_ID) -> None:
        import usb.core
        import usb.util

        self._usb = usb
        dev = usb.core.find(idVendor=vid, idProduct=pid, backend=_backend())
        if dev is None:
            raise TransportError(
                f"Programmer {vid:04X}:{pid:04X} not found. Is it plugged in"
                + (" and bound to the WinUSB driver (see README)?" if sys.platform == "win32" else "?")
            )
        try:
            if sys.platform != "win32":
                try:
                    if dev.is_kernel_driver_active(0):
                        dev.detach_kernel_driver(0)
                except (NotImplementedError, usb.core.USBError):
                    pass
            try:
                dev.set_configuration()
            except usb.core.USBError:
                pass  # already configured (common with WinUSB)
            cfg = dev.get_active_configuration()
            intf = cfg[(0, 0)]
            usb.util.claim_interface(dev, intf.bInterfaceNumber)
        except usb.core.USBError as e:
            raise TransportError(_explain(e)) from e
        except NotImplementedError as e:
            raise TransportError(
                "libusb cannot access the device. On Windows, install the WinUSB "
                "driver for it with Zadig (see README)."
            ) from e

        def find(direction):
            return usb.util.find_descriptor(
                intf,
                custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
                == direction,
            )

        self._dev = dev
        self._intf = intf.bInterfaceNumber
        self._ep_out = find(usb.util.ENDPOINT_OUT)
        self._ep_in = find(usb.util.ENDPOINT_IN)
        if self._ep_out is None or self._ep_in is None:
            raise TransportError("Programmer has no bulk IN/OUT endpoints")
        self.name = f"USB {vid:04X}:{pid:04X} (bus {dev.bus}, addr {dev.address})"

    def write(self, data: bytes, timeout_ms: int = TIMEOUT_MS) -> int:
        try:
            return self._ep_out.write(data, timeout_ms)
        except self._usb.core.USBError as e:
            raise TransportError(_explain(e)) from e

    def read(self, size: int, timeout_ms: int = TIMEOUT_MS) -> bytes:
        try:
            return bytes(self._ep_in.read(size, timeout_ms))
        except self._usb.core.USBTimeoutError as e:
            raise TransportError("Timed out waiting for the programmer") from e
        except self._usb.core.USBError as e:
            raise TransportError(_explain(e)) from e

    def close(self) -> None:
        try:
            self._usb.util.release_interface(self._dev, self._intf)
        finally:
            self._usb.util.dispose_resources(self._dev)


def _explain(e: Exception) -> str:
    msg = str(e)
    if "Access denied" in msg or "Errno 13" in msg:
        return (
            f"{msg}. Another program (e.g. the vendor EZP software) may hold the "
            "device, or you lack permission (Linux: add a udev rule)."
        )
    return msg


class SimulatedTransport:
    """Emulates programmer firmware with a W25Q80BV attached. For demos and tests."""

    MANUFACTURER_ID = 0xEF
    DEVICE_ID = 0x13
    SIZE = 1024 * 1024

    def __init__(self) -> None:
        self.name = "Simulated programmer"
        self.memory = bytearray(b"\xff" * self.SIZE)
        self._out: deque[bytes] = deque()
        self._write_remaining = 0
        self._write_pos = 0
        self._erase_polls = 0

    def write(self, data: bytes, timeout_ms: int = TIMEOUT_MS) -> int:
        data = bytes(data)
        if self._write_remaining:
            n = min(len(data), self._write_remaining)
            for i in range(n):  # NOR flash: programming can only clear bits
                self.memory[self._write_pos + i] &= data[i]
            self._write_pos += n
            self._write_remaining -= n
            return len(data)

        cmd = data[0]
        if cmd == p.CMD_VERSION:
            self._out.append(bytes([p.CMD_VERSION, 0x1E]) + b"EZP2010 V3.0 (simulated)".ljust(30, b"\0"))
        elif cmd == p.CMD_SERIAL:
            self._out.append(bytes([p.CMD_SERIAL, 0x10]) + b"SIM00000000001" + b"\xff\xff")
        elif cmd == p.CMD_DETECT:
            self._out.append(bytes([p.CMD_DETECT, 0x02, self.MANUFACTURER_ID, self.DEVICE_ID, 0]))
        elif cmd == p.CMD_READ:
            (size,) = struct.unpack(">I", data[7:11])
            self._out.append(p.READ_OK)
            size = min(size, self.SIZE)
            for off in range(0, size, p.CHUNK):
                self._out.append(bytes(self.memory[off : min(off + p.CHUNK, size)]))
        elif cmd == p.CMD_WRITE:
            (size,) = struct.unpack(">I", data[7:11])
            self._write_remaining = min(size, self.SIZE)
            self._write_pos = 0
            self._out.append(p.WRITE_OK)
        elif cmd == p.CMD_ERASE_START:
            self._erase_polls = 5
            self._out.append(p.ERASE_START_OK)
        elif cmd == p.CMD_ERASE_POLL:
            if self._erase_polls > 0:
                self._erase_polls -= 1
                self._out.append(p.ERASE_BUSY)
            else:
                self.memory[:] = b"\xff" * self.SIZE
                self._out.append(p.ERASE_DONE)
        elif cmd == p.CMD_SELF_TEST:
            self._out.append(bytes([p.CMD_SELF_TEST, 0x00]))
            self._out.append(b"Self test OK (simulated)")
        return len(data)

    def read(self, size: int, timeout_ms: int = TIMEOUT_MS) -> bytes:
        if not self._out:
            raise TransportError("Timed out waiting for the programmer")
        return self._out.popleft()[:size]

    def close(self) -> None:
        pass
