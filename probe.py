# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only Protocol 2.0 discovery below the PTY layer."""
import argparse
import time
from dynamixel_sdk import PacketHandler
from ch348 import CH348

RATES = (57600, 115200, 1000000, 2000000, 3000000, 4000000, 9600, 250000, 500000, 1500000)
PING = bytes.fromhex("ff ff fd 00 fe 03 00 01 31 42")


def models(data):
    sdk = PacketHandler(2.0)
    found = []
    for i in range(len(data) - 13):
        frame = data[i:i + 14]
        if (frame[:4] == PING[:4] and frame[5:8] == b'\x07\x00\x55' and frame[8] in (0, 128)
                and sdk.updateCRC(0, frame, 12) == int.from_bytes(frame[12:], 'little')):
            found.append((frame[4], int.from_bytes(frame[9:11], 'little')))
    return found


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rates", type=int, nargs="+", default=RATES)
    args = parser.parse_args()
    with CH348() as board:
        print("chip version", board.version.hex(), flush=True)
        for port in range(8):
            board.activate(port)
            board.modem(port, True, True)
        for baud in args.rates:
            for port in range(8):
                board.configure(port, baud)
                board.write(port, PING)
                received = bytearray()
                deadline = time.monotonic() + 0.9
                while time.monotonic() < deadline:
                    for channel, data in board.read(50):
                        if port == channel:
                            received.extend(data)
                print(baud, port, "tx_empty", "rx", received.hex() or "-",
                      "id/model", models(received), flush=True)
