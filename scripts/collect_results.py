#!/usr/bin/env python3
"""Build the human verification reports from executed build/test/benchmark artifacts."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
R=Path(__file__).resolve().parents[1]

def read(p):return (R/p).read_text()
def checks(p):
    suite=ET.parse(R/p).getroot().find('testsuite')
    assert suite is not None
    assert int(suite.get('failures'))==0 and int(suite.get('errors'))==0
    return int(suite.get('tests'))
def digest(p):return hashlib.sha256((R/p).read_bytes()).hexdigest()
def table(j):
    text='| Latency (ms) | Mean | Median | P95 | P99 | Max |\n|---|---:|---:|---:|---:|---:|\n'
    for key,values in j['latencies'].items():
        text+='| '+key+' | '+' | '.join(f'{values[k]:.3f}' for k in ('mean','median','p95','p99','maximum'))+' |\n'
    return text

def main():
    host=checks('results/host-tests.xml');asan=checks('results/asan-tests.xml')
    for p in ['results/firmware-build.log','results/hardware-build.log']:assert 'Project build complete.' in read(p)
    assert 'Build files have been written' in read('results/host-build.log') and (R/'build/kiosk_host').exists()
    b=json.loads(read('results/benchmark/benchmark.json'));q=json.loads(read('results/qemu/results.json'));qs=json.loads(read('results/qemu/benchmark.json'))
    assert all(x['passed'] for x in q['tests']) and len(q['tests'])==8
    assert b['sample_count']==25 and b['successes']==25
    resource=q['resources'];minimum={k:min(row[k] for row in resource) for k in ('controller_stack_hwm_bytes','scanner_stack_hwm_bytes','heap_free_bytes','heap_min_bytes')}
    assert minimum['controller_stack_hwm_bytes']>=4096
    binaries=['build/kiosk_host','firmware/build/qr_ticket_kiosk.bin','firmware/build-hardware/qr_ticket_kiosk.bin','firmware/build/flash_image.bin']
    manifest={'generated_utc':datetime.now(timezone.utc).isoformat(),'host_tests_passed':host,'sanitizer_tests_passed':asan,'qemu_checks_passed':len(q['tests']),'host_benchmark_samples':b['sample_count'],'toolchain':q['toolchain'],'host_gcc':subprocess.check_output(['g++','-dumpfullversion'],text=True).strip(),'artifacts':{p:{'bytes':(R/p).stat().st_size,'sha256':digest(p)} for p in binaries},'qemu_resource_minima':minimum}
    (R/'results/manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    previews=sorted((R/'results/benchmark/previews').glob('*.txt'))
    if previews:(R/'results/sample-ticket.txt').write_text(previews[0].read_text())
    report=f'''# Executed runtime benchmarks

Generated {manifest['generated_utc']}. These results are read from the recorded executions, not estimated scanner/printer specifications.

## Host native baseline

{b['sample_count']} successful transactions; {b['failures']} failed transactions. Success rate {b['success_rate']:.0%}. The process executes the shared C++ controller, real localhost HTTP calls, SQLite FULL persistence, a file journal with fsync, and an 80 ms virtual printer job model. Five samples each use artificial pre-injection delays of 0, 100, 250, 500 and 1000 ms. Every payload is split with a measured 10 ms inter-chunk wait.

{table(b)}
Observed throughput: **{b['observed_transactions_per_minute']:.2f} transactions/minute** across {b['wall_seconds']:.3f} seconds, including artificial pre-injection delays, partial delivery and harness polling. This is not a saturation test or a hardware throughput claim. P95/P99 use nearest rank; 25 samples provide limited tail resolution.

`input_ms` is first-byte/source-timestamp to completed-frame receipt. `total_ms` starts at completed-frame receipt and ends at commit/failure. `end_to_end_ms` includes both. Pre-injection artificial sleeps appear in observed throughput but are deliberately not called application processing latency. `validation_ms` includes reserve/reconciliation calls and retry waits; `retry_ms` records timer backoff separately. `generation_ms` measures formatting; `printing_ms` measures the simulator completion interval. Fields are not all additive.

Raw samples and resource observations: [JSON](../results/benchmark/benchmark.json), [CSV](../results/benchmark/benchmark.csv).

## Actual ESP32-S3 firmware in QEMU

{q['toolchain']}. External UART1 TCP, ESP-IDF UART driver, OpenETH NAT, FreeRTOS and NVS are exercised. {len(q['tests'])} assertions/scenarios pass, including a restart with persistent emulated flash during printing.

{table(qs)}
The QEMU telemetry contains **{qs['sample_count']} completed attempt metrics**, including intentional faults: {qs['successes']} success and {qs['failures']} failure/uncertainty rows. These fractions describe the selected fault workload, not an inferred reliability rate. Manual retry/reconciliation completion and interrupted transactions are visible in state logs, and do not create a second initial-attempt metric. The active-transaction equivalent is {qs['active_transaction_equivalent_per_minute']:.2f}/minute; it excludes idle/reboot time and is not observed sustained throughput.

Minimum sampled controller stack high-water mark: **{minimum['controller_stack_hwm_bytes']} bytes**; scanner: **{minimum['scanner_stack_hwm_bytes']} bytes**. Lowest reported free-heap watermark: **{minimum['heap_min_bytes']} bytes**. The main task stack was increased from 8 KiB to 16 KiB after a preliminary run exposed only 152 bytes of margin. Final samples show the improved margin. Queue depth, overflow, failure count and heap observations are retained in [QEMU results](../results/qemu/results.json).

Raw QEMU [CSV](../results/qemu/benchmark.csv), [statistics](../results/qemu/benchmark.json), [runtime console](../results/qemu/uart1-runtime.log), and [NVS restart console](../results/qemu/nvs-power-recovery.log).

These numbers measure emulator scheduling plus mocked peripherals and host service behavior. They do not measure ESP32 hardware CPU performance, real GM75 optical decode time/FPS, Wi-Fi behavior, USB/Bluetooth transfers, physical paper emergence or cutter reliability.
'''
    (R/'docs/benchmark-report.md').write_text(report)
    verification=f'''# Final verification report

Executed on Ubuntu 26.04.1 x86_64; generated {manifest['generated_utc']}. GCC {manifest['host_gcc']}, CMake 3.30.2, Ninja 1.12.1, Python 3.14.4; {q['toolchain']}.

| Milestone | Executed evidence | Result |
|---|---|---|
| 1: inspect and architecture | New project created after workspace/toolchain inspection; architecture and durable protocol documented | Complete |
| 2: shared controller and host | CMake build; actual C++ executable invoked by integration tests | Pass |
| 3: backend and printer | FastAPI, SQLite persistence, concurrent reservation/idempotency and ESC/POS decoding exercised by real HTTP | Pass |
| 4: ESP-IDF adapters | ESP32-S3 emulation and hardware configurations compiled with ESP-IDF | Both pass |
| 5: QEMU | Actual Xtensa firmware; {len(q['tests'])} runtime scenarios and persistent-NVS restart | Pass |
| 6: faults and measurements | {host} host tests; {asan} ASan/UBSan tests; 25 successful native benchmark transactions | Pass |
| 7: verification | Fresh logs, JUnit, JSON/CSV, artifact hashes and reports collected | Complete |

## Acceptance criteria

- Native simulator builds and runs: verified by [build log](../results/host-build.log) and [{host} passing tests](../results/host-tests.xml).
- Functional and fault assertions exit successfully: [{host} host tests](../results/host-tests.log), [{asan} sanitizer tests](../results/asan-tests.log). The runner uses nonzero exit on assertion failures.
- Firmware builds for ESP32-S3: [QEMU configuration](../results/firmware-build.log), [hardware configuration](../results/hardware-build.log). Hardware compilation is not hardware validation.
- QEMU execution demonstrated: [{len(q['tests'])} checks](../results/qemu-tests.log), full console logs and JSON telemetry retained.
- Invalid/expired/duplicate tickets do not print: tested against printer job counts; malformed/corrupt/overlength scanner frames are dropped.
- Backend errors never authorize implicitly: timeout, HTTP 500, refused connection, retry exhaustion, and lost commit-response paths tested.
- Restart recovery: CREATED, RESERVED, PRINTING, CONFIRMED, COMMITTED, and server-commit-before-local-journal-write cases exercised. A journal storage error fails closed.
- Uncertain printing never triggers automatic reprinting: restart tests and explicit operator reconciliation assert unchanged job counts.
- Every state transition is logged with monotonic timestamps, operation ID and reason; benchmark outputs derive from actual executions.

The requested eighteen scenarios are all covered: valid, invalid, expired, duplicate, rapid scans, backend timeout, HTTP 500, network loss, paper-out, busy, cutter failure, restart during printing, restart after reservation, duplicate backend requests, partial UART, malformed QR, overflow, and uncertain-state recovery. Additional tests cover concurrent competing reservations, corrupted journal, scanner disconnect/stale/overlength frames, journal-write failures, external input timestamps, restart around commit, and retry telemetry.

## QEMU checks

'''
    verification+='\n'.join('- '+x['test']+': PASS.' for x in q['tests'])+'\n'
    verification+='''
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
'''
    (R/'docs/verification.md').write_text(verification)
    print(json.dumps(manifest,indent=2))
if __name__=='__main__':main()
