# Final verification report

Executed on Ubuntu 26.04.1 x86_64; generated 2026-10-30T12:39:38.420764+00:00. GCC 15.2.0, CMake 3.30.2, Ninja 1.12.1, Python 3.14.4; ESP-IDF v5.5.1; Espressif QEMU 9.2.2 esp_develop_9.2.2_20260417.

| Milestone | Executed evidence | Result |
|---|---|---|
| 1: inspect and architecture | New project created after workspace/toolchain inspection; architecture and durable protocol documented | Complete |
| 2: shared controller and host | CMake build; actual C++ executable invoked by integration tests | Pass |
| 3: backend and printer | FastAPI, SQLite persistence, concurrent reservation/idempotency and ESC/POS decoding exercised by real HTTP | Pass |
| 4: ESP-IDF adapters | ESP32-S3 emulation and hardware configurations compiled with ESP-IDF | Both pass |
| 5: QEMU | Actual Xtensa firmware; 8 runtime scenarios and persistent-NVS restart | Pass |
| 6: faults and measurements | 31 host tests; 31 ASan/UBSan tests; 25 successful native benchmark transactions | Pass |
| 7: verification | Fresh logs, JUnit, JSON/CSV, artifact hashes and reports collected | Complete |

## Acceptance criteria

- Native simulator builds and runs: verified by [build log](../results/host-build.log) and [31 passing tests](../results/host-tests.xml).
- Functional and fault assertions exit successfully: [31 host tests](../results/host-tests.log), [31 sanitizer tests](../results/asan-tests.log). The runner uses nonzero exit on assertion failures.
- Firmware builds for ESP32-S3: [QEMU configuration](../results/firmware-build.log), [hardware configuration](../results/hardware-build.log). Hardware compilation is not hardware validation.
- QEMU execution demonstrated: [8 checks](../results/qemu-tests.log), full console logs and JSON telemetry retained.
- Invalid/expired/duplicate tickets do not print: tested against printer job counts; malformed/corrupt/overlength scanner frames are dropped.
- Backend errors never authorize implicitly: timeout, HTTP 500, refused connection, retry exhaustion, and lost commit-response paths tested.
- Restart recovery: CREATED, RESERVED, PRINTING, CONFIRMED, COMMITTED, and server-commit-before-local-journal-write cases exercised. A journal storage error fails closed.
- Uncertain printing never triggers automatic reprinting: restart tests and explicit operator reconciliation assert unchanged job counts.
- Every state transition is logged with monotonic timestamps, operation ID and reason; benchmark outputs derive from actual executions.

The requested eighteen scenarios are all covered: valid, invalid, expired, duplicate, rapid scans, backend timeout, HTTP 500, network loss, paper-out, busy, cutter failure, restart during printing, restart after reservation, duplicate backend requests, partial UART, malformed QR, overflow, and uncertain-state recovery. Additional tests cover concurrent competing reservations, corrupted journal, scanner disconnect/stale/overlength frames, journal-write failures, external input timestamps, restart around commit, and retry telemetry.

## QEMU checks

- UART1 external TCP input and valid ticket: PASS.
- invalid ticket never prints: PASS.
- duplicate suppression: PASS.
- partial UART packets: PASS.
- backend 500 exponential retry: PASS.
- paper out recovery before print: PASS.
- cutter uncertainty and operator commit without reprint: PASS.
- NVS restart during printing has no automatic reprint: PASS.

## Explicit limits and remaining hardware work

The external UART1 socket was verified on the installed Espressif QEMU release. This exercises emulated UART registers/interrupts and ESP-IDF's UART driver; it does not emulate the GM75 optics, GPIO electrical levels, serial bit timing or unplug detection. The alternative firmware console injection option is documented and is not the path used in the successful UART1 checks.

QEMU uses OpenETH, not Wi-Fi. USB Host and Bluetooth are not implemented. GPIO indicator electrical behavior is not tested. The virtual printer reports completion of its own model; real KP307-UB physical completion remains unproven. Its transport deliberately fails closed in hardware builds until the actual interface/status semantics are verified. See [hardware checklist](hardware-integration.md).

Process termination and restart with a persistent flash image verify logical NVS recovery; they do not model analog brownout or torn physical flash writes. Production authentication/TLS/operator UI, printer transport, NVS endurance qualification and real hardware validation remain deployment/integration work. The sample backend is loopback-only and includes unauthenticated fault controls.

The first QEMU harness closed stdin and therefore lost UART0 console output while the guest was running. Keeping the stdio pipe open resolved this. No peripheral limitation or physical printing claim is inferred from that failed initial run.

## Reproduce

```bash
./scripts/check_prerequisites.sh
./scripts/run_tests.sh
./scripts/build_firmware.sh
./scripts/build_firmware.sh --hardware
.venv/bin/python scripts/benchmark.py
.venv/bin/python scripts/test_qemu.py
.venv/bin/python scripts/collect_results.py
```

Sanitizer reproduction uses a separate build directory:

```bash
source scripts/env.sh
cmake -S . -B build-asan -G Ninja -DKIOSK_SANITIZE=ON -DPython3_EXECUTABLE="$PWD/.venv/bin/python"
cmake --build build-asan
KIOSK_HOST="$PWD/build-asan/kiosk_host" .venv/bin/python -m pytest -q host_tests --junitxml=results/asan-tests.xml > results/asan-tests.log
```

The reports' binaries and SHA-256 hashes are in [manifest.json](../results/manifest.json). Binaries, runtime databases, journals, local packages, and virtual environments are excluded from source control. These reports record local executed checks; no remote CI result is claimed.
