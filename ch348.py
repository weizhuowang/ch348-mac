# SPDX-License-Identifier: GPL-2.0-or-later
# Protocol formats follow WCH's ch9344.c (GPL-2.0+).
# Upstream copyright (C) 2026 Nanjing Qinheng Microelectronics Co., Ltd.
# https://github.com/WCHSoftGroup/ch9344ser_linux/blob/dc1b70ad0920f526874514f7f6957b4805173ee9/driver/ch9344.c
"""User-space CH348 transport. Packet layout from WCH's ch9344ser_linux."""
from contextlib import ExitStack
import struct
import time

import usb.core
import usb.util

from ownership import claim_owner


def register_base(port):
    if port not in range(8):
        raise ValueError("UART index must be 0..7")
    return 16 * (port % 4) + 8 * (port // 4)


class CH348:
    def __init__(self, owner=None):
        self.owner = owner

    def __enter__(self):
        self.resources = ExitStack()
        try:
            if self.owner is None:
                self.resources.enter_context(claim_owner("probe"))
            elif self.owner.closed:
                raise RuntimeError("bridge lock is closed")
            self.device = usb.core.find(idVendor=0x1a86, idProduct=0x55d9)
            if self.device is None:
                raise OSError("CH348 disconnected")
            self.resources.callback(usb.util.dispose_resources, self.device)
            self.device.set_configuration()
            usb.util.claim_interface(self.device, 0)
            self.version = bytes(self.device.ctrl_transfer(0xc0, 0x96, 0, 0, 4))
            if len(self.version) != 4:
                raise OSError("incomplete version response")
            self.is_q = bool(self.version[1] & 0x80)
            if self.version[0] >= 0x8a:
                self.command(0x90, 0x9d, 1, 0, 0, 0, 0, 0)
            return self
        except BaseException:
            self.resources.close()
            raise

    def __exit__(self, *_):
        self.resources.close()

    def command(self, *values):
        self._write(0x01, bytes(values))

    def _write(self, endpoint, data):
        if self.device.write(endpoint, data, 1000) != len(data):
            raise OSError("short USB write")

    def activate(self, port):
        base = register_base(port)
        self.command(0xc0, base + 2, 0x87)
        self.command(0xc0, base + 4, 0x08)

    def configure(self, port, baud, bits=8, stops=1, parity=0, flow=False):
        base = register_base(port)
        if not (1200 <= baud <= 4000000 and bits in range(5, 9)
                and stops in (1, 2) and parity in range(5)):
            raise ValueError("unsupported UART settings")
        timeout = 5 if baud >= 921600 else 150000 // baud + 1
        # Both rotate and XOR keys may be zero in WCH's R_INIT format.
        line = struct.pack(">IBBBB", baud, 2 if stops == 2 else 0, parity, bits, timeout)
        self.command(0x90 | port, 0xa1, port, *line, 0)
        self.command(0xc0, base + 1, 0x0f)
        if not self.is_q or port < 4:
            self.command(0x80, base + 4, 0x50 | int(flow))
        elif flow:
            raise ValueError("CH348Q has no flow-control pins on this UART")

    def modem(self, port, dtr, rts):
        base = register_base(port)
        if self.is_q and port >= 4:
            return
        self.command(0x80, base + 4, int(dtr))
        self.command(0x80, base + 4, 0x10 | int(rts))

    def write(self, port, data):
        register_base(port)
        for start in range(0, len(data), 509):
            chunk = data[start:start + 509]
            self._write(0x02, struct.pack("<BH", port, len(chunk)) + chunk)
            self.wait_empty(port)

    def wait_empty(self, port):
        # Serialise writes across UARTs so only one TX-empty is outstanding.
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            try:
                status = self.device.read(0x81, 512, 250)
            except usb.core.USBTimeoutError:
                continue
            offset = 0
            while offset + 2 <= len(status):
                channel, reg = status[offset:offset + 2]
                if reg & 15 == 2 and channel & 15 == port:
                    return
                length = {0xa1: 12, 0x9d: 4, 0x85: 4}.get(reg, 3)
                offset += length
        raise TimeoutError(f"UART {port} TX-empty timeout")

    def read(self, timeout_ms):
        try:
            packet = bytes(self.device.read(0x82, 512, timeout_ms))
        except usb.core.USBTimeoutError:
            return []
        frames = []
        for offset in range(0, len(packet), 32):
            port, length = packet[offset:offset + 2]
            if port >= 8 or length > 30 or offset + 2 + length > len(packet):
                raise OSError("invalid CH348 RX record: " + packet.hex())
            frames.append((port, packet[offset + 2:offset + 2 + length]))
        return frames
