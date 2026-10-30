import concurrent.futures
import json
import socket
import time
import uuid
from conftest import free_port


def jobs(server):return server[0].get('/printer/stats').json()['jobs']
def backend_fault(server,mode,**kw):assert server[0].post('/__test/faults',json=dict(mode=mode,**kw)).status_code==200
def printer_fault(server,mode,**kw):assert server[0].post('/printer/__test/faults',json=dict(mode=mode,**kw)).status_code==200


def test_valid_ticket(factory,server,token):
    k=factory();before=jobs(server);t=token();k.scan(t);s=k.success()
    assert jobs(server)==before+1
    job=server[0].get('/printer/jobs/'+s['operation_id']).json()
    assert t in job['preview'] and 'Museum entry' in job['preview']
    assert job['outcome']=='confirmed'
    assert server[0].get('/api/operations/'+s['operation_id']).json()['status']=='committed'
    assert {'QR_RECEIVED','VALIDATING','RESERVED','PRINTING','PRINT_CONFIRMED','COMMITTING','SUCCESS'} <= {e['data']['state'] for e in k.events if e['event']=='state'}


def test_invalid_ticket(factory,server):
    k=factory();before=jobs(server);k.scan('TKT:unknown');k.wait(lambda s:s['failures']==1 and s['state']=='IDLE')
    assert jobs(server)==before
    assert any(e['data'].get('reason')=='INVALID_TICKET' for e in k.events)


def test_expired_ticket(factory,server):
    k=factory();before=jobs(server);k.scan('TKT:expired');k.wait(lambda s:s['failures']==1 and s['state']=='IDLE')
    assert jobs(server)==before
    assert any(e['data'].get('reason')=='EXPIRED_TICKET' for e in k.events)


def test_duplicate_ticket(factory,server,token):
    t=token();a=factory();before=jobs(server);a.scan(t);a.success();a.scan(t);a.wait(lambda s:s['suppressed']==1)
    b=factory();b.scan(t);b.wait(lambda s:s['failures']==1 and s['state']=='IDLE');assert jobs(server)==before+1


def test_rapid_repeated_scanning(factory,server,token):
    k=factory();before=jobs(server);t=token();k.command('scan',data=(t+'\n')*30);k.success()
    s=k.wait(lambda s:s['queue_depth']==0);assert s['overflow']==22;assert s['suppressed']==7;assert jobs(server)==before+1


def test_backend_timeout(factory,server,token):
    backend_fault(server,'timeout');k=factory();before=jobs(server);k.scan(token());s=k.state('RECOVERY')
    assert s['successes']==0 and jobs(server)==before
    backend_fault(server,'normal');assert k.command('retry')['ok'];k.success();assert jobs(server)==before+1


def test_backend_http500(factory,server,token):
    backend_fault(server,'http500');k=factory();before=jobs(server);k.scan(token());k.state('RECOVERY');assert jobs(server)==before
    backend_fault(server,'normal');k.command('retry');k.success();assert jobs(server)==before+1


def test_network_disconnection(factory,server,token):
    # Real connection refusal on host; this models loss of connectivity, not a Wi-Fi radio.
    k=factory(backend=f'http://127.0.0.1:{free_port()}');before=jobs(server);k.scan(token());s=k.state('RECOVERY');assert not s['successes'];assert jobs(server)==before


def test_printer_paper_out(factory,server,token):
    printer_fault(server,'paper_out');k=factory();before=jobs(server);k.scan(token());k.state('RECOVERY');assert jobs(server)==before
    printer_fault(server,'normal');k.command('retry');k.success();assert jobs(server)==before+1


def test_printer_busy(factory,server,token):
    printer_fault(server,'busy');k=factory();before=jobs(server);k.scan(token());k.state('RECOVERY');assert jobs(server)==before
    printer_fault(server,'normal');k.command('retry');k.success();assert jobs(server)==before+1


def test_cutter_failure(factory,server,token):
    printer_fault(server,'cutter_failure');k=factory();before=jobs(server);k.scan(token());s=k.state('UNCERTAIN');assert jobs(server)==before+1
    assert server[0].get('/api/operations/'+s['operation_id']).json()['status']=='reserved'
    assert not k.command('retry')['ok']


def test_restart_during_printing(factory,server,token,tmp_path):
    printer_fault(server,'normal',duration_ms=400);journal=tmp_path/'power.journal';k=factory(journal);before=jobs(server);k.scan(token());k.state('PRINTING')
    assert jobs(server)==before+1;k.close();b=factory(journal);b.state('UNCERTAIN');time.sleep(.45);assert jobs(server)==before+1


def test_restart_after_reservation(factory,server,token,tmp_path):
    journal=tmp_path/'reserved.journal';k=factory(journal,env={'KIOSK_CRASH_AT':'RESERVED'});before=jobs(server);k.scan(token());assert k.p.wait(timeout=5)==86
    assert jobs(server)==before;k.close();b=factory(journal);b.success();assert jobs(server)==before+1


def test_duplicate_backend_requests(server,token):
    client=server[0];identity={'operation_id':uuid.uuid4().hex,'device_id':'test-kiosk','ticket_token':token()}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        rows=list(pool.map(lambda _:client.post('/api/tickets/reserve',json=identity).json(),range(12)))
    assert len({x['reservation_id'] for x in rows})==1 and rows[0]['authorized']
    identity['reservation_id']=rows[0]['reservation_id']
    rows=[client.post('/api/tickets/commit',json=identity).json() for _ in range(3)]
    assert all(x['status']=='committed' for x in rows)
    assert client.post('/api/tickets/reserve',json=dict(identity,device_id='attacker')).status_code==409
    assert client.post('/api/tickets/commit',json=dict(identity,reservation_id='bad')).status_code==409


def test_partial_uart_data(factory,server,token):
    k=factory();before=jobs(server);t=token();k.command('scan',data=t[:3]);time.sleep(.03);k.command('scan',data=t[3:8]);time.sleep(.03);assert jobs(server)==before
    k.command('scan',data=t[8:]+'\r\n');k.success();assert jobs(server)==before+1


def test_malformed_qr_payload(factory,server):
    k=factory();before=jobs(server);k.scan('BAD PAYLOAD');k.scan('TKT:hello;world');k.wait(lambda s:s['malformed']==2);assert jobs(server)==before
    k.command('raw',hex=b'TKT:valid-001\x00\xff\n'.hex());assert k.command('status')['scanner_corrupt']==1;assert jobs(server)==before


def test_queue_overflow(factory,server,token):
    k=factory();before=jobs(server);k.command('scan',data=''.join(token()+'\n' for _ in range(20)));k.success(8)
    s=k.status();assert s['overflow']==12 and s['queue_peak']==8;assert jobs(server)==before+8


def test_recovery_from_uncertain(factory,server,token,tmp_path):
    printer_fault(server,'incomplete');journal=tmp_path/'uncertain.journal';k=factory(journal);before=jobs(server);k.scan(token());s=k.state('UNCERTAIN');op=s['operation_id'];k.close()
    b=factory(journal);b.state('UNCERTAIN');assert b.command('resolve_printed')['ok'];b.state('IDLE');assert jobs(server)==before+1
    assert server[0].get('/api/operations/'+op).json()['status']=='committed'
    assert not b.command('resolve_printed')['ok']


def test_restart_before_commit(factory,server,token,tmp_path):
    journal=tmp_path/'confirm.journal';k=factory(journal,env={'KIOSK_CRASH_AT':'PRINT_CONFIRMED'});before=jobs(server);k.scan(token());assert k.p.wait(timeout=5)==86;k.close()
    b=factory(journal);b.state('IDLE');assert jobs(server)==before+1
    assert server[0].get('/api/operations/'+b.status()['operation_id']).json()['status']=='committed'


def test_restart_before_reserve(factory,server,token,tmp_path):
    journal=tmp_path/'created.journal';k=factory(journal,env={'KIOSK_CRASH_AT':'VALIDATING'});before=jobs(server);k.scan(token());assert k.p.wait(timeout=5)==86;k.close()
    b=factory(journal);b.state('IDLE');assert jobs(server)==before+1


def test_lost_commit_response(factory,server,token):
    backend_fault(server,'lost_commit_response',route='commit',remaining=1);k=factory();before=jobs(server);k.scan(token());k.success();assert jobs(server)==before+1


def test_printer_disconnect(factory,server,token):
    printer_fault(server,'disconnect');k=factory();before=jobs(server);k.scan(token());k.state('UNCERTAIN');assert jobs(server)==before


def test_corrupt_journal(factory,server,tmp_path):
    journal=tmp_path/'corrupt.journal';journal.write_bytes(b'corrupt');k=factory(journal);s=k.state('RECOVERY');assert s['locked'];assert not k.command('retry')['ok'];assert journal.read_bytes()==b'corrupt'


def test_journal_failure_before_print(factory,server,token):
    k=factory(env={'KIOSK_JOURNAL_FAIL_STAGE':'3'});before=jobs(server);k.scan(token());s=k.state('RECOVERY');assert s['locked'];assert jobs(server)==before


def test_scanner_disconnect_and_stale_frame(factory,server,token):
    k=factory();before=jobs(server);k.command('scan',data='TKT:part');k.command('disconnect');k.scan(token());k.success();assert jobs(server)==before+1
    k.command('scan',data='TKT:stale');time.sleep(1.05);k.command('scan',data='bad\n');k.wait(lambda s:s['malformed']>=1);assert jobs(server)==before+1


def test_competing_reservations(server,token):
    client=server[0];t=token()
    def reserve(_):return client.post('/api/tickets/reserve',json={'operation_id':uuid.uuid4().hex,'device_id':'test-kiosk','ticket_token':t}).json()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(reserve,range(8)))
    assert sum(r['authorized'] for r in rows)==1


def test_monotonic_metrics(factory,server,token):
    backend_fault(server,'http500',remaining=2);k=factory();k.scan(token());k.success()
    rows=[e['data'] for e in k.events if e['event']=='metric'];assert len(rows)==1
    row=rows[0];assert row['retry_ms']>=300 and row['printing_ms']>=50;assert row['total_ms']>=row['retry_ms']+row['printing_ms'];assert row['success']


def test_server_commit_before_local_journal_failure(factory,server,token,tmp_path):
    journal=tmp_path/'commit-reply.journal';k=factory(journal,env={'KIOSK_JOURNAL_FAIL_STAGE':'5'});before=jobs(server);k.scan(token());s=k.state('RECOVERY')
    assert s['locked'] and jobs(server)==before+1
    assert server[0].get('/api/operations/'+s['operation_id']).json()['status']=='committed'
    k.close();b=factory(journal);b.success();assert jobs(server)==before+1


def test_restart_committed_and_duplicate_suppression(factory,server,token,tmp_path):
    journal=tmp_path/'done.journal';t=token();k=factory(journal);before=jobs(server);k.scan(t);k.success();k.close()
    b=factory(journal);b.state('IDLE');b.scan(t);s=b.wait(lambda s:s['suppressed']==1);assert jobs(server)==before+1 and s['queue_depth']==0


def test_overlength_uart_frame_discard(factory,server,token):
    k=factory();before=jobs(server);k.command('scan',data='TKT:'+'x'*150+'\n');assert k.command('status')['scanner_corrupt']==1
    assert jobs(server)==before;k.scan(token());k.success();assert jobs(server)==before+1


def test_external_input_timestamp_and_end_to_end(factory,token):
    k=factory();k.command('scan',data=token()+'\n',input_us=time.monotonic_ns()//1000-20000);k.success()
    row=[e['data'] for e in k.events if e['event']=='metric'][0]
    assert row['input_ms']>=20
    assert abs(row['end_to_end_ms']-row['input_ms']-row['total_ms'])<1
