#!/usr/bin/env python3
"""Execute native end-to-end transactions and summarize actual monotonic measurements."""
import argparse
import csv
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'host_tests'))
from conftest import Kiosk, free_port


def summarize(rows, wall_seconds):
    metrics={}
    for key in ('input_ms','validation_ms','retry_ms','generation_ms','printing_ms','total_ms','end_to_end_ms'):
        values=sorted(float(x[key]) for x in rows)
        def q(p):return values[max(0,math.ceil(len(values)*p)-1)]
        metrics[key]={'mean':statistics.mean(values),'median':statistics.median(values),'p95':q(.95),'p99':q(.99),'maximum':max(values)}
    successes=sum(bool(x['success']) for x in rows)
    return {'sample_count':len(rows),'successes':successes,'failures':len(rows)-successes,'success_rate':successes/len(rows),'failure_rate':1-successes/len(rows),'observed_transactions_per_minute':len(rows)*60/wall_seconds,'wall_seconds':wall_seconds,'quantile_method':'nearest_rank','latencies':metrics}


def main():
    p=argparse.ArgumentParser();p.add_argument('--samples-per-profile',type=int,default=5);p.add_argument('--output',default='results/benchmark');a=p.parse_args()
    if not 1<=a.samples_per_profile<=40:p.error('samples must be 1..40')
    out=ROOT/a.output;out.mkdir(parents=True,exist_ok=True)
    port=free_port();url=f'http://127.0.0.1:{port}'
    with tempfile.TemporaryDirectory(prefix='kiosk-bench-') as tmp, (out/'backend.log').open('w') as log:
        env=dict(os.environ,KIOSK_DB=tmp+'/backend.sqlite',PRINTER_DB=tmp+'/printer.sqlite',PREVIEW_DIR=str(out/'previews'))
        process=subprocess.Popen([sys.executable,'-m','uvicorn','simulator.mock_backend:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log)
        kiosk=None
        try:
            for _ in range(200):
                try:
                    if httpx.get(url+'/health',timeout=.5,trust_env=False).status_code==200:break
                except httpx.TransportError:pass
                if process.poll() is not None:raise RuntimeError('backend exited')
                time.sleep(.03)
            else:raise RuntimeError('backend startup failed')
            kiosk=Kiosk(url,Path(tmp)/'benchmark.journal','benchmark')
            rows=[];index=500;started=time.monotonic()
            for delay in (0,100,250,500,1000):
                for _ in range(a.samples_per_profile):
                    time.sleep(delay/1000)
                    token=f'TKT:valid-{index:03}';index+=1
                    # Partial frame delivery makes input_ms measure an executed 10ms inter-chunk delay.
                    kiosk.command('scan',data=token[:5]);time.sleep(.01);kiosk.command('scan',data=token[5:]+'\n')
                    kiosk.success(len(rows)+1)
                    metrics=[x['data'] for x in kiosk.events if x['event']=='metric']
                    assert len(metrics)==len(rows)+1 and metrics[-1]['success']
                    row=dict(metrics[-1],domain='host_native',artificial_pre_injection_delay_ms=delay)
                    rows.append(row)
            wall=time.monotonic()-started
            summary=summarize(rows,wall)
            resources=[x['data'] for x in kiosk.events if x['event']=='resources']
            report={'domain':'host_native','notes':['C++ native executable, loopback HTTP, SQLite FULL persistence and virtual ESC/POS printer.','Artificial 0/100/250/500/1000 ms delivery profiles and 10 ms partial-frame gap; no optical scanner measurement.','All samples use an 80 ms virtual printer duration.','Throughput includes artificial pre-injection sleeps and polling overhead; not a hardware capacity claim.','Host stack high-water marks are not FreeRTOS measurements; firmware reports those separately.'],**summary,'resources':resources,'rows':rows}
            (out/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n')
            with (out/'benchmark.csv').open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            print(json.dumps(summary,indent=2))
        finally:
            if kiosk:kiosk.close()
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
if __name__=='__main__':main()
