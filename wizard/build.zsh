#!/bin/zsh
# SPDX-License-Identifier: GPL-2.0-or-later
# Build the supported Wizard copy in the installer's private staging directory.
set -eu
cd "${0:A:h}"
app=${1:?Pass the staging bundle path}
qt=${2:?Pass the matching Qt framework directory}
src=/Applications/DynamixelWizard2.app
[[ ! -e "$app" && "$app" != "$src" ]]
ditto "$src" "$app"
fw="$app/Contents/Frameworks"
clang++ -arch arm64 -std=c++17 -mmacosx-version-min=15.0 -dynamiclib \
    -F"$qt" -I"$qt/QtCore.framework/Headers" -I"$qt/QtSerialPort.framework/Headers/6.11.2/QtSerialPort" \
    -I"$qt/QtCore.framework/Headers/6.11.2" -I"$qt/QtCore.framework/Headers/6.11.2/QtCore" \
    -framework QtCore -framework QtSerialPort -Wl,-rpath,@executable_path/../Frameworks \
    ports.cpp speed-arm64.S -o "$fw/ch348-ports.dylib"
/usr/libexec/PlistBuddy -c 'Set CFBundleIdentifier local.ch348.DynamixelWizard2' "$app/Contents/Info.plist"
codesign -s - --force "$fw/ch348-ports.dylib"
codesign -s - --force "$app"
codesign --verify --deep --strict "$app"
