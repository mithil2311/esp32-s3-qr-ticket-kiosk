#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .tool-deps/packages
cd .tool-deps/packages
apt download libslirp0 libsdl2-2.0-0
if apt-cache show libsdl2-classic >/dev/null 2>&1; then apt download libsdl2-classic; fi
for package in ./*.deb; do dpkg-deb -x "$package" ..; done
