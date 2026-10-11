#!/usr/bin/env bash
# Reproduce the working environment on macOS (tested: M1 Pro, pyenv Python 3.10.6, 2026-10-09).
# Two gotchas this script works around:
#  1. pyastar2d (TA-RWARE's A*) fails to compile when pyenv Python's baked-in Xcode -I flags mix with
#     the CommandLineTools SDK headers. Fix: build with the Xcode SDK as sysroot.
#  2. gymnasium>=1.x breaks on Python 3.10.6 (typing bug). Pin 0.29.1, which TA-RWARE was written against.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip setuptools wheel
.venv/bin/pip install -q matplotlib "numpy<2" "gymnasium==0.29.1" "six==1.16.0" "pyglet==1.5.11" "networkx==3.2.1"
.venv/bin/pip install -q "torch==2.14.1" --index-url https://download.pytorch.org/whl/cpu
mkdir -p vendor
[ -d vendor/tarware ]   || git clone -q https://github.com/uoe-agents/task-assignment-robotic-warehouse.git vendor/tarware
[ -d vendor/pyastar2d ] || git clone -q https://github.com/raulsteleac/pyastar2d_TARWARE vendor/pyastar2d
XSDK=/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk
if [ -d "$XSDK" ]; then
  export SDKROOT=$XSDK CFLAGS="-isysroot $XSDK" CPPFLAGS="-isysroot $XSDK" CXXFLAGS="-isysroot $XSDK" LDFLAGS="-isysroot $XSDK"
fi
(cd vendor/pyastar2d && ../../.venv/bin/pip install -q --no-build-isolation .)
.venv/bin/pip install -q --no-deps -e vendor/tarware
.venv/bin/python -c "import gymnasium as gym, tarware; e=gym.make('tarware-small-4agvs-2pickers-globalobs-v1'); e.unwrapped.reset(seed=0); print('tarware OK, agents =', e.unwrapped.num_agents)"
