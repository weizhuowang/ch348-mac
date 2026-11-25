# SPDX-License-Identifier: GPL-2.0-or-later
"""Expose one connected CH348 as eight macOS PTYs."""
import contextlib
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import pty
import select
import signal
import termios
import threading
import tty

from ch348 import CH348

from ownership import ROOT, claim_owner

LOG = logging.getLogger("bridge")


def line_settings(fd):
    _, _, flags, _, _, rate, _ = termios.tcgetattr(fd)
    sizes = {termios.CS5: 5, termios.CS6: 6, termios.CS7: 7, termios.CS8: 8}
    parity = (1 if flags & termios.PARODD else 2) if flags & termios.PARENB else 0
    return (rate, sizes[flags & termios.CSIZE], 2 if flags & termios.CSTOPB else 1,
            parity, bool(flags & termios.CRTSCTS))


def connected(board, cleanup, stop, reconnect):
    masters, slaves, applied = [], [], {}
    for port in range(8):
        master, slave = pty.openpty()
        for fd in (master, slave):
            cleanup.callback(os.close, fd)
        tty.setraw(slave)
        attrs = termios.tcgetattr(slave)
        attrs[4:6] = [57600, 57600]
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        os.set_blocking(master, False)
        board.activate(port)
        board.modem(port, True, True)
        masters.append(master)
        slaves.append(slave)

    rejected = {}

    def sync(port):
        settings = line_settings(slaves[port])
        if rejected.get(port) == settings:
            return False
        if applied.get(port) != settings:
            try:
                board.configure(port, *settings)
            except ValueError as exc:
                rejected[port] = settings
                applied.pop(port, None)
                LOG.warning("port=%s rejected settings=%s: %s", port, settings, exc)
                return False
            applied[port] = settings
            LOG.info("configured port=%s baud=%s bits=%s stops=%s parity=%s flow=%s",
                     port, *settings)
        rejected.pop(port, None)
        return True

    for port in range(8):
        sync(port)
        link = ROOT / str(port)
        temporary = link.with_suffix(".new")
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(os.ttyname(slaves[port]))
        temporary.replace(link)
        cleanup.callback(link.unlink, missing_ok=True)

    done = threading.Event()
    failures = []

    def receive():
        try:
            while not done.is_set():
                for port, data in board.read(50):
                    if LOG.isEnabledFor(logging.DEBUG):
                        LOG.debug("rx port=%d bytes=%d data=%s", port, len(data), data.hex())
                    while data and not done.is_set():
                        if select.select([], [masters[port]], [], 0.05)[1]:
                            data = data[os.write(masters[port], data):]
        except Exception as exc:
            failures.append(exc)
            done.set()

    reader = threading.Thread(target=receive)
    reader.start()
    LOG.info("ready firmware=%s", board.version.hex())
    try:
        while not (stop.is_set() or done.is_set() or reconnect.is_set()):
            ready, _, _ = select.select(masters, [], [], 0.02)
            for port in range(8):
                valid = sync(port)
                if masters[port] in ready:
                    data = os.read(masters[port], 4096)
                    if not valid:
                        continue
                    board.write(port, data)
                    LOG.info("tx_empty port=%s baud=%s bytes=%s head=%s",
                             port, applied[port][0], len(data), data[:16].hex())
    finally:
        done.set()
        reader.join()
    if failures:
        raise failures[0]


def main():
    handler = RotatingFileHandler(Path.home() / "Library/Logs/ch348-bridge.log",
                                  maxBytes=2_000_000, backupCount=2)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    stop = threading.Event()
    signal.signal(signal.SIGUSR1, lambda *_: LOG.setLevel(
        logging.INFO if LOG.isEnabledFor(logging.DEBUG) else logging.DEBUG))
    reconnect = threading.Event()
    signal.signal(signal.SIGHUP, lambda *_: reconnect.set())
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    with claim_owner("bridge") as owner:
        for port in range(8):
            link = ROOT / str(port)
            if link.is_symlink():
                link.unlink()
        last_error = None
        while not stop.is_set():
            try:
                with CH348(owner) as board, contextlib.ExitStack() as cleanup:
                    last_error = None
                    connected(board, cleanup, stop, reconnect)
                if reconnect.is_set():
                    LOG.info("released USB interface; reclaim requested")
                    reconnect.clear()
                    stop.wait(1)
            except (OSError, ValueError, termios.error) as exc:
                if str(exc) != last_error:
                    LOG.warning("reconnecting: %s", exc)
                    last_error = str(exc)
                stop.wait(1)


if __name__ == "__main__":
    main()
