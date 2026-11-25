# SPDX-License-Identifier: GPL-2.0-or-later
"""Install or remove the per-user CH348 bridge and supported Wizard copy."""
import argparse
import contextlib
import fcntl
import os
import platform
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path.home()
ROOT = Path(__file__).resolve().parents[1]
SUPPORT = HOME / "Library/Application Support/CH348"
APPS = HOME / "Applications"
ORIGINAL = Path("/Applications/DynamixelWizard2.app")
COPY = APPS / "DynamixelWizard2-CH348.app"
LAUNCHER = APPS / "CH348 Wizard.app"
LABEL = "local.ch348.bridge"
DOMAIN = f"gui/{os.getuid()}"
PLIST = LABEL + ".plist"
QT = "6.11.2"
WIZARD = "2.16.4"
VENV = SUPPORT / "venv"
MARKER = SUPPORT / ".ch348-managed"
sys.path.insert(0, str(ROOT))
from lifecycle import check_clients, exclusive_maintenance


def run(*args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def output(*args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()


def plist_field(path, key):
    with path.open("rb") as stream:
        return plistlib.load(stream)[key]


def framework_version(directory, name):
    binary = directory / f"{name}.framework" / name
    listing = output("otool", "-arch", "arm64", "-L", binary)
    for line in listing.splitlines():
        if line.strip().startswith(f"@rpath/{name}.framework/"):
            match = re.search(r"current version ([\d.]+)\)", line)
            if match:
                return match[1]
    raise ValueError(f"无法识别 {binary} 的 arm64 版本。")


def wizard_check():
    if not ORIGINAL.is_dir():
        return f"请先将 DYNAMIXEL Wizard {WIZARD} 安装到 {ORIGINAL}。"
    run("lipo", ORIGINAL / "Contents/MacOS/DynamixelWizard2", "-verify_arch", "arm64")
    version = plist_field(ORIGINAL / "Contents/Info.plist", "CFBundleShortVersionString")
    frameworks = ORIGINAL / "Contents/Frameworks"
    versions = {name: framework_version(frameworks, name) for name in ("QtCore", "QtSerialPort")}
    if version != WIZARD or any(v != QT for v in versions.values()):
        return f"检测到 Wizard {version}、{versions}。完整安装需要 Wizard {WIZARD} 和 Qt {QT}。"
    return None


def brew_binary():
    brew = shutil.which("brew") or "/opt/homebrew/bin/brew"
    if not Path(brew).is_file():
        raise ValueError("请先从 https://brew.sh 安装 Apple Silicon 版 Homebrew。")
    if output(brew, "--prefix") == "/usr/local":
        raise ValueError("请使用 Apple Silicon 版 Homebrew，并将其 bin 目录放到 PATH 前面。")
    return brew


def dependencies(brew):
    prefix = Path(output(brew, "--prefix"))
    if not (prefix / "opt/libusb/lib/libusb-1.0.dylib").is_file():
        run(brew, "install", "libusb")
    python = prefix / "bin/python3"
    if not python.exists() or subprocess.call([str(python), "-c",
            "import sys; sys.exit(sys.version_info < (3,10))"]):
        run(brew, "install", "python@3.12")
        python = prefix / "opt/python@3.12/bin/python3.12"
    # Always use the stable final venv path (pip console scripts embed it).
    if not (VENV / "bin/python").exists():
        run(python, "-m", "venv", VENV)
    python = VENV / "bin/python"
    run(python, "-m", "pip", "--disable-pip-version-check", "install", "-r", ROOT / "requirements.txt")
    run(python, "-c", "import usb.core; d=usb.core.find(idVendor=0x1a86,idProduct=0x55d9); "
        "print('已检测到 CH348。' if d is not None else '未接入 CH348；可完成安装，接板后启动。')")
    return python


def qt_lib(base):
    return base / QT / "macos/lib"


def check_sdk(base):
    lib = qt_lib(base)
    headers = [lib / "QtCore.framework/Headers/qtversion.h",
               lib / f"QtSerialPort.framework/Headers/{QT}/QtSerialPort/private/qserialportinfo_p.h"]
    return all(h.is_file() for h in headers) and all(
        framework_version(lib, name) == QT for name in ("QtCore", "QtSerialPort"))


def sdk(python):
    base = SUPPORT / "qt-sdk"
    if not check_sdk(base):
        with tempfile.TemporaryDirectory(dir=SUPPORT, prefix=".qt-") as temp:
            stage = Path(temp)
            run(python, "-m", "pip", "--disable-pip-version-check", "install", "aqtinstall==3.3.0")
            run(python, "-m", "aqt", "install-qt", "mac", "desktop", QT, "clang_64",
                "--archives", "qtbase", "--modules", "qtserialport", "-O", stage, cwd=stage)
            if not check_sdk(stage):
                raise ValueError("Qt SDK 校验失败，请重新运行安装。")
            if base.exists():
                base.rename(stage / "previous-sdk")
            base.mkdir()
            (stage / QT).rename(base / QT)
    return qt_lib(base)


def verify_managed():
    for bundle, expected in ((COPY, "local.ch348.DynamixelWizard2"), (LAUNCHER, "local.ch348.launcher")):
        if bundle.is_symlink() or (bundle.exists() and
                plist_field(bundle / "Contents/Info.plist", "CFBundleIdentifier") != expected):
            raise ValueError(f"请先移走同名的其他应用：{bundle}")
    if SUPPORT.is_symlink():
        raise ValueError(f"安装目录是符号链接：{SUPPORT}")
    if SUPPORT.exists() and not MARKER.is_file():
        # Recognize the original installation made before the marker existed.
        if not (SUPPORT / PLIST).is_file() or plist_field(SUPPORT / PLIST, "Label") != LABEL:
            raise ValueError(f"请先移走现有的非本项目目录：{SUPPORT}")


def require_idle():
    processes = output("ps", "-x", "-o", "comm=")
    if str(COPY / "Contents/MacOS/DynamixelWizard2") in processes.splitlines():
        raise ValueError("请先退出用户 Applications 里的 CH348 Wizard 副本，再重试。")
    check_clients()


def unload():
    service = f"{DOMAIN}/{LABEL}"
    if subprocess.call(["launchctl", "print", service], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL) != 0:
        return False
    run("launchctl", "bootout", service)
    return True


def make_launcher(bundle, icon):
    contents = bundle / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "Resources").mkdir()
    executable = contents / "MacOS/launch"
    shutil.copy2(ROOT / "launcher/launch.zsh", executable)
    executable.chmod(0o755)
    shutil.copy2(icon, contents / "Resources/CH348.icns")
    (contents / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": "local.ch348.launcher", "CFBundleName": "CH348 Wizard",
        "CFBundleExecutable": "launch", "CFBundlePackageType": "APPL",
        "CFBundleIconFile": "CH348.icns", "CFBundleVersion": "1", "LSUIElement": True}))
    run("codesign", "-s", "-", bundle)
    run("codesign", "--verify", "--strict", bundle)


def install_apps(python):
    frameworks = sdk(python)
    APPS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=APPS, prefix=".ch348-") as app_temp, \
            tempfile.TemporaryDirectory(dir=SUPPORT, prefix=".install-") as data_temp:
        stage, data = Path(app_temp), Path(data_temp)
        run(ROOT / "wizard/build.zsh", stage / COPY.name, frameworks)
        make_launcher(stage / LAUNCHER.name, ORIGINAL / "Contents/Resources/ico_256.icns")
        for file in ("bridge.py", "ch348.py", "ownership.py"):
            shutil.copy2(ROOT / file, data / file)
        (data / PLIST).write_bytes(plistlib.dumps({
            "Label": LABEL, "ProgramArguments": [str(python), str(SUPPORT / "bridge.py")],
            "KeepAlive": True, "LimitLoadToSessionType": "Aqua", "ThrottleInterval": 3,
            "StandardErrorPath": str(HOME / "Library/Logs/ch348-service-errors.log")}))
        require_idle()
        loaded = unload()
        with contextlib.ExitStack() as rollback:
            if loaded:
                rollback.callback(run, "launchctl", "bootstrap", DOMAIN, SUPPORT / PLIST)
            with exclusive_maintenance():
                for new, dest in [(stage / COPY.name, COPY), (stage / LAUNCHER.name, LAUNCHER),
                                  *((data / n, SUPPORT / n) for n in ("bridge.py", "ch348.py", "ownership.py", PLIST))]:
                    if dest.exists():
                        backup = new.with_name("old-" + new.name)
                        dest.rename(backup)
                        rollback.callback(backup.rename, dest)
                    new.rename(dest)
                    rollback.callback(dest.rename, new)
            if loaded:
                run("launchctl", "bootstrap", DOMAIN, SUPPORT / PLIST)
            rollback.pop_all()
    print(f"安装完成。双击 {LAUNCHER} 启动。")


def uninstall():
    verify_managed()
    require_idle()
    unload()
    with exclusive_maintenance():
        remove_files()
    print("卸载完成。")


def remove_files():
    for path in (COPY, LAUNCHER, SUPPORT):
        if path.exists():
            shutil.rmtree(path)
    logs = HOME / "Library/Logs"
    for name in ("ch348-service-errors.log", "ch348-bridge.log", "ch348-bridge.log.1", "ch348-bridge.log.2"):
        (logs / name).unlink(missing_ok=True)
    ports = Path("/tmp/ch348")
    if ports.exists():
        info = ports.lstat()
        if stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077:
            for port in range(8):
                for link in (ports / str(port), ports / f"{port}.new"):
                    if link.is_symlink():
                        link.unlink()
            (ports / "bridge.lock").unlink(missing_ok=True)
            if not any(ports.iterdir()):
                ports.rmdir()


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    for flag in ("check", "deps-only", "uninstall"):
        modes.add_argument("--" + flag, action="store_true")
    args = parser.parse_args()
    if args.uninstall:
        uninstall()
        return
    if platform.machine() != "arm64" or int(platform.mac_ver()[0].split(".")[0]) < 15:
        raise ValueError("需要 Apple Silicon 和 macOS 15 或更高版本。")
    brew = brew_binary()
    try:
        issue = wizard_check()
    except (OSError, KeyError, ValueError, subprocess.CalledProcessError) as exc:
        issue = f"无法校验 Wizard/Qt 的 arm64 框架：{exc}"
    if issue:
        if not args.deps_only:
            raise ValueError(issue + " 仅验证依赖可用 ./install.sh --deps-only。")
        print(issue + " 本次只安装依赖。", flush=True)
    else:
        print(f"Wizard {WIZARD}、Qt {QT} 和基本环境检查通过。", flush=True)
    if args.check:
        return
    verify_managed()
    if not args.deps_only:
        require_idle()
    SUPPORT.mkdir(mode=0o700, parents=True, exist_ok=True)
    MARKER.touch()
    python = dependencies(brew)
    if not args.deps_only:
        install_apps(python)


if __name__ == "__main__":
    # Serialize swaps and removal across different clones for the same user.
    fd = os.open(HOME / "Library/Application Support", os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        main()
    except (ValueError, RuntimeError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        sys.exit(str(exc))
    finally:
        os.close(fd)
