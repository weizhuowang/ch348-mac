# SPDX-License-Identifier: GPL-2.0-or-later
"""Stop only verified CH348 workers, then hold their lock during replacement."""
import contextlib
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import subprocess
import time

from ownership import LOCK, ROOT, claim_owner

SUPPORT = Path.home() / "Library/Application Support/CH348"
PROJECT = Path(__file__).resolve().parents[1]


def file_users(paths):
    if not paths:
        return set()
    result = subprocess.run(["lsof", "-Fp", *paths], capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise OSError("无法确认串口占用状态：" + result.stderr)
    return {int(s[1:]) for s in result.stdout.splitlines() if re.fullmatch(r"p\d+", s)}


def lock_record():
    try:
        record = json.loads(LOCK.read_text())
        if record["role"] in ("bridge", "probe"):
            return int(record["pid"])
    except (FileNotFoundError, ValueError, TypeError, KeyError):
        pass
    return None


def usb_owners():
    raw = subprocess.check_output(["ioreg", "-a", "-r", "-n", "USB2.0 To Multi Serial Ports"])
    owners = set()

    def visit(node):
        value = str(node.get("UsbExclusiveOwner", ""))
        match = re.search(r"pid (\d+),", value)
        if match:
            owners.add(int(match[1]))
        for child in node.get("IORegistryEntryChildren", []):
            visit(child)

    for node in plistlib.loads(raw) if raw.strip() else []:
        if (node.get("idVendor"), node.get("idProduct")) == (0x1a86, 0x55d9):
            visit(node)
    return owners


def ps(pid, field):
    result = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", field + "="],
                            capture_output=True, text=True)
    return result.stdout.strip()


def managed(pid, from_lock):
    if ps(pid, "uid") != str(os.getuid()) or not re.fullmatch(
            r"python(?:3(?:\.\d+)?)?", Path(ps(pid, "comm")).name, re.IGNORECASE):
        return False
    if from_lock and lock_record() == pid:
        return True
    # Migration of pre-PID-file bridge and raw probes from our project venv.
    command = ps(pid, "command")
    if command.endswith(" " + str(SUPPORT / "bridge.py")):
        return True
    if not (command.endswith((" bridge.py", " probe.py", "/bridge.py", "/probe.py"))
            or (command.endswith(" -") and ps(pid, "ppid") == "1")):
        return False
    env = subprocess.run(["ps", "eww", "-p", str(pid), "-o", "command="],
                         capture_output=True, text=True).stdout
    launcher = re.escape(str(PROJECT / ".venv/bin/python"))
    return (PROJECT / "ch348.py").is_file() and bool(re.search(
        r"(?:^|\s)__PYVENV_LAUNCHER__=" + launcher + r"(?:3(?:\.\d+)?)?(?:\s|$)", env))


def terminate_owner(pid, from_lock):
    started = ps(pid, "lstart")
    if not started:
        return
    if not managed(pid, from_lock):
        raise RuntimeError(f"CH348 由其他程序 PID {pid} 占用。请退出该程序后重试。")
    still_owner = pid in (file_users([LOCK]) if from_lock else usb_owners())
    if still_owner and ps(pid, "lstart") == started:
        print(f"正在结束旧 CH348 进程 PID {pid}。", flush=True)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 8
        while ps(pid, "lstart") == started and not ps(pid, "stat").startswith("Z"):
            if time.monotonic() >= deadline:
                raise RuntimeError(f"PID {pid} 尚未退出，已停止安装操作。")
            time.sleep(0.1)


def check_clients():
    clients = file_users([p for p in (ROOT / str(i) for i in range(8)) if p.exists()])
    workers = file_users([LOCK]) if LOCK.is_file() else set()
    clients -= {pid for pid in workers if managed(pid, True)}
    if clients:
        raise RuntimeError(f"请先关闭占用 CH348 的串口客户端（PID {sorted(clients)}）。")


@contextlib.contextmanager
def exclusive_maintenance():
    # bootout may return before the old process releases its USB interface.
    with contextlib.ExitStack() as cleanup:
        try:
            cleanup.enter_context(claim_owner("installer"))
        except BlockingIOError:
            for pid in file_users([LOCK]):
                terminate_owner(pid, True)
            cleanup.enter_context(claim_owner("installer"))
        for pid in usb_owners():
            terminate_owner(pid, False)
        if usb_owners():
            raise RuntimeError("CH348 接口尚未释放，请稍后重试。")
        yield
