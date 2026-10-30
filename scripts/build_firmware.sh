#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
# Prefer ESP-IDF's own Python interpreter over the host-test venv.
export PATH="$IDF_PYTHON_ENV_PATH/bin:$PATH"
cd firmware
if [[ "${1:-}" == --hardware ]]; then
 shift
 idf.py -B build-hardware -D SDKCONFIG=sdkconfig.hw -D SDKCONFIG_DEFAULTS=sdkconfig.hardware -D IDF_TARGET=esp32s3 build "$@"
else
 idf.py -D IDF_TARGET=esp32s3 build "$@"
 (cd build && python -m esptool --chip esp32s3 merge_bin --fill-flash-size 4MB -o flash_image.bin @flash_args)
fi
