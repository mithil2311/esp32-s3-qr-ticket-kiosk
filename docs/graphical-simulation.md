# Live graphical QEMU simulator

Launch from the project root after building the firmware and installing Python dependencies:

```bash
.venv/bin/python simulator/dashboard.py --port 8080
```

Open **http://127.0.0.1:8080** in a browser on the same Ubuntu computer. The dashboard is a local graphical observation/control adapter for the actual ESP32-S3 firmware in Espressif QEMU. Its scanner, controller and printer illustration is rendered with local SVG/CSS; it is not an emulated LCD or an electrical circuit simulation.

The launcher owns a private test backend on port **9000** and scanner UART1 socket on **5556**. These ports must be free: close prior manual demos first. The launcher does not reuse or terminate unrelated services. A new launch creates a separate directory under `results/gui-demo/` containing its SQLite databases, writable QEMU flash/NVS, raw firmware logs and captured printer output. Ctrl+C stops only its owned processes and retains those files.

To resume a retained session rather than creating an isolated new one:

```bash
.venv/bin/python simulator/dashboard.py --session /absolute/path/to/results/gui-demo/SESSION
```

A resumed backend retains ticket usage; choose an unused custom token if its initial auto-selected token was consumed. The **Restart guest** button preserves the current backend and NVS image. Restarting during printing therefore enters `UNCERTAIN`, and never automatically produces another ticket.

## Controls and observations

- **Scan ticket** sends decoded bytes through the real QEMU UART1 character device and ESP-IDF UART driver. Choose valid, invalid, expired, duplicate, partial, corrupted, rapid-repeat or mid-frame-disconnect scenarios. Input delivery delays are artificial; GM75 optics are not simulated. Disconnect closes the input stream mid-frame; it does not claim that a physical UART can detect an unplug event.
- The diagram highlights observed UART, validation/commit and print activity. Firmware state, transaction durations, FreeRTOS queue counts, heap and stack margins come from actual guest telemetry. Indicator colors are derived from state events; very brief events are visually held for readability and are not measurements of physical GPIO pulse width.
- **Fault injection** changes the existing backend/printer models, including HTTP 500, timeout, outage, paper-out, busy, disconnect, incomplete printing and cutter failure. Defaults include a 250 ms artificial backend delay and 1200 ms virtual print duration so transitions are visible. Changes take effect only after **Apply fault settings**.
- The receipt displays the virtual printer's actual decoded ESC/POS job capture. A model completion result does not establish physical printing on a KP307-UB.
- In `RECOVERY`, restore normal fault settings and select **Retry operation**. In `UNCERTAIN`, the **Confirm ticket printed** action requires an explicit operator verification dialog. It commits the same reservation without reprinting. If output cannot be verified, leave the operation quarantined.
- Live activity distinguishes firmware timestamps from host-adapter events. Printed-token metadata and operation IDs are kept as text, not rendered as untrusted HTML.

The graphical server binds only to loopback, rejects cross-origin control requests and requires JSON for mutations. It is a local development tool with unauthenticated simulator controls, not a remotely deployable production operator console. The project has not been published as a hosted web app; the browser must reach the Ubuntu machine running QEMU.

## Executed verification

The full host/API suite passed **37 tests**: the existing 31 functional tests plus six graphical-adapter contract tests. They cover page/assets, telemetry cursor, scanner request validation, fault bounds, operator verification, lifecycle, and cross-origin/control-payload rejection.

Six additional end-to-end checks were executed through the graphical HTTP controls against its actual QEMU guest:

1. Valid scan produces a committed ticket and captured ESC/POS preview.
2. Invalid ticket does not print.
3. Partial UART packets reach the real firmware parser.
4. Paper-out and operator retry preserve the operation.
5. Backend errors fail closed and recover after clearing the fault.
6. Guest restart preserves NVS uncertainty; verified reconciliation does not reprint.

Evidence: [host/API regression output](../results/gui-regression.log), [live runtime checks](../results/gui-runtime-checks.json). Browser automation was unavailable in this environment: browser rendering/layout was not automatically verified, and these results do not claim a screenshot or browser interaction test. Static markup references and JavaScript syntax were checked.

To repeat the live checks while the dashboard is running:

```bash
.venv/bin/python scripts/test_dashboard_runtime.py
```

The script intentionally drives fault scenarios and a restart, then leaves the guest idle with normal models and a successful sample ticket. Do not operate the dashboard concurrently during that scripted check.
