#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
set -eu
case "$(uname -s):$(uname -m)" in
    Darwin:arm64) ;;
    *) echo '需要原生 Apple Silicon macOS 终端（arm64）。' >&2; exit 1 ;;
esac
if ! xcode-select -p >/dev/null 2>&1 || ! xcrun --find clang++ >/dev/null 2>&1; then
    echo '请运行 xcode-select --install，完成后重试。' >&2
    exit 1
fi
exec /usr/bin/python3 "$(dirname "$0")/launcher/install.py" "$@"
