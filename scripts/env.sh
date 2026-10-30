#!/usr/bin/env bash
# Source this file; it does not modify shell startup files.
KIOSK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export IDF_PATH="${IDF_PATH:-$HOME/esp/esp-idf-v5.5.1}"
export LD_LIBRARY_PATH="$KIOSK_ROOT/.tool-deps/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if [[ -f "$IDF_PATH/export.sh" ]]; then
  source "$IDF_PATH/export.sh" >/dev/null
fi
for tool_dir in "${IDF_TOOLS_PATH:-$HOME/.espressif}/tools/qemu-xtensa/"*/qemu/bin; do
 [[ ! -d "$tool_dir" ]] || export PATH="$tool_dir:$PATH"
done
if [[ -x "$KIOSK_ROOT/.tool-deps/qemu-9.2.2/qemu/bin/qemu-system-xtensa" ]]; then
 export PATH="$KIOSK_ROOT/.tool-deps/qemu-9.2.2/qemu/bin:$PATH"
fi
if [[ -n "${IDF_PYTHON_ENV_PATH:-}" ]]; then
 export PATH="$IDF_PYTHON_ENV_PATH/bin:$PATH"
fi
