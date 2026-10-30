# Executed runtime benchmarks

Generated 2026-10-30T12:39:38.420764+00:00. These results are read from the recorded executions, not estimated scanner/printer specifications.

## Host native baseline

25 successful transactions; 0 failed transactions. Success rate 100%. The process executes the shared C++ controller, real localhost HTTP calls, SQLite FULL persistence, a file journal with fsync, and an 80 ms virtual printer job model. Five samples each use artificial pre-injection delays of 0, 100, 250, 500 and 1000 ms. Every payload is split with a measured 10 ms inter-chunk wait.

| Latency (ms) | Mean | Median | P95 | P99 | Max |
|---|---:|---:|---:|---:|---:|
| input_ms | 10.455 | 10.451 | 10.680 | 10.727 | 10.727 |
| validation_ms | 2.791 | 2.005 | 2.518 | 23.068 | 23.068 |
| retry_ms | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| generation_ms | 0.001 | 0.001 | 0.003 | 0.003 | 0.003 |
| printing_ms | 90.959 | 89.552 | 99.034 | 99.127 | 99.127 |
| total_ms | 105.174 | 102.855 | 113.025 | 126.282 | 126.282 |
| end_to_end_ms | 115.629 | 113.404 | 123.501 | 136.816 | 136.816 |

Observed throughput: **119.92 transactions/minute** across 12.508 seconds, including artificial pre-injection delays, partial delivery and harness polling. This is not a saturation test or a hardware throughput claim. P95/P99 use nearest rank; 25 samples provide limited tail resolution.

`input_ms` is first-byte/source-timestamp to completed-frame receipt. `total_ms` starts at completed-frame receipt and ends at commit/failure. `end_to_end_ms` includes both. Pre-injection artificial sleeps appear in observed throughput but are deliberately not called application processing latency. `validation_ms` includes reserve/reconciliation calls and retry waits; `retry_ms` records timer backoff separately. `generation_ms` measures formatting; `printing_ms` measures the simulator completion interval. Fields are not all additive.

Raw samples and resource observations: [JSON](../results/benchmark/benchmark.json), [CSV](../results/benchmark/benchmark.csv).

## Actual ESP32-S3 firmware in QEMU

ESP-IDF v5.5.1; Espressif QEMU 9.2.2 esp_develop_9.2.2_20260417. External UART1 TCP, ESP-IDF UART driver, OpenETH NAT, FreeRTOS and NVS are exercised. 8 assertions/scenarios pass, including a restart with persistent emulated flash during printing.

| Latency (ms) | Mean | Median | P95 | P99 | Max |
|---|---:|---:|---:|---:|---:|
| input_ms | 17.002 | 0.000 | 102.011 | 102.011 | 102.011 |
| validation_ms | 193.316 | 15.532 | 767.019 | 767.019 | 767.019 |
| retry_ms | 168.294 | 0.000 | 709.554 | 709.554 | 709.554 |
| generation_ms | 0.097 | 0.064 | 0.310 | 0.310 | 0.310 |
| printing_ms | 61.817 | 89.552 | 93.886 | 93.886 | 93.886 |
| total_ms | 283.266 | 135.966 | 902.487 | 902.487 | 902.487 |
| end_to_end_ms | 300.286 | 186.984 | 902.535 | 902.535 | 902.535 |

The QEMU telemetry contains **6 completed attempt metrics**, including intentional faults: 3 success and 3 failure/uncertainty rows. These fractions describe the selected fault workload, not an inferred reliability rate. Manual retry/reconciliation completion and interrupted transactions are visible in state logs, and do not create a second initial-attempt metric. The active-transaction equivalent is 211.81/minute; it excludes idle/reboot time and is not observed sustained throughput.

Minimum sampled controller stack high-water mark: **8344 bytes**; scanner: **2860 bytes**. Lowest reported free-heap watermark: **312348 bytes**. The main task stack was increased from 8 KiB to 16 KiB after a preliminary run exposed only 152 bytes of margin. Final samples show the improved margin. Queue depth, overflow, failure count and heap observations are retained in [QEMU results](../results/qemu/results.json).

Raw QEMU [CSV](../results/qemu/benchmark.csv), [statistics](../results/qemu/benchmark.json), [runtime console](../results/qemu/uart1-runtime.log), and [NVS restart console](../results/qemu/nvs-power-recovery.log).

These numbers measure emulator scheduling plus mocked peripherals and host service behavior. They do not measure ESP32 hardware CPU performance, real GM75 optical decode time/FPS, Wi-Fi behavior, USB/Bluetooth transfers, physical paper emergence or cutter reliability.
