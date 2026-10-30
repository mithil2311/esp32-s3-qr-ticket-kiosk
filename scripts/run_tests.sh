#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
scripts/build_host.sh
mkdir -p results
: > results/integration-events.jsonl
.venv/bin/python -m pytest -q host_tests --junitxml=results/host-tests.xml | tee results/host-tests.log
