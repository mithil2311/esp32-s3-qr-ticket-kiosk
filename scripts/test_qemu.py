#!/usr/bin/env python3
"""Run actual ESP32-S3 firmware in Espressif QEMU with UART1 TCP and OpenETH adapters."""
import csv
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'host_tests'))
from conftest import free_port
from importlib.machinery import SourceFileLoader
bench=SourceFileLoader('bench',str(ROOT/'scripts/benchmark.py')).load_module()
OUT=ROOT/'results/qemu'


class Guest:
    def __init__(self,image,label):
        self.events=[];self.lines=[];self.label=label;self.port=free_port()
        self.p=subprocess.Popen([str(ROOT/'scripts/run_qemu.sh')],cwd=ROOT,env=dict(os.environ,KIOSK_FLASH_IMAGE=str(image),KIOSK_UART_PORT=str(self.port)),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
        self.reader=threading.Thread(target=self.read,daemon=True);self.reader.start()
    def read(self):
        with (OUT/(self.label+'.log')).open('w') as log:
            for line in self.p.stdout:
                log.write(line);log.flush();self.lines.append(line)
                start=line.find('{"event":')
                if start>=0:
                    try:self.events.append(json.loads(line[start:]))
                    except json.JSONDecodeError:pass
    def wait(self,predicate,timeout=25):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if predicate():return
            if self.p.poll() is not None:raise AssertionError(f'QEMU exited {self.p.returncode}; see {self.label}.log')
            time.sleep(.02)
        raise AssertionError(f'QEMU timeout {self.label}; last lines: '+''.join(self.lines[-8:]))
    def state(self,s,after=0):self.wait(lambda:any(e['event']=='state' and e['data']['state']==s for e in self.events[after:]))
    def send(self,data):
        with socket.create_connection(('127.0.0.1',self.port),timeout=3) as s:s.sendall(data.encode())
    def close(self):
        if self.p.poll() is None:self.p.terminate()
        try:self.p.wait(timeout=5)
        except subprocess.TimeoutExpired:self.p.kill();self.p.wait()
        self.reader.join(timeout=2);self.p.stdout.close();self.p.stdin.close()


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    # Firmware base URL is deliberately fixed by sdkconfig; avoid talking to an unknown service.
    with socket.socket() as s:s.bind(('127.0.0.1',9000))
    results=[];metrics=[];resources=[];guests=[]
    with tempfile.TemporaryDirectory(prefix='kiosk-qemu-') as tmp, (OUT/'backend.log').open('w') as log:
        tmp=Path(tmp);env=dict(os.environ,KIOSK_DB=str(tmp/'backend.sqlite'),PRINTER_DB=str(tmp/'printer.sqlite'),PREVIEW_DIR=str(OUT/'previews'))
        backend=subprocess.Popen([sys.executable,'-m','uvicorn','simulator.mock_backend:app','--host','127.0.0.1','--port','9000'],cwd=ROOT,env=env,stdout=log,stderr=log)
        client=httpx.Client(base_url='http://127.0.0.1:9000',timeout=5,trust_env=False)
        try:
            for _ in range(200):
                try:
                    if client.get('/health').status_code==200:break
                except httpx.TransportError:pass
                time.sleep(.03)
            else:raise AssertionError('backend did not start')
            def guest(label,image=None):
                image=image or tmp/(label+'.bin')
                if not image.exists():shutil.copyfile(ROOT/'firmware/build/flash_image.bin',image)
                g=Guest(image,label);guests.append(g);return g,image
            def count():return client.get('/printer/stats').json()['jobs']
            def result(label):results.append({'test':label,'passed':True});print('PASS',label,flush=True)
            g,image=guest('uart1-runtime');g.state('IDLE');time.sleep(.3)
            before=count();mark=len(g.events);g.send('TKT:valid-701\r\n');g.state('SUCCESS',mark);assert count()==before+1
            result('UART1 external TCP input and valid ticket')
            mark=len(g.events);g.send('TKT:unknown\n');g.state('REJECTED',mark);assert count()==before+1;result('invalid ticket never prints')
            mark=len(g.events);g.send('TKT:valid-701\n');g.wait(lambda:any(e['event']=='scan_drop' and e['data'].get('reason')=='LOCAL_DUPLICATE' for e in g.events[mark:]));assert count()==before+1;result('duplicate suppression')
            mark=len(g.events);g.send('TKT:valid-');time.sleep(.1);assert count()==before+1;g.send('702\n');g.state('SUCCESS',mark);assert count()==before+2;result('partial UART packets')
            client.post('/__test/faults',json={'mode':'http500','remaining':2});mark=len(g.events);g.send('TKT:valid-703\n');g.state('SUCCESS',mark);assert any(e['event']=='state' and e['data']['state']=='RETRY' for e in g.events[mark:]);assert count()==before+3;result('backend 500 exponential retry')
            client.post('/printer/__test/faults',json={'mode':'paper_out'});mark=len(g.events);g.send('TKT:valid-704\n');g.state('RECOVERY',mark);assert count()==before+3
            client.post('/printer/__test/faults',json={'mode':'normal'});mark=len(g.events);g.send('!retry\n');g.state('SUCCESS',mark);assert count()==before+4;result('paper out recovery before print')
            client.post('/printer/__test/faults',json={'mode':'cutter_failure'});mark=len(g.events);g.send('TKT:valid-705\n');g.state('UNCERTAIN',mark);assert count()==before+5
            mark=len(g.events);g.send('!resolve_printed\n');g.state('SUCCESS',mark);assert count()==before+5;result('cutter uncertainty and operator commit without reprint')
            client.post('/printer/__test/faults',json={'mode':'normal','duration_ms':2000});mark=len(g.events);g.send('TKT:valid-706\n');g.state('PRINTING',mark)
            deadline=time.monotonic()+5
            while count()!=before+6 and time.monotonic()<deadline:time.sleep(.02)
            assert count()==before+6;g.close()
            b,_=guest('nvs-power-recovery',image);b.state('UNCERTAIN');time.sleep(2.1);assert count()==before+6
            mark=len(b.events);b.send('!resolve_printed\n');b.state('SUCCESS',mark);assert count()==before+6;result('NVS restart during printing has no automatic reprint')
            b.close()
            for instance in guests:
                metrics.extend(dict(e['data'],domain='qemu_xtensa_firmware') for e in instance.events if e['event']=='metric')
                resources.extend(e['data'] for e in instance.events if e['event']=='resources')
            (OUT/'results.json').write_text(json.dumps({'toolchain':'ESP-IDF v5.5.1; Espressif QEMU 9.2.2 esp_develop_9.2.2_20260417','uart':'UART1 external TCP chardev verified by guest transactions','network':'OpenETH emulation, not Wi-Fi','printer':'HTTP virtual printer, not USB/Bluetooth','tests':results,'metrics':metrics,'resources':resources},indent=2)+'\n')
            if metrics:
                with (OUT/'benchmark.csv').open('w',newline='') as f:
                    writer=csv.DictWriter(f,fieldnames=list(metrics[0]));writer.writeheader();writer.writerows(metrics)
                summary=bench.summarize(metrics,sum(m['total_ms'] for m in metrics)/1000)
                summary['active_transaction_equivalent_per_minute']=summary.pop('observed_transactions_per_minute')
                summary['active_transaction_seconds']=summary.pop('wall_seconds')
                summary['notes']=['Mixed functional/fault scenarios; throughput is active-transaction equivalent, excludes idle and reboot time.','Emulator timing is not ESP32 hardware performance.','Uncertain and no-start attempts are counted as failures even if later operator reconciliation succeeds.']
                (OUT/'benchmark.json').write_text(json.dumps(summary,indent=2)+'\n')
            assert len(results)==8
            print(f'{len(results)} QEMU runtime checks passed',flush=True)
        finally:
            for g in guests:g.close()
            client.close();backend.terminate()
            try:backend.wait(timeout=5)
            except subprocess.TimeoutExpired:backend.kill();backend.wait()
if __name__=='__main__':main()
