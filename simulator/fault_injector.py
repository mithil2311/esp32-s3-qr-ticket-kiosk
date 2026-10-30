import argparse
import json
from urllib.request import Request, urlopen


def main():
    p=argparse.ArgumentParser(description="Configure local backend or printer fault model")
    p.add_argument("target",choices=["backend","printer"])
    p.add_argument("mode")
    p.add_argument("--url",default="http://127.0.0.1:9000")
    p.add_argument("--latency-ms",type=int,default=0)
    p.add_argument("--duration-ms",type=int,default=80)
    p.add_argument("--remaining",type=int,default=-1)
    p.add_argument("--route",default="all")
    a=p.parse_args()
    body={"mode":a.mode}
    if a.target=="printer": body["duration_ms"]=a.duration_ms
    else: body.update(latency_ms=a.latency_ms,remaining=a.remaining,route=a.route)
    path="/printer/__test/faults" if a.target=="printer" else "/__test/faults"
    with urlopen(Request(a.url+path,json.dumps(body).encode(),{"Content-Type":"application/json"})) as r: print(r.read().decode())

if __name__=="__main__": main()
