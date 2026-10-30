#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
image="${KIOSK_FLASH_IMAGE:-$PWD/results/qemu-flash.bin}"
if [[ ! -f "$image" ]]; then cp firmware/build/flash_image.bin "$image"; fi
# Keep this writable image across restarts: it includes the NVS journal.
qemu="${KIOSK_QEMU:-qemu-system-xtensa}"
if [[ -z "${KIOSK_QEMU:-}" && -x "$PWD/.tool-deps/qemu-9.2.2/qemu/bin/qemu-system-xtensa" ]]; then qemu="$PWD/.tool-deps/qemu-9.2.2/qemu/bin/qemu-system-xtensa"; fi
exec "$qemu" -machine esp32s3 -display none -monitor none \
 -drive "file=$image,if=mtd,format=raw" \
 -serial stdio -serial "tcp:127.0.0.1:${KIOSK_UART_PORT:-5556},server,nowait" \
 -nic user,model=open_eth "$@"
