"""Local-only FastAPI/SQLite reservation server. Test controls are deliberately unauthenticated."""
import argparse
import asyncio
from contextlib import asynccontextmanager, contextmanager
import os
import sqlite3
import time
import uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
try:
    from .virtual_printer import router
except ImportError:
    from virtual_printer import router

faults = {"mode": "normal", "latency_ms": 0, "remaining": -1, "route": "all"}


@contextmanager
def db():
    c = sqlite3.connect(os.environ.get("KIOSK_DB", "tickets.sqlite"), timeout=5)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=FULL")
    try:
        with c:
            yield c
    finally:
        c.close()


def initialize():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS tickets (token TEXT PRIMARY KEY,title TEXT NOT NULL,expires REAL NOT NULL,owner TEXT,used INTEGER NOT NULL DEFAULT 0)")
        c.execute("CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY,token TEXT NOT NULL,device TEXT NOT NULL,reservation TEXT NOT NULL,status TEXT NOT NULL,error TEXT NOT NULL,title TEXT NOT NULL)")
        c.executemany("INSERT OR IGNORE INTO tickets(token,title,expires) VALUES (?,?,?)", [(f"TKT:valid-{i:03}", "Museum entry", time.time()+86400*365) for i in range(1000)])
        c.execute("INSERT OR IGNORE INTO tickets(token,title,expires) VALUES ('TKT:expired','Expired entry',1)")


@asynccontextmanager
async def lifespan(app):
    initialize()
    yield

app = FastAPI(title="QR kiosk local test backend", lifespan=lifespan)
app.include_router(router)


@app.middleware("http")
async def fault_middleware(request: Request, call_next):
    mode, latency = "normal", 0
    path = request.url.path
    if path.startswith("/api/") and faults["remaining"] != 0 and (faults["route"]=="all" or faults["route"] in path):
        mode, latency = faults["mode"], faults["latency_ms"]
        if faults["remaining"] > 0: faults["remaining"] -= 1
    if latency: await asyncio.sleep(latency/1000)
    if mode == "timeout": await asyncio.sleep(0.6)
    if mode == "http500": return JSONResponse({"error_code": "INJECTED_500"}, status_code=500)
    if mode == "unavailable": return JSONResponse({"error_code": "NETWORK_DISCONNECTED"}, status_code=503)
    response = await call_next(request)
    if mode == "lost_commit_response" and path.endswith("/commit"): await asyncio.sleep(0.6)
    return response


class Identity(BaseModel):
    ticket_token: str = Field(pattern=r"^TKT:[A-Za-z0-9_-]{1,64}$")
    device_id: str = Field(min_length=1, max_length=48, pattern=r"^[A-Za-z0-9_-]+$")
    operation_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    reservation_id: str = Field(default="", max_length=64)


class Fault(BaseModel):
    mode: str = "normal"
    latency_ms: int = Field(default=0, ge=0, le=10000)
    remaining: int = Field(default=-1, ge=-1, le=1000)
    route: str = "all"


@app.post("/__test/faults")
async def set_faults(f: Fault):
    if f.mode not in {"normal", "timeout", "http500", "unavailable", "lost_commit_response"}: raise HTTPException(422, "unknown fault")
    faults.update(f.model_dump()); return dict(faults)


def response(row):
    return {"operation_id": row["id"], "device_id": row["device"], "ticket_token": row["token"], "authorized": row["status"] in ("reserved", "committed"), "reservation_id": row["reservation"], "status": row["status"], "title": row["title"], "metadata": {"title": row["title"]}, "error_code": row["error"]}


def match(row, i):
    if row["token"]!=i.ticket_token or row["device"]!=i.device_id: raise HTTPException(409, "operation identity mismatch")


@app.post("/api/tickets/reserve")
def reserve(i: Identity):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM operations WHERE id=?", (i.operation_id,)).fetchone()
        if row:
            match(row,i); return response(row)
        ticket = c.execute("SELECT * FROM tickets WHERE token=?",(i.ticket_token,)).fetchone()
        error = ""
        if not ticket: error="INVALID_TICKET"
        elif ticket["used"]: error="ALREADY_USED"
        elif ticket["expires"] < time.time(): error="EXPIRED_TICKET"
        elif ticket["owner"]: error="ALREADY_RESERVED"
        reservation = uuid.uuid4().hex if not error else ""
        c.execute("INSERT INTO operations VALUES (?,?,?,?,?,?,?)", (i.operation_id,i.ticket_token,i.device_id,reservation,"denied" if error else "reserved",error,ticket["title"] if ticket else ""))
        if not error: c.execute("UPDATE tickets SET owner=? WHERE token=?",(i.operation_id,i.ticket_token))
        return response(c.execute("SELECT * FROM operations WHERE id=?",(i.operation_id,)).fetchone())


@app.post("/api/tickets/commit")
def commit(i: Identity):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM operations WHERE id=?",(i.operation_id,)).fetchone()
        if not row: raise HTTPException(404,"unknown operation")
        match(row,i)
        if row["status"] not in ("reserved","committed") or not i.reservation_id or row["reservation"]!=i.reservation_id: raise HTTPException(409,"invalid reservation")
        c.execute("UPDATE operations SET status='committed' WHERE id=?",(i.operation_id,))
        c.execute("UPDATE tickets SET used=1 WHERE token=? AND owner=?",(i.ticket_token,i.operation_id))
        return response(c.execute("SELECT * FROM operations WHERE id=?",(i.operation_id,)).fetchone())


@app.get("/api/operations/{operation_id}")
def operation(operation_id: str):
    with db() as c:
        row=c.execute("SELECT * FROM operations WHERE id=?",(operation_id,)).fetchone()
        if not row: raise HTTPException(404,"unknown operation")
        return response(row)


@app.get("/health")
def health():
    with db() as c: c.execute("SELECT 1")
    return {"status":"ok","mode":"local_test_only"}

if __name__ == "__main__":
    import uvicorn
    p=argparse.ArgumentParser();p.add_argument("--port",type=int,default=9000)
    uvicorn.run(app,host="127.0.0.1",port=p.parse_args().port)
