"""Graphical adapter API contracts; business behavior is covered by native/QEMU tests."""
from fastapi.testclient import TestClient
from simulator.dashboard import create_app, Runtime


class FakeRuntime:
    def __init__(self): self.calls=[]
    def start(self): self.calls.append('start')
    def close(self): self.calls.append('close')
    def snapshot(self, after=0): return {'domain':'qemu_xtensa_firmware','state':'IDLE','after':after}
    def scan(self, scenario, delay_ms, token):
        self.calls.append(('scan',scenario,delay_ms,token));return {'token':token or 'TKT:valid-001'}
    def set_faults(self,*args): self.calls.append(('faults',*args))
    def operator(self,action): self.calls.append(('operator',action))
    def restart(self): self.calls.append('restart')


def test_dashboard_page_and_live_observation():
    runtime=FakeRuntime()
    with TestClient(create_app(runtime)) as client:
        page=client.get('/')
        assert page.status_code==200 and 'Kiosk Lab' in page.text and 'Actual firmware in QEMU' in page.text
        assert client.get('/assets/app.js').status_code==200
        assert client.get('/api/ui/state?after=17').json()['after']==17
        assert runtime.calls==['start']
    assert runtime.calls[-1]=='close'


def test_dashboard_scan_validation():
    runtime=FakeRuntime()
    with TestClient(create_app(runtime)) as client:
        assert client.post('/api/ui/scan',json={'scenario':'partial','delay_ms':250}).status_code==202
        assert runtime.calls[-1]==('scan','partial',250,'')
        assert client.post('/api/ui/scan',json={'scenario':'invented'}).status_code==422
        assert client.post('/api/ui/scan',json={'delay_ms':1234}).status_code==422


def test_dashboard_operator_requires_verification():
    runtime=FakeRuntime()
    with TestClient(create_app(runtime)) as client:
        before=len(runtime.calls)
        assert client.post('/api/ui/operator',json={'action':'resolve_printed'}).status_code==409
        assert len(runtime.calls)==before
        assert client.post('/api/ui/operator',json={'action':'resolve_printed','verified_printed':True}).status_code==200
        assert runtime.calls[-1]==('operator','resolve_printed')
        assert client.post('/api/ui/operator',json={'action':'restart'}).status_code==200
        assert runtime.calls[-1]=='restart'


def test_dashboard_rejects_cross_origin_controls():
    runtime=FakeRuntime()
    with TestClient(create_app(runtime)) as client:
        assert client.post('/api/ui/scan',json={},headers={'Origin':'https://untrusted.example'}).status_code==403
        assert not any(isinstance(x,tuple) for x in runtime.calls)
        assert client.post('/api/ui/scan',data='scenario=valid').status_code==415
        assert client.post('/api/ui/scan',json={},headers={'Origin':'http://testserver'}).status_code==202


def test_dashboard_fault_bounds():
    runtime=FakeRuntime()
    with TestClient(create_app(runtime)) as client:
        assert client.post('/api/ui/faults',json={'printer':'paper_out','backend':'http500','duration_ms':1200,'latency_ms':250}).status_code==200
        assert runtime.calls[-1]==('faults','paper_out','http500',1200,250)
        assert client.post('/api/ui/faults',json={'duration_ms':-1}).status_code==422


def test_dashboard_cannot_inject_operator_command_as_qr(tmp_path):
    runtime=Runtime(session=tmp_path)
    try:
        for token in ('!resolve_printed','TKT:okay\n!retry','TKT:bad\x00'):
            try:runtime.scan('valid',0,token)
            except ValueError:pass
            else:raise AssertionError('control payload accepted')
        assert runtime.pending_inputs==0
    finally:runtime.client.close()
