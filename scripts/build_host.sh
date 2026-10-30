#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for tool_dir in "$HOME/.espressif/tools/cmake/"*/bin "$HOME/.espressif/tools/ninja/"*; do
 [[ ! -d "$tool_dir" ]] || export PATH="$tool_dir:$PATH"
done
export PATH="$PWD/.venv/bin:$PATH"
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DPython3_EXECUTABLE="$PWD/.venv/bin/python" "$@"
cmake --build build
