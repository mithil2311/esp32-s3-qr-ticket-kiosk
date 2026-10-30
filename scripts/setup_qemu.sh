#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# ESP-IDF v5.5.1's optional installer selects QEMU 9.0.0.
# This project pins the newer official binary used for runtime verification.
version=esp_develop_9.2.2_20260417
archive="qemu-xtensa-softmmu-${version}-x86_64-linux-gnu.tar.xz"
if [[ "$(uname -m)" != x86_64 || "$(uname -s)" != Linux ]]; then
 echo 'This pinned binary setup supports x86_64 Linux. Use official Espressif source build instructions on other systems.' >&2
 exit 1
fi
mkdir -p .tool-deps/downloads .tool-deps/qemu-9.2.2
if [[ ! -f ".tool-deps/downloads/$archive" ]]; then
 curl -fL --retry 3 --retry-all-errors "https://dl.espressif.com/github_assets/espressif/qemu/releases/download/esp-develop-9.2.2-20260417/$archive" -o ".tool-deps/downloads/$archive"
fi
tar -xJf ".tool-deps/downloads/$archive" -C .tool-deps/qemu-9.2.2
export LD_LIBRARY_PATH="$PWD/.tool-deps/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
.tool-deps/qemu-9.2.2/qemu/bin/qemu-system-xtensa --version
