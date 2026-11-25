# SPDX-License-Identifier: GPL-2.0-or-later
"""Measure successful unicast Protocol 2.0 round trips on one idle CH348 UART."""
import argparse
import math
import statistics
import time
from collections import Counter

import serial
from dynamixel_sdk import COMM_SUCCESS, PacketHandler, PortHandler

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", type=int, choices=range(8))
    parser.add_argument("baud", type=int)
    parser.add_argument("device_id", type=int, choices=range(253), metavar="ID")
    args = parser.parse_args()
    serial.Serial.BAUDRATE_CONSTANTS = {**serial.Serial.BAUDRATE_CONSTANTS, args.baud: args.baud}
    port = PortHandler(f"/tmp/ch348/{args.port}")
    packet = PacketHandler(2.0)
    if not port.setBaudRate(args.baud):
        raise OSError("SDK rejected baud rate")
    try:
        model, comm, error = packet.read2ByteTxRx(port, args.device_id, 0)
        if comm != COMM_SUCCESS or error:
            raise OSError(f"model read failed: comm={comm}, error={error}")
        samples, failures = [], Counter()
        for _ in range(1000):
            start = time.perf_counter_ns()
            ping_model, comm, error = packet.ping(port, args.device_id)
            elapsed = (time.perf_counter_ns() - start) / 1e6
            if comm == COMM_SUCCESS and not error and ping_model == model:
                samples.append(elapsed)
            else:
                failures[(comm, error, ping_model)] += 1
        print(f"port={port.port_name} baud={args.baud} ID={args.device_id} model(address=0)={model}")
        print(f"success={len(samples)}/1000 failures={dict(failures)}")
        if samples:
            p99 = sorted(samples)[math.ceil(0.99 * len(samples)) - 1]
            print(f"RTT_ms median={statistics.median(samples):.3f} p99={p99:.3f} "
                  f"min={min(samples):.3f} max={max(samples):.3f}")
    finally:
        port.closePort()
