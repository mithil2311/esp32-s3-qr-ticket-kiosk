#!/usr/bin/env python3
"""Loopback graphical control/observation adapter for the actual QEMU firmware.

All ticket decisions remain in the shared firmware controller. This process owns
only an isolated test backend, UART byte injection, telemetry and visualization.
"""
import argparse
from collections import deque
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "simulator/dashboard"


class Runtime:
    def __init__(self, session=None, backend_port=9000, uart_port=5556):
        self.directory = Path(session or ROOT / "results/gui-demo" / time.strftime("%Y%m%d-%H%M%S")).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.backend_port, self.uart_port = backend_port, uart_port
        self.lock, self.input_lock = threading.RLock(), threading.Lock()
        self.events = deque(maxlen=400)
        self.metrics = deque(maxlen=100)
        self.sequence, self.token_number = 0, 1
        self.state, self.operation, self.reason = "BOOT", "", ""
        self.last_token, self.last_job = "", None
        self.resources, self.backend = {}, None
        self.guest, self.reader = None, None
        self.completed, self.rejected, self.uncertain = set(), set(), set()
        self.pending_inputs, self.restarts, self.scans = 0, 0, 0
        self.printer_fault, self.backend_fault = "normal", "normal"
        self.printer_duration, self.backend_latency = 1200, 250
        self.client = httpx.Client(base_url=f"http://127.0.0.1:{backend_port}", timeout=2, trust_env=False)
        self.backend_log = None
        self.stopping = threading.Event()

    def emit(self, kind, data):
        with self.lock:
            self.sequence += 1
            self.events.append({"id": self.sequence, "event": kind, "data": data, "host_time": time.time()})

    def start(self):
        # Never reuse an unknown backend or another guest's UART socket.
        for port in (self.backend_port, self.uart_port):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
        self.backend_log = (self.directory / "backend.log").open("a")
        env = dict(os.environ, KIOSK_DB=str(self.directory / "tickets.sqlite"),
                   PRINTER_DB=str(self.directory / "printer.sqlite"), PREVIEW_DIR=str(self.directory / "previews"))
        self.backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "simulator.mock_backend:app",
            "--host", "127.0.0.1", "--port", str(self.backend_port)], cwd=ROOT, env=env,
            stdout=self.backend_log, stderr=self.backend_log)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.backend.poll() is not None:
                raise RuntimeError("Test backend failed; inspect " + str(self.directory / "backend.log"))
            try:
                if self.client.get("/health").status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(.05)
        else:
            raise RuntimeError("Backend startup timeout")
        self.set_faults("normal", "normal", 1200, 250)
        self._start_guest()

    def _start_guest(self):
        self.guest = subprocess.Popen([str(ROOT / "scripts/run_qemu.sh")], cwd=ROOT,
            env=dict(os.environ, KIOSK_FLASH_IMAGE=str(self.directory / "flash.bin"), KIOSK_UART_PORT=str(self.uart_port)),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1)
        self.reader = threading.Thread(target=self._read_guest, args=(self.guest,), daemon=True)
        self.reader.start()
        (self.directory / "pids.json").write_text(json.dumps({"dashboard": os.getpid(), "backend": self.backend.pid, "qemu": self.guest.pid}))

    def _read_guest(self, guest):
        with (self.directory / "firmware.log").open("a") as log:
            for line in guest.stdout:
                log.write(line)
                log.flush()
                start = line.find('{"event":')
                if start < 0:
                    if "eth ip:" in line:
                        self.emit("network", {"message": line.strip()})
                    continue
                try:
                    item = json.loads(line[start:])
                    data, kind = item["data"], item["event"]
                except (ValueError, KeyError):
                    continue
                with self.lock:
                    if kind == "state":
                        self.state, self.operation, self.reason = data["state"], data["operation_id"], data.get("reason", "")
                        if self.state == "SUCCESS": self.completed.add(self.operation)
                        if self.state == "REJECTED": self.rejected.add(self.operation)
                        if self.state == "UNCERTAIN": self.uncertain.add(self.operation)
                    elif kind == "resources": self.resources = data
                    elif kind == "metric": self.metrics.append(data)
                    self.emit(kind, data)
            if not self.stopping.is_set() and guest is self.guest:
                self.emit("adapter", {"message": "QEMU exited", "exit_code": guest.poll()})

    def send(self, payload):
        if not self.guest or self.guest.poll() is not None:
            raise RuntimeError("QEMU is not running")
        with socket.create_connection(("127.0.0.1", self.uart_port), timeout=2) as wire:
            wire.sendall(payload)

    def scan(self, scenario, delay_ms, token=""):
        if not token:
            if scenario == "invalid": token = "TKT:unknown"
            elif scenario == "expired": token = "TKT:expired"
            elif scenario == "duplicate":
                token = self.last_token
                if not token: raise ValueError("Scan a ticket before repeating it")
            else:
                with self.lock:
                    if self.token_number > 999: raise ValueError("Demo seed tickets exhausted; choose a fresh session")
                    token = f"TKT:valid-{self.token_number:03}"
                    self.token_number += 1
        if token.startswith("!") or any(ord(c) < 32 or ord(c) > 126 for c in token):
            raise ValueError("Use a printable ticket payload without control commands")
        with self.lock:
            self.pending_inputs += 1
            self.last_token = token
            self.scans += 1
        self.emit("input", {"token": token, "scenario": scenario, "delay_ms": delay_ms, "source": "UART1 TCP injector"})
        def inject():
            try:
                with self.input_lock:
                    time.sleep(delay_ms / 1000)
                    packet = (token + "\r\n").encode("ascii")
                    if scenario == "partial":
                        self.send(packet[:5]); time.sleep(.25); self.send(packet[5:])
                    elif scenario == "corrupt": self.send(packet[:4] + b"\x00\xff" + packet[4:])
                    elif scenario == "disconnect": self.send(packet[:6])
                    elif scenario == "rapid": self.send(packet * 20)
                    else: self.send(packet)
                    self.emit("injected", {"token": token, "scenario": scenario})
            except Exception as error:
                self.emit("adapter_error", {"message": str(error)})
            finally:
                with self.lock: self.pending_inputs -= 1
        threading.Thread(target=inject, daemon=True).start()
        return {"token": token, "scenario": scenario, "delay_ms": delay_ms}

    def set_faults(self, printer, backend, duration_ms, latency_ms):
        self.client.post("/printer/__test/faults", json={"mode": printer, "duration_ms": duration_ms}).raise_for_status()
        self.client.post("/__test/faults", json={"mode": backend, "latency_ms": latency_ms}).raise_for_status()
        with self.lock:
            self.printer_fault, self.backend_fault = printer, backend
            self.printer_duration, self.backend_latency = duration_ms, latency_ms
        self.emit("fault", {"printer": printer, "backend": backend, "printing_ms": duration_ms, "latency_ms": latency_ms})

    def operator(self, action):
        with self.lock:
            if action == "retry" and self.state != "RECOVERY": raise ValueError("Retry is available only in RECOVERY")
            if action == "resolve_printed" and self.state != "UNCERTAIN": raise ValueError("No uncertain print to reconcile")
        self.send(("!" + action + "\n").encode())
        self.emit("operator", {"action": action})

    def restart(self):
        with self.input_lock:
            self._stop_guest()
            with self.lock:
                self.restarts += 1
                self.state = "BOOT"
            self.emit("adapter", {"message": "Restarting guest with the same NVS flash; backend and reservations retained"})
            self._start_guest()

    def snapshot(self, after=0):
        # Printer preview is captured from real ESC/POS jobs, not fabricated UI text.
        try:
            stats = self.client.get("/printer/stats").json()
            if stats.get("operations"):
                op = stats["operations"][-1]
                response = self.client.get("/printer/jobs/" + op)
                if response.status_code == 200: self.last_job = response.json()
        except (httpx.TransportError, ValueError):
            pass
        with self.lock:
            snapshot = {"state": self.state, "operation_id": self.operation, "reason": self.reason,
                "qemu_running": bool(self.guest and self.guest.poll() is None),
                "backend_running": bool(self.backend and self.backend.poll() is None),
                "successes": len(self.completed), "rejected": len(self.rejected),
                "uncertain_count": len(self.uncertain), "scans": self.scans, "restarts": self.restarts,
                "pending_inputs": self.pending_inputs, "last_token": self.last_token,
                "resources": self.resources, "metrics": list(self.metrics)[-20:], "printer_job": self.last_job,
                "events": [e for e in self.events if e["id"] > after], "cursor": self.sequence,
                "faults": {"printer": self.printer_fault, "backend": self.backend_fault,
                           "duration_ms": self.printer_duration, "latency_ms": self.backend_latency},
                "session_directory": str(self.directory), "domain": "qemu_xtensa_firmware"}
            return snapshot

    def _stop_guest(self):
        guest, reader = self.guest, self.reader
        if guest:
            if guest.poll() is None: guest.terminate()
            try: guest.wait(timeout=5)
            except subprocess.TimeoutExpired: guest.kill(); guest.wait()
            if reader: reader.join(timeout=2)
            guest.stdin.close(); guest.stdout.close()

    def close(self):
        self.stopping.set()
        self._stop_guest()
        if self.backend:
            if self.backend.poll() is None: self.backend.terminate()
            try: self.backend.wait(timeout=5)
            except subprocess.TimeoutExpired: self.backend.kill(); self.backend.wait()
        self.client.close()
        if self.backend_log: self.backend_log.close()


class ScanRequest(BaseModel):
    scenario: Literal["valid", "invalid", "expired", "duplicate", "partial", "corrupt", "disconnect", "rapid"] = "valid"
    delay_ms: Literal[0, 100, 250, 500, 1000] = 250
    token: str = Field(default="", max_length=96)


class FaultRequest(BaseModel):
    printer: Literal["normal", "paper_out", "busy", "disconnect", "incomplete", "cutter_failure"] = "normal"
    backend: Literal["normal", "http500", "timeout", "unavailable"] = "normal"
    duration_ms: int = Field(default=1200, ge=80, le=8000)
    latency_ms: int = Field(default=250, ge=0, le=1000)


class OperatorRequest(BaseModel):
    action: Literal["retry", "resolve_printed", "restart"]
    verified_printed: bool = False


def create_app(runtime):
    @asynccontextmanager
    async def lifespan(app):
        try:
            runtime.start()
            yield
        finally:
            runtime.close()
    app = FastAPI(title="Kiosk Lab - live QEMU dashboard", lifespan=lifespan)

    @app.middleware("http")
    async def local_controls(request: Request, call_next):
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Cross-origin control is not allowed"}, status_code=403)
            if "application/json" not in request.headers.get("content-type", ""):
                return JSONResponse({"detail": "JSON controls required"}, status_code=415)
        return await call_next(request)

    @app.get("/")
    def home(): return FileResponse(ASSETS / "index.html")

    @app.get("/api/ui/state")
    def get_state(after: int = 0): return runtime.snapshot(after)

    @app.post("/api/ui/scan", status_code=202)
    def scan(body: ScanRequest):
        try: return runtime.scan(body.scenario, body.delay_ms, body.token)
        except ValueError as error: raise HTTPException(409, str(error)) from error

    @app.post("/api/ui/faults")
    def faults(body: FaultRequest):
        try:
            runtime.set_faults(body.printer, body.backend, body.duration_ms, body.latency_ms)
            return {"ok": True}
        except httpx.HTTPError as error: raise HTTPException(503, "Fault adapter unavailable") from error

    @app.post("/api/ui/operator")
    def operator(body: OperatorRequest):
        if body.action == "resolve_printed" and not body.verified_printed:
            raise HTTPException(409, "Operator verification is required")
        try:
            if body.action == "restart": runtime.restart()
            else: runtime.operator(body.action)
            return {"ok": True}
        except (ValueError, RuntimeError, OSError) as error: raise HTTPException(409, str(error)) from error

    app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")
    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--session", help="Resume this directory's backend and NVS flash; defaults to an isolated new demo")
    args = parser.parse_args()
    print(f"Graphical QEMU simulator: http://127.0.0.1:{args.port}", flush=True)
    uvicorn.run(create_app(Runtime(args.session)), host="127.0.0.1", port=args.port)

if __name__ == "__main__": main()
