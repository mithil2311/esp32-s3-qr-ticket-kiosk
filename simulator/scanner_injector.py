"""Inject scanner bytes over a QEMU UART TCP chardev or host JSONL stdin."""
import argparse
import json
import random
import socket
import sys
import time


def packets(payload, scenario):
    data = (payload + "\r\n").encode("ascii")
    if scenario == "partial": return [data[:3], data[3:7], data[7:]]
    if scenario == "corrupt": return [data[:4] + b"\x00\xff" + data[4:]]
    if scenario == "malformed": return [b"NOT-A-TICKET\n"]
    if scenario == "disconnect": return [data[:5]]
    if scenario in ("repeated", "rapid"): return [data] * 20
    return [data]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tcp", help="QEMU UART chardev address, e.g. 127.0.0.1:5556")
    p.add_argument("--payload", default="TKT:valid-001")
    p.add_argument("--scenario", choices=["valid", "invalid", "expired", "partial", "corrupt", "malformed", "repeated", "rapid", "disconnect"], default="valid")
    p.add_argument("--delay-ms", type=int, choices=[0, 100, 250, 500, 1000], default=100)
    p.add_argument("--seed", type=int, default=1)
    a = p.parse_args()
    if a.scenario=="invalid": a.payload="TKT:unknown"
    if a.scenario=="expired": a.payload="TKT:expired"
    # Artificial delivery delay, not a GM75 optical decoding measurement.
    random.seed(a.seed)
    chunks = packets(a.payload, a.scenario)
    sock = socket.create_connection(tuple([a.tcp.rsplit(':',1)[0],int(a.tcp.rsplit(':',1)[1])])) if a.tcp else None
    try:
        for data in chunks:
            time.sleep((0 if a.scenario=="rapid" else a.delay_ms)/1000)
            if sock: sock.sendall(data)
            else:
                print(json.dumps({"cmd":"raw", "hex":data.hex(), "input_us":time.monotonic_ns()//1000}),flush=True)
        if not sock and a.scenario=="disconnect": print(json.dumps({"cmd":"disconnect"}),flush=True)
    finally:
        if sock: sock.close()

if __name__ == "__main__": main()
