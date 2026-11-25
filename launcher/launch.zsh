#!/bin/zsh
# SPDX-License-Identifier: GPL-2.0-or-later
set -eu
app="$HOME/Applications/DynamixelWizard2-CH348.app"
label=local.ch348.bridge
domain="gui/$(id -u)"
if ! launchctl print "$domain/$label" >/dev/null 2>&1; then
    launchctl bootstrap "$domain" "$HOME/Library/Application Support/CH348/$label.plist"
fi
launchctl kickstart "$domain/$label"
for i in {1..50}; do
    [[ -c /tmp/ch348/7 ]] && break
    sleep 0.1
done
exec /usr/bin/open --env DYLD_INSERT_LIBRARIES="$app/Contents/Frameworks/ch348-ports.dylib" "$app"
