# SPDX-License-Identifier: GPL-2.0-or-later
"""Coordinate USB access across the service, direct probes and the installer."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import stat

ROOT = Path("/tmp/ch348")
LOCK = ROOT / "bridge.lock"


def private_directory():
    ROOT.mkdir(mode=0o700, exist_ok=True)
    info = ROOT.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError(f"expected a private directory at {ROOT}")


@contextlib.contextmanager
def claim_owner(role):
    private_directory()
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as stream:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not os.path.samestat(os.fstat(fd), LOCK.lstat()):
            raise OSError("CH348 lock was replaced; retry")
        stream.seek(0)
        stream.truncate()
        json.dump({"pid": os.getpid(), "role": role}, stream)
        stream.flush()
        yield stream
