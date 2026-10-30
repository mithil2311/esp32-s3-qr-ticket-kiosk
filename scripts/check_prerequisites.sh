#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
uname -a
cat /etc/os-release
failed=0
for tool in git gcc g++ python3 cmake ninja; do
  if ! command -v "$tool"; then failed=1; fi
done
python3 --version
if command -v idf.py >/dev/null; then idf.py --version || failed=1; else echo 'ESP-IDF absent'; failed=1; fi
if command -v qemu-system-xtensa >/dev/null; then
  qemu-system-xtensa --version || failed=1
  qemu-system-xtensa -machine help | rg esp32s3 || failed=1
  ldd "$(command -v qemu-system-xtensa)" | rg 'not found' && failed=1
else
  echo 'Espressif QEMU absent'; failed=1
fi
exit "$failed"
