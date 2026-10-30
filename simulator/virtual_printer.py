"""Virtual ESC/POS job completion model. Confirmation proves only simulator completion."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/printer")
lock = threading.RLock()
faults = {"mode": "normal", "duration_ms": 80}
MODES = {"normal", "paper_out", "busy", "disconnect", "incomplete", "cutter_failure"}


@contextmanager
def db():
    p = os.environ.get("PRINTER_DB", "virtual_printer.sqlite")
    c = sqlite3.connect(p, timeout=5)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=FULL")
    c.execute("CREATE TABLE IF NOT EXISTS jobs (operation TEXT PRIMARY KEY, hex TEXT NOT NULL, preview TEXT NOT NULL, commands TEXT NOT NULL, done REAL NOT NULL, failure TEXT NOT NULL)")
    try:
        with c:
            yield c
    finally:
        c.close()


def decode_escpos(data: bytes):
    text, commands, i = [], [], 0
    while i < len(data):
        c = data[i]
        if c == 27:
            if i + 1 >= len(data):
                raise ValueError("truncated ESC")
            op = data[i + 1]
            if op == 64:
                commands.append({"init": True}); i += 2; continue
            if i + 2 >= len(data):
                raise ValueError("truncated ESC parameter")
            n = data[i + 2]
            if op == 97: commands.append({"align": n})
            elif op == 69: commands.append({"bold": bool(n)})
            elif op == 100: commands.append({"feed": n}); text.append("\n" * n)
            else: raise ValueError(f"unsupported ESC {op}")
            i += 3; continue
        if c == 29:
            if i + 2 >= len(data): raise ValueError("truncated GS")
            op, n = data[i + 1:i + 3]
            if op == 33: commands.append({"font_size": n})
            elif op == 86: commands.append({"cut": n})
            else: raise ValueError(f"unsupported GS {op}")
            i += 3; continue
        if c not in (10, 13) and not 32 <= c < 127:
            raise ValueError("unsupported text byte")
        text.append(chr(c)); i += 1
    if not any("cut" in x for x in commands): raise ValueError("no cut command")
    return "".join(text), commands


class Job(BaseModel):
    operation_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    escpos_hex: str = Field(min_length=2, max_length=8192, pattern=r"^[a-f0-9]+$")


class PrinterFault(BaseModel):
    mode: str = "normal"
    duration_ms: int = Field(default=80, ge=0, le=20000)


@router.post("/__test/faults")
def set_faults(f: PrinterFault):
    if f.mode not in MODES: raise HTTPException(422, "invalid fault")
    with lock: faults.update(f.model_dump())
    return dict(faults)


def outcome(row):
    if time.monotonic() < row["done"]: return "pending"
    return "uncertain" if row["failure"] else "confirmed"


@router.post("/jobs")
def start_job(j: Job):
    with lock, db() as c:
        row = c.execute("SELECT * FROM jobs WHERE operation=?", (j.operation_id,)).fetchone()
        if row:
            if row["hex"] != j.escpos_hex: raise HTTPException(409, "operation payload changed")
            return {"operation_id": j.operation_id, "outcome": outcome(row)}
        mode, duration = faults["mode"], faults["duration_ms"]
        if mode == "disconnect": raise HTTPException(503, "printer disconnected")
        if mode in ("paper_out", "busy"):
            return {"operation_id": j.operation_id, "outcome": "not_started", "error_code": mode}
        try: preview, commands = decode_escpos(bytes.fromhex(j.escpos_hex))
        except ValueError as e: raise HTTPException(422, str(e)) from e
        failure = mode if mode in ("incomplete", "cutter_failure") else ""
        if mode == "incomplete": preview = preview[:len(preview)//2]
        c.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)", (j.operation_id, j.escpos_hex, preview, json.dumps(commands), time.monotonic()+duration/1000, failure))
        target = Path(os.environ.get("PREVIEW_DIR", "results/previews"))
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{j.operation_id}.txt").write_text(preview)
        (target / f"{j.operation_id}.bin").write_bytes(bytes.fromhex(j.escpos_hex))
        (target / f"{j.operation_id}.json").write_text(json.dumps({"commands": commands, "fault": failure}, indent=2))
        return {"operation_id": j.operation_id, "outcome": "pending"}


@router.get("/jobs/{operation_id}")
def job_status(operation_id: str):
    with lock, db() as c:
        row = c.execute("SELECT * FROM jobs WHERE operation=?", (operation_id,)).fetchone()
        if not row: raise HTTPException(404, "unknown job")
        return {"operation_id": operation_id, "outcome": outcome(row), "preview": row["preview"], "error_code": row["failure"]}


@router.get("/stats")
def stats():
    with lock, db() as c:
        rows = c.execute("SELECT * FROM jobs").fetchall()
        return {"jobs": len(rows), "operations": [r["operation"] for r in rows], "confirmed": sum(outcome(r)=="confirmed" for r in rows)}

app = FastAPI(title="Virtual ESC/POS printer (simulation only)")
app.include_router(router)
if __name__ == "__main__":
    import uvicorn
    p = argparse.ArgumentParser(); p.add_argument("--port", type=int, default=9001)
    uvicorn.run(app, host="127.0.0.1", port=p.parse_args().port)
