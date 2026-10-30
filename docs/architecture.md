# Architecture and safety contract

Milestone 1 inspection: Ubuntu 26.04.1 x86_64, GCC and Python 3.14 present. No pre-existing kiosk source or installed ESP-IDF/QEMU/CMake/Ninja found. This is a new firmware/software project; no PCB layout or circuit design is performed.

The C++17 controller has no ESP-IDF dependencies. Host and ESP adapters implement monotonic clock, bounded HTTP calls, durable journal, printer transport, and indicators. A bounded scanner parser/ring buffers eight 96-byte frames; the firmware scanner task feeds a FreeRTOS queue and the single controller task owns all business state. Every transition is a JSON log with a monotonic timestamp. Adapter calls are bounded; retry waiting is timer driven, not a busy loop.

A ticket is a newline/CR-delimited ASCII `TKT:<1..64 letters/digits/_/->`. This framing is an integration assumption requiring GM75 configuration verification. Binary/control corruption, overlength frames, and frame timeouts discard the entire frame. Optical decoding is inside the scanner. Artificial injection delays are not scanner benchmarks.

## Durable protocol

1. Persist CREATED with a random 128-bit operation ID and token **before** reserve.
2. Reserve atomically in SQLite; one operation owns one ticket. Repeated identical requests return the same reservation. Changing identity under an operation ID is rejected.
3. Persist RESERVED. On restart reconcile with the backend using the same operation ID.
4. Persist PRINTING **before** invoking any printer transport.
5. Only a positive, job-specific completion result from a simulator or operator can produce CONFIRMED. Sending bytes never confirms physical printing.
6. Persist CONFIRMED before commit. Commit is idempotent. A timeout retries commit and never prints again.
7. Persist COMMITTED before SUCCESS. The backend keeps permanent operation and ticket history. One unresolved local transaction blocks new scans.

A crash with CREATED retries/reconciles reserve. RESERVED can perform the first print after server reconciliation; PRINTING/UNCERTAIN blocks for operator investigation. CONFIRMED only reconciles/commits. A corrupt journal fails closed and is never silently erased. Host atomic rename + file and directory fsync and ESP NVS blob commit provide the respective storage barriers. Host execution holds a process lock. Unique device IDs must be provisioned, and only one physical controller may own a journal.

## Error policy

| Condition | State and action |
|---|---|
| Unknown, expired, used or reserved-by-other token | REJECTED -> IDLE, no print |
| Malformed/corrupt scanner frame | Drop frame; count failure, no authorization |
| Network/HTTP 5xx/protocol failure | RETRY with 100/200/400 ms backoff; after four attempts RECOVERY, keep operation |
| Definitively no printer bytes accepted (paper out/busy) | Persist RESERVED, RECOVERY; explicit `retry` may resume |
| Disconnect, timeout, partial print, cutter failure | UNCERTAIN, preserve reservation, never automatic print |
| Journal failure | RECOVERY locked until restart and investigation; no further side effects |
| Restart with PRINTING | Persist UNCERTAIN; operator reconciliation required |
| Queue full | Drop newest, count overflow; never overwrite accepted frame |
| Operator verifies ticket printed | `resolve_printed` persists CONFIRMED and commits same operation |

An operator who cannot establish printing must leave the operation quarantined. No automatic reservation expiry or release is provided: releasing an uncertain print could permit duplicate admission. Authentication, authorization and audit retention for a production operator console/backend remain deployment work; simulator control endpoints bind to loopback and are not production APIs.

## Execution domains

Host: real native C++ executable + loopback HTTP FastAPI/SQLite + virtual printer. QEMU: actual Xtensa firmware, FreeRTOS, UART/NVS, with explicit network and printer adapters. Hardware: real UART scanner/GPIO/Wi-Fi adapters; USB Host and Bluetooth printer transports deliberately unavailable until verified. The ESC/POS builder is independent of all transports. QEMU latency is emulator runtime, never ESP32 CPU performance.
