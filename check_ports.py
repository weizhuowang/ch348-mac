# SPDX-License-Identifier: GPL-2.0-or-later
"""Send read-only pings via pyserial and the ROBOTIS SDK. No motor needed."""
import serial
from dynamixel_sdk import PacketHandler, PortHandler

from probe import PING

rates = (57600, 115200, 1000000, 2000000, 3000000, 4000000, 500000, 57600)

if __name__ == "__main__":
    # macOS PTYs accept numeric termios speeds, but not IOKit's IOSSIOSPEED.
    # This map applies only to pyserial objects in this diagnostic process.
    serial.Serial.BAUDRATE_CONSTANTS = {**serial.Serial.BAUDRATE_CONSTANTS,
                                        **{rate: rate for rate in rates}}
    for port, rate in enumerate(rates):
        path = f"/tmp/ch348/{port}"
        with serial.Serial(path, rate, timeout=0.05) as device:
            device.write(PING)
            device.read(1)
        sdk = PortHandler(path)
        if not sdk.setBaudRate(rate):
            raise OSError(f"SDK rejected {rate} on {path}")
        try:
            model, result, error = PacketHandler(2.0).ping(sdk, 1)
            print(f"{path} baud={rate} model={model} SDK={result} error={error}")
        finally:
            sdk.closePort()
