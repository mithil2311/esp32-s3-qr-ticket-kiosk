import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time
import httpx
import pytest

ROOT=Path(__file__).resolve().parents[1]
RESULTS=ROOT/'results'


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0)); return s.getsockname()[1]


@pytest.fixture(scope='session')
def server(tmp_path_factory):
    work=tmp_path_factory.mktemp('backend')
    port=free_port();url=f'http://127.0.0.1:{port}'
    env=dict(os.environ,KIOSK_DB=str(work/'tickets.sqlite'),PRINTER_DB=str(work/'printer.sqlite'),PREVIEW_DIR=str(RESULTS/'previews'))
    RESULTS.mkdir(exist_ok=True)
    with (RESULTS/'backend-test.log').open('w') as log:
        p=subprocess.Popen([sys.executable,'-m','uvicorn','simulator.mock_backend:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log)
        try:
            for _ in range(200):
                if p.poll() is not None: raise RuntimeError('backend exited; see results/backend-test.log')
                try:
                    if httpx.get(url+'/health').status_code==200: break
                except httpx.TransportError: pass
                time.sleep(.03)
            else: raise RuntimeError('backend startup timeout')
            with httpx.Client(base_url=url,timeout=3,trust_env=False) as client:
                yield client,url,work
        finally:
            p.terminate()
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:p.kill();p.wait()


@pytest.fixture(autouse=True)
def normal_faults(server):
    client,_,_=server
    client.post('/__test/faults',json={'mode':'normal'})
    client.post('/printer/__test/faults',json={'mode':'normal','duration_ms':60})
    yield
    client.post('/__test/faults',json={'mode':'normal'})
    client.post('/printer/__test/faults',json={'mode':'normal','duration_ms':60})


class Kiosk:
    def __init__(self,url,journal,label,env=None,backend=None):
        self.events=[];self.responses=queue.Queue();self.counter=0;self.label=label
        executable=os.environ.get('KIOSK_HOST',str(ROOT/'build/kiosk_host'))
        self.error=(RESULTS/(label.replace('/','_')+'-host.stderr')).open('a')
        self.p=subprocess.Popen([executable,'--backend',backend or url,'--printer',url,'--journal',str(journal),'--device','test-kiosk','--timeout-ms','150'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.error,text=True,bufsize=1,env=dict(os.environ,**(env or {})))
        self.reader=threading.Thread(target=self._read,daemon=True);self.reader.start()
    def _read(self):
        with (RESULTS/'integration-events.jsonl').open('a') as output:
            for line in self.p.stdout:
                event=json.loads(line);event['test']=self.label;event['domain']='host_native';self.events.append(event)
                output.write(json.dumps(event)+'\n');output.flush()
                if event['event']=='response':self.responses.put(event['data'])
    def command(self,cmd,**kw):
        self.counter+=1
        self.p.stdin.write(json.dumps(dict(cmd=cmd,id=self.counter,**kw))+'\n');self.p.stdin.flush()
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            response=self.responses.get(timeout=5)
            if response['id']==self.counter:return response
        raise AssertionError('missing response')
    def scan(self,token):return self.command('scan',data=token+'\n')
    def status(self):return self.command('status')['status']
    def wait(self,predicate,timeout=6):
        deadline=time.monotonic()+timeout;state=None
        while time.monotonic()<deadline:
            assert self.p.poll() is None, f'host exited {self.p.returncode}'
            state=self.status()
            if predicate(state):return state
            time.sleep(.01)
        raise AssertionError(f'timeout: {state}')
    def success(self,n=1):return self.wait(lambda s:s['successes']>=n and s['state']=='IDLE')
    def state(self,value):return self.wait(lambda s:s['state']==value)
    def close(self):
        if self.p.poll() is None:self.p.kill()
        self.p.wait(timeout=5);self.reader.join(timeout=2);self.p.stdin.close();self.p.stdout.close();self.error.close()


@pytest.fixture
def factory(server,tmp_path,request):
    _,url,_=server;instances=[]
    def create(journal=None,**kwargs):
        k=Kiosk(url,journal or tmp_path/f'host{len(instances)}.journal',request.node.name,**kwargs);instances.append(k);return k
    yield create
    for k in instances:k.close()


@pytest.fixture(scope='session')
def token():
    seq=10
    def next_token():
        nonlocal seq
        seq+=1;return f'TKT:valid-{seq:03}'
    return next_token
