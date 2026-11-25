# CH348 for DYNAMIXEL Wizard 2 on macOS

Use a WCH CH348 eight-port USB-to-UART board with DYNAMIXEL Wizard 2 on an Apple Silicon Mac. A user-space bridge exposes each UART as a pseudo-terminal (PTY). A locally built copy of Wizard lists the ports as **CH348-0** through **CH348-7**. System Integrity Protection (SIP) can stay enabled.

## Requirements

- Apple Silicon running macOS 15 or later, native Homebrew, and Xcode Command Line Tools. To install the command line tools, run `xcode-select --install`.
- DYNAMIXEL Wizard **2.16.4** installed at `/Applications/DynamixelWizard2.app`, with QtCore and QtSerialPort **6.11.2**. This is the only tested Wizard/Qt combination. The installer checks both framework versions before building the copy.
- A CH348 board (USB VID:PID `1A86:55D9`) and a connected, powered actuator for hardware use. Installation can run with the board unplugged.

## Install

```sh
git clone https://github.com/weizhuowang/ch348-mac && ./ch348-mac/install.sh
```

The installer uses Homebrew for libusb and Python, creates a per-user Python environment, and downloads the matching Qt headers and build frameworks on first installation. It creates the Wizard copy and its launcher in `~/Applications`. To check compatibility from any checkout before installing, run `./install.sh --check`.

## Connect an actuator

1. Connect the CH348 board, wire the actuator to a UART and power it.
2. Double-click **CH348 Wizard.app** in your user's Applications folder. The launcher starts the bridge and opens the locally built Wizard copy.
3. In **Options → Scan → Port**, select the port matching the wiring. Choose the actuator's protocol and baud rate, then click **Scan**. Select its ID and open **Control Table** to view live values.

Other serial clients can open `/tmp/ch348/0` through `/tmp/ch348/7`. Use one client per port. The bridge log is at `~/Library/Logs/ch348-bridge.log`. If the bridge recreates a PTY, reopen it in the client.

## Rebuild or uninstall

After updating Wizard, quit the CH348 copy and close clients using its ports. From the checkout, run:

```sh
git pull --ff-only && ./install.sh --check && ./install.sh
```

A supported version rebuilds from the currently installed Wizard. If the version check fails, wait for support for that Wizard/Qt combination before rebuilding.

To uninstall, quit the CH348 copy, close serial clients, and run `./uninstall.sh` from the checkout. It removes the user service, the two generated apps, bridge logs, and the private Python environment and Qt SDK. Shared Homebrew packages and the original Wizard stay installed.

## Tested behavior and limits

| Item | Result |
| --- | --- |
| Hardware tested | One CH348 board on macOS 15.7.7. The bridge handles one board at a time. |
| Baud rate | Up to **4 Mbps**. Chip transmit completion was verified at 4 Mbps. End-to-end actuator tests ran at 2 Mbps. |
| Protocol 2.0 ping | **1,000 of 1,000** replies at 2 Mbps. Median SDK round-trip time was about **0.8 ms**. |
| Recovery | USB interface release/reclaim and bridge restart were tested. Physical unplug/replug and system sleep/wake remain unverified. |

To repeat the ping measurement, release the port in Wizard and run the following from the checkout. The arguments are the zero-based UART number, baud rate, and actuator ID. This example uses UART 0 and ID 1.

```sh
"$HOME/Library/Application Support/CH348/venv/bin/python" qa/ping_bench.py 0 2000000 1
```

## How the Wizard copy works

The installer copies the user's own DYNAMIXEL Wizard installation and **ad-hoc re-signs the copy**. The launcher uses **DYLD injection** (`DYLD_INSERT_LIBRARIES`) to load a library that adds the eight ports to Qt's enumeration, keeps their names consistent after opening, and translates high baud rates for macOS PTYs.

This repository distributes no ROBOTIS or Qt binaries. The Wizard copy is generated on the user's Mac. The Qt headers and frameworks needed for compilation are downloaded at install time and cached for subsequent builds.

## License and affiliation

The project source is licensed under the GNU General Public License, version 2 or later. [License text](LICENSE)

This is an independent project, unaffiliated with WCH or ROBOTIS.

## 中文简述

本项目让 Apple Silicon Mac 上的 DYNAMIXEL Wizard 通过 CH348 八路板连接舵机。已验证的组合是 macOS 15.7.7、Wizard 2.16.4 和 Qt 6.11.2。按上方命令安装后，双击用户“应用程序”目录中的 **CH348 Wizard.app**，选择 **CH348-0** 至 **CH348-7** 中接线的端口，设置协议和波特率后扫描。退出副本并关闭串口客户端后，可在源码目录运行 `./uninstall.sh` 卸载。
