#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export IDF_PATH="${IDF_PATH:-$HOME/esp/esp-idf-v5.5.1}"
export IDF_GITHUB_ASSETS="${IDF_GITHUB_ASSETS:-dl.espressif.com/github_assets}"
if [[ ! -d "$IDF_PATH/.git" ]]; then
 mkdir -p "$(dirname "$IDF_PATH")"
 git clone --depth 1 --branch v5.5.1 --recursive --shallow-submodules https://github.com/espressif/esp-idf.git "$IDF_PATH"
fi
if [[ "$(git -C "$IDF_PATH" describe --tags --exact-match)" != v5.5.1 ]]; then
 echo 'Expected ESP-IDF v5.5.1; use a separate installation path.' >&2; exit 1
fi
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://dl.espressif.com/pypi}"
"$IDF_PATH/install.sh" esp32s3
python3 "$IDF_PATH/tools/idf_tools.py" install cmake ninja
# If QEMU lacks shared libraries, install Ubuntu prerequisites from README or use:
# scripts/setup_qemu_user_libs.sh (extracts packages locally, needs no root).
