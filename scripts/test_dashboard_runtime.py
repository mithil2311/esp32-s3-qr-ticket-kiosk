#!/usr/bin/env python3
"""Exercise the graphical dashboard API against its live QEMU guest.

Start simulator/dashboard.py first. This script sends demonstration tickets,
faults and a guest restart, and leaves normal models and an idle guest afterwards.
It checks actual guest events; it does not claim a rendered-browser visual test.
"""
import argparse
import json
from pathlib import Path
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8080')
    args=parser.parse_args()
    checks=[]
    with httpx.Client(base_url=args.url,timeout=8,trust_env=False) as client, httpx.Client(base_url='http://127.0.0.1:9000',timeout=3,trust_env=False) as backend:
        def snap():
            response=client.get('/api/ui/state');response.raise_for_status();return response.json()
        def wait(predicate):
            deadline=time.monotonic()+18;state=None
            while time.monotonic()<deadline:
                state=snap()
                if predicate(state):return state
                time.sleep(.05)
            raise AssertionError('Dashboard runtime wait timed out: '+str(state and (state['state'],state['reason'])))
        def post(path,body):
            response=client.post(path,json=body);response.raise_for_status();return response.json()
        def faults(printer='normal',server='normal'):
            post('/api/ui/faults',{'printer':printer,'backend':server,'duration_ms':800,'latency_ms':100})
        def scan(scenario='valid'):
            return post('/api/ui/scan',{'scenario':scenario,'delay_ms':100})
        def jobs():return backend.get('/printer/stats').json()['jobs']
        def passed(label):
            checks.append({'check':label,'passed':True});print('PASS',label,flush=True)
        state=wait(lambda s:s['state']=='IDLE')
        assert state['domain']=='qemu_xtensa_firmware' and state['qemu_running']
        faults();before=jobs();n=state['successes'];issued=scan()
        state=wait(lambda s:s['state']=='IDLE' and s['successes']==n+1)
        assert jobs()==before+1 and issued['token'] in state['printer_job']['preview']
        passed('Graphical scan control produces a committed ticket and real ESC/POS preview')
        rejected=state['rejected'];before=jobs();scan('invalid')
        wait(lambda s:s['state']=='IDLE' and s['rejected']==rejected+1)
        assert jobs()==before;passed('Invalid ticket control cannot print')
        state=snap();n=state['successes'];scan('partial')
        wait(lambda s:s['state']=='IDLE' and s['successes']==n+1)
        passed('Partial UART scenario reaches actual firmware')
        faults('paper_out');before=jobs();n=snap()['successes'];scan()
        wait(lambda s:s['state']=='RECOVERY');assert jobs()==before
        faults();post('/api/ui/operator',{'action':'retry'})
        wait(lambda s:s['state']=='IDLE' and s['successes']==n+1)
        assert jobs()==before+1;passed('Paper-out control and operator retry preserve the operation')
        faults(server='http500');before=jobs();n=snap()['successes'];scan()
        wait(lambda s:s['state']=='RECOVERY');assert jobs()==before
        faults();post('/api/ui/operator',{'action':'retry'})
        wait(lambda s:s['state']=='IDLE' and s['successes']==n+1)
        assert jobs()==before+1;passed('Backend fault control fails closed and recovers')
        faults('cutter_failure');before=jobs();n=snap()['successes'];scan()
        state=wait(lambda s:s['state']=='UNCERTAIN');op=state['operation_id']
        assert jobs()==before+1
        assert client.post('/api/ui/operator',json={'action':'resolve_printed'}).status_code==409
        post('/api/ui/operator',{'action':'restart'})
        state=wait(lambda s:s['state']=='UNCERTAIN' and s['operation_id']==op)
        assert jobs()==before+1
        faults();post('/api/ui/operator',{'action':'resolve_printed','verified_printed':True})
        wait(lambda s:s['state']=='IDLE' and s['successes']==n+1)
        assert jobs()==before+1;passed('GUI restart preserves NVS uncertainty; verified reconciliation never reprints')
        # Return a useful, normal-speed ready-to-use demonstration to the user.
        post('/api/ui/faults',{'printer':'normal','backend':'normal','duration_ms':1200,'latency_ms':250})
        n=snap()['successes'];scan();last=wait(lambda s:s['state']=='IDLE' and s['successes']==n+1)
        report={'domain':'qemu_xtensa_firmware','browser_rendering_verified':False,
                'notes':'Browser automation unavailable. These assertions test GUI HTTP controls, UART1, actual guest events and printer capture.',
                'checks':checks,'final_state':last['state'],'final_operation':last['operation_id'],
                'qemu_running':last['qemu_running'],'session_directory':last['session_directory']}
        (ROOT/'results/gui-runtime-checks.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'{len(checks)} live graphical-adapter checks passed')

if __name__=='__main__':main()
