# ESP32-S3 QR ticket kiosk

Working C++17/ESP-IDF application with a native Linux simulator, persistent FastAPI/SQLite backend, virtual ESC/POS printer, fault tests, and actual ESP32-S3 execution in Espressif QEMU.

Project verification and measured results are in [docs/verification.md](docs/verification.md). Business logic and recovery policy are in [docs/architecture.md](docs/architecture.md). Real printer integration is intentionally incomplete until the SHREYANS KP307-UB interface is verified; USB Host and Bluetooth are not implemented or assumed.

## Execution modes

| Mode | Executes | Scanner | Network | Printer | Persistence |
|---|---|---|---|---|---|
| Host | Native Linux C++ executable | Incremental byte parser via JSONL stdin | Real loopback HTTP | Python ESC/POS job model | Atomic file journal + fsync |
| QEMU | Built ESP32-S3 Xtensa firmware + FreeRTOS | Verified UART1 TCP chardev | Emulated OpenETH with user-mode NAT | HTTP virtual printer | ESP-IDF NVS in writable emulated flash |
| Hardware | ESP32-S3 firmware | Real UART1 | Wi-Fi station adapter | Unconfigured transport fails closed | ESP-IDF NVS |

No QEMU result measures real ESP32 CPU speed, scanner optics/FPS, physical printer completion, Wi-Fi, USB Host, Bluetooth, GPIO drive or electrical behavior.

## Graphical simulator

```bash
.venv/bin/python simulator/dashboard.py --port 8080
```

Open **http://127.0.0.1:8080** to see the scanner, ESP32-S3 controller, indicators, virtual printer receipt, live activity and firmware telemetry. The controls inject actual UART1 bytes into the QEMU guest and apply real backend/printer test faults. **Restart guest** retains NVS and reservations; uncertain printing requires operator reconciliation.

The launcher starts its own isolated backend and QEMU session, so ports 9000 and 5556 must be free. This is a local graphical interface around the running firmware, with mocked peripherals. It does not emulate an LCD, scanner optics or physical GPIO/printer behavior. See [graphical simulator instructions and executed checks](docs/graphical-simulation.md).

## Ubuntu installation

Tested here on Ubuntu 26.04.1 x86_64, Python 3.14.4, GCC 15.2.0, ESP-IDF **v5.5.1**, and Espressif QEMU **9.2.2 / esp_develop_9.2.2_20260417**. Standard Ubuntu 22.04/24.04 prerequisites can be installed with:

```bash
sudo apt-get update
sudo apt-get install -y git wget curl gcc g++ make flex bison gperf python3 python3-pip python3-venv cmake ninja-build ccache libffi-dev libssl-dev dfu-util libusb-1.0-0 libgcrypt20 libglib2.0-0 libpixman-1-0 libsdl2-2.0-0 libslirp0
git clone https://github.com/mithil2311/esp32-s3-qr-ticket-kiosk.git
cd esp32-s3-qr-ticket-kiosk
./scripts/setup_host.sh
./scripts/setup_idf.sh
./scripts/setup_qemu.sh
./scripts/check_prerequisites.sh
```

Ubuntu 26.04 uses some `t64` library package names and a `libsdl2-classic` dependency. This workstation required **no sudo changes**: compiler/Python were present, CMake/Ninja were installed with ESP-IDF, and QEMU libraries were extracted locally:

```bash
./scripts/setup_qemu_user_libs.sh
./scripts/setup_qemu.sh
```

If Python package downloads stall on an IPv6 route, an opt-in install-only workaround is included:

```bash
KIOSK_INSTALL_IPV4=1 PYTHONPATH="$PWD/scripts/install_ipv4" ./scripts/setup_host.sh
PIP_INDEX_URL=https://dl.espressif.com/pypi ./scripts/setup_idf.sh
```

The ESP-IDF script pins v5.5.1 under `~/esp/esp-idf-v5.5.1`, installs its tools under `~/.espressif`, and uses Espressif's official Python/download mirrors. `IDF_PATH` and `IDF_TOOLS_PATH` can override those locations. It does not alter shell startup files. The tested host Python dependency versions are recorded in `requirements.lock.txt`; CMake/Ninja can come from the system, the host venv, or the ESP-IDF tool installation.

## Build and run native tests

```bash
./scripts/build_host.sh
./scripts/run_tests.sh
.venv/bin/python scripts/benchmark.py
```

`run_tests.sh` starts a private backend on a dynamically allocated loopback port, runs the real native executable as subprocesses, and exits nonzero on failed assertions. It generates `results/host-tests.xml`, `results/host-tests.log`, and `results/integration-events.jsonl`. An optional sanitizer build is available:

```bash
./scripts/build_host.sh -DKIOSK_SANITIZE=ON
./scripts/run_tests.sh
```

For interactive use, start the local backend in one terminal:

```bash
.venv/bin/python simulator/mock_backend.py --port 9000
```

Then start the native application in another terminal:

```bash
./build/kiosk_host --backend http://127.0.0.1:9000 --printer http://127.0.0.1:9000 --journal ./demo.journal --device demo-kiosk
```

Enter JSON commands, one per line:

```json
{"id":1,"cmd":"scan","data":"TKT:valid-001\r\n"}
{"id":2,"cmd":"status"}
{"id":3,"cmd":"raw","hex":"544b543a76616c69642d3030320a"}
{"id":4,"cmd":"disconnect"}
{"id":5,"cmd":"retry"}
{"id":6,"cmd":"resolve_printed"}
```

`resolve_printed` means an operator has verified the ticket was printed. It never prints again. If the operator cannot establish the outcome, leave the transaction quarantined. `retry` is accepted only in recoverable states and never in `UNCERTAIN`. A changed device ID or corrupt journal locks recovery. Each journal is exclusively locked against concurrent native processes.

For a piped scanner simulation, EOF drains accepted transactions before exit:

```bash
.venv/bin/python simulator/scanner_injector.py --payload TKT:valid-003 --scenario partial --delay-ms 100 | ./build/kiosk_host --journal ./piped.journal --device piped-kiosk
```

`input_ms` spans the first byte (or host injector monotonic timestamp) to completed frame receipt. `total_ms` spans completed receipt to the durable commit or failed attempt; `end_to_end_ms` includes both. QEMU uses guest timestamps, without equating host and guest clocks.

The scanner utility supports `valid`, `invalid`, `expired`, `partial`, `corrupt`, `malformed`, `repeated`, `rapid`, and `disconnect` profiles. Delays of 0/100/250/500/1000 ms are artificial delivery delays, not GM75 optical measurements. In host mode `disconnect` explicitly resets a partial frame. A physical UART has no inherent unplug notification; stale partial frames time out after one second. Overlength or control-corrupted frames are discarded through the next terminator.

## ESP32-S3 firmware and QEMU

```bash
./scripts/build_firmware.sh
.venv/bin/python scripts/test_qemu.py
```

The first command configures target `esp32s3`, builds the firmware, and merges a 4 MiB flash image. The second starts its own backend on loopback **9000**, launches actual firmware in QEMU, asserts runtime behavior, restarts with the same NVS flash image, and saves full console logs and JSON/CSV metrics under `results/qemu/`. Port 9000 must be free. Existing servers are not silently reused.

Manual QEMU use:

```bash
# Terminal 1
.venv/bin/python simulator/mock_backend.py --port 9000
# Terminal 2
./scripts/run_qemu.sh 2>&1 | tee results/qemu-manual.log
# Terminal 3
.venv/bin/python simulator/scanner_injector.py --tcp 127.0.0.1:5556 --payload TKT:valid-004 --scenario partial --delay-ms 100
```

`run_qemu.sh` preserves `results/qemu-flash.bin` across runs. Do not delete or replace a pending transaction journal to bypass uncertainty. For an isolated fresh demo, supply a **new** `KIOSK_FLASH_IMAGE=/absolute/path/new-demo.bin`. It is copied from the pristine build image only if absent. Do not run two QEMU instances against the same writable image. `KIOSK_UART_PORT` changes the UART1 TCP port; `KIOSK_QEMU` selects an explicit emulator executable. The script prefers the pinned local 9.2.2 binary.

UART0 carries console logs; UART1 carries simulated scanner bytes through QEMU's actual UART peripheral model and the ESP-IDF UART driver. This is not a physical GM75 or GPIO timing model. Keep QEMU's stdin open when using `-serial stdio`; the automated harness does so explicitly. EOF on the console chardev caused missing logs during initial troubleshooting, although the guest was running. Both conventional `-serial` bindings are introspectable with QMP.

An explicit alternative `CONFIG_KIOSK_CONSOLE_INJECTION=y` reads scanner input from UART0 as a firmware-level adapter if a different QEMU build cannot expose UART1. It is not the adapter used for the verified UART1 run. Simulation-only `!retry\n` and `!resolve_printed\n` commands can be sent to the scanner TCP socket. Hardware firmware does not enable these unauthenticated commands.

The guest reaches the host service at **10.0.2.2:9000**, using QEMU's OpenETH model and user NAT (`-nic user,model=open_eth`). This is not Wi-Fi emulation. No USB Host or Bluetooth functionality is used.

## Fault injection and printer previews

```bash
.venv/bin/python simulator/fault_injector.py backend timeout
.venv/bin/python simulator/fault_injector.py backend http500 --remaining 2
.venv/bin/python simulator/fault_injector.py backend unavailable
.venv/bin/python simulator/fault_injector.py backend normal --latency-ms 250
.venv/bin/python simulator/fault_injector.py printer paper_out
.venv/bin/python simulator/fault_injector.py printer busy
.venv/bin/python simulator/fault_injector.py printer incomplete
.venv/bin/python simulator/fault_injector.py printer cutter_failure
.venv/bin/python simulator/fault_injector.py printer disconnect
.venv/bin/python simulator/fault_injector.py printer normal --duration-ms 1000
```

Backend faults also support `lost_commit_response`, `--route commit`, and `--remaining N`. Reset with `backend normal`. `unavailable` models service outage via HTTP 503; the test suite separately exercises real TCP connection refusal as network loss. Host tests do not test an actual Wi-Fi radio.

The backend mounts virtual printer routes for convenient one-process testing. The printer can instead run separately with `.venv/bin/python simulator/virtual_printer.py --port 9001`; point the host `--printer` URL there. The ESC/POS parser captures init, alignment, bold, size, feed and cut commands, raw `.bin` data, formatting metadata `.json`, and readable `.txt` previews. Default output directory is `results/previews/`.

Backend variables: `KIOSK_DB`, `PRINTER_DB`, and `PREVIEW_DIR`. Default seeded tokens are `TKT:valid-000` through `TKT:valid-999`, `TKT:expired`, and arbitrary unknown tokens for invalid-ticket tests. A consumed seed token remains consumed across backend restarts; use a new token or an explicitly separate test database. Reservations never expire automatically.

## API contract

`POST /api/tickets/reserve` accepts `ticket_token`, `device_id`, `operation_id` (32 hex characters), and optional `reservation_id`. `POST /api/tickets/commit` requires the same identity and returned reservation ID. `GET /api/operations/{operation_id}` returns durable operation status; `GET /health` checks SQLite access. Responses include `authorized`, reservation, ticket identity, title/metadata, status, and error code. Identical operations are idempotent; changing identity under an operation ID yields HTTP 409. SQLite `BEGIN IMMEDIATE`, primary keys, and permanent ownership enforce ticket exclusion across concurrent kiosks.

The local test backend and `/__test/faults` controls are unauthenticated and bind to loopback. Deployment needs authenticated kiosk/operator access, TLS with configured trust, ticket provisioning and policy controls. A commit is the kiosk's attestation of confirmed printing; the backend cannot independently prove paper emerged.

## Hardware build and configuration

```bash
./scripts/build_firmware.sh --hardware
source scripts/env.sh
cd firmware
idf.py -B build-hardware -D SDKCONFIG=sdkconfig.hw -D SDKCONFIG_DEFAULTS=sdkconfig.hardware menuconfig
# Configure Wi-Fi, backend URL, unique device ID and GPIOs; rebuild afterwards.
idf.py -B build-hardware -D SDKCONFIG=sdkconfig.hw build
# Only after hardware checks, use your actual serial port:
# idf.py -B build-hardware -D SDKCONFIG=sdkconfig.hw -p /dev/ttyACM0 flash monitor
```

The hardware and QEMU configurations have separate build directories and sdkconfig files. Hardware transport initialization deliberately reports `NotStarted`; it cannot falsely report a physical print. Implement the verified printer transport behind `Printer`, preserving the formatter and controller. See [hardware integration checklist](docs/hardware-integration.md).

The supplied scanner pin labels are interpreted from the **scanner** perspective: scanner RX connects to GPIO17 (ESP TX), scanner TX connects to GPIO18 (ESP RX). All GPIOs and baud rate are configurable under `menuconfig → QR ticket kiosk`. If the original labels instead meant ESP RX/TX, swap those two configuration values after wiring verification. Green/red/buzzer default to GPIO4/5/6. No PCB or driver circuit has been designed in this software project.

## Repository map

- `firmware/components/ticket_controller`: shared state machine and telemetry.
- `qr_scanner`, `backend_client`, `printer`, `transaction_journal`, `platform_hal`, `indicators`: small interfaces, formatters and platform adapters.
- `host_tests/host_main.cpp`: POSIX HTTP, file journal and JSONL native runtime.
- `host_tests/test_integration.py`: asserted end-to-end functional and fault tests.
- `simulator/`: scanner byte injector, FastAPI/SQLite backend, virtual ESC/POS printer, fault controls, and the local graphical QEMU dashboard.
- `scripts/`: prerequisites, installs, builds, host/QEMU tests, launch and benchmarks.
- `docs/`: architecture, hardware checklist, benchmark and verification reports.
- `vendor/`: upstream cJSON v1.7.19 for host; firmware uses ESP-IDF's cJSON component. MIT license retained.

Official references: [ESP-IDF Ubuntu setup](https://docs.espressif.com/projects/esp-idf/en/v5.5.1/esp32s3/get-started/linux-macos-setup.html), [ESP-IDF QEMU guide](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32s3/api-guides/tools/qemu.html), [Espressif QEMU feature matrix](https://github.com/espressif/esp-toolchain-docs/blob/main/qemu/README.md), [ESP32-S3 QEMU instructions](https://github.com/espressif/esp-toolchain-docs/blob/main/qemu/esp32s3/README.md), [official QEMU release](https://github.com/espressif/qemu/releases/tag/esp-develop-9.2.2-20260417).
