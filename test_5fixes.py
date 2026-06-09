import sys
sys.path.insert(0, '.')
import logging
import io

class _MuteFilter(logging.Filter):
    def filter(self, record):
        if record.levelno < logging.WARNING:
            return False
        return True

_root = logging.getLogger()
for _h in list(_root.handlers):
    _root.removeHandler(_h)
logging.basicConfig(level=logging.WARNING, format='%(message)s', stream=sys.stderr)
for _name in ['sqlalchemy.engine.Engine', 'sqlalchemy', 'sqlalchemy.orm', 'sqlalchemy.pool',
              'uvicorn', 'apscheduler', 'fastapi', 'starlette']:
    _l = logging.getLogger(_name)
    _l.setLevel(logging.WARNING)
    _l.addFilter(_MuteFilter())
    for _h in list(_l.handlers):
        _l.removeHandler(_h)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

import builtins as _bi
_real_print = _bi.print
_LOG_F = open('run5_full.log', 'w', encoding='utf-8')
def _p(*a, **kw):
    _real_print(*a, file=_LOG_F, flush=True, **kw)
_bi.print = _p

from fastapi.testclient import TestClient
from datetime import date, datetime
import json
import time

from app.main import app

results = []

def test(name, fn):
    try:
        fn()
        results.append((name, 'PASS'))
        print(f'  [PASS] {name}')
    except AssertionError as e:
        results.append((name, f'FAIL: {e}'))
        print(f'  [FAIL] {name}: {e}')
        import traceback; traceback.print_exc()
    except Exception as e:
        results.append((name, f'ERROR: {e}'))
        print(f'  [ERROR] {name}: {e}')
        import traceback; traceback.print_exc()

print('=' * 70)
print('Five Issues Regression (TestClient)')
print('=' * 70)

with TestClient(app) as client:
    basin = '示范流域'
    today = date.today().isoformat()

    print('\n[Q1] Transfer scheme countersign chain')
    def q1():
        rr = client.get('/api/v1/transfer/regions', params={'basin': basin})
        print(f'    regions: {json.dumps(rr.json()["data"][:5], ensure_ascii=False)}')
        pp = client.get('/api/v1/transfer/pipelines')
        print(f'    pipes: {json.dumps(pp.json()["data"], ensure_ascii=False)}')
        r = client.post('/api/v1/transfer/generate-schemes', json={'basin': basin})
        assert r.status_code == 200, f'generate HTTP {r.status_code}: {r.text}'
        d = r.json()['data']
        assert d['generated_count'] > 0, f'no scheme: {d}'
        schemes = d['schemes']
        s0 = schemes[0]
        assert isinstance(s0['required_countersign_regions'], list), \
            f'required not list: {type(s0["required_countersign_regions"])} = {s0["required_countersign_regions"]}'
        assert isinstance(s0['signed_regions'], list), \
            f'signed not list: {type(s0["signed_regions"])} = {s0["signed_regions"]}'
        scheme_id = s0['id']
        req_regions = s0['required_countersign_regions']
        print(f'    scheme id={scheme_id}, required={req_regions}, signed={s0["signed_regions"]}')

        r = client.post(f'/api/v1/transfer/schemes/{scheme_id}/submit', params={'creator_id': 1})
        assert r.status_code == 200, f'submit HTTP {r.status_code}: {r.text}'
        d = r.json()['data']
        assert isinstance(d['required_countersign_regions'], list)
        assert d['status'] == 'countersigning', f'status not countersigning: {d["status"]}'
        req_regions = d['required_countersign_regions']
        print(f'    after submit: status={d["status"]}, req={req_regions}')

        r = client.get('/api/v1/transfer/schemes')
        assert r.status_code == 200
        lst = r.json()['data']
        rec = next((x for x in lst if x['id'] == scheme_id), None)
        assert rec, f'scheme {scheme_id} missing from list'
        assert isinstance(rec['required_countersign_regions'], list), \
            f'list required not list: {rec["required_countersign_regions"]}'
        assert isinstance(rec['signed_regions'], list)

        approved_count = 0
        for rid in req_regions:
            r = client.post('/api/v1/transfer/countersign', json={
                'transfer_id': scheme_id, 'region_id': rid, 'signer_id': 1,
                'is_approved': True, 'opinion': f'region {rid} approve'
            })
            assert r.status_code == 200, f'sign region {rid} fail: {r.status_code} {r.text}'
            resp = r.json()['data']
            sch = resp['scheme']
            approved_count += 1
            print(f'    region {rid} FULL: {json.dumps(resp, ensure_ascii=False)}')
            assert isinstance(sch['signed_regions'], list)
            assert isinstance(sch['required_countersign_regions'], list)

        assert sch['status'] == 'approved', f'all signed but not approved: {sch["status"]}'
        print(f'    FINAL status={sch["status"]} (OK)')

    test('Q1_transfer_chain', q1)

    print('\n[Q2] Notification unread / read / read-all')
    def q2():
        roles_to_check = ['water_admin', 'env_officer', 'agri_officer', 'engineer', 'basin_manager', 'WATER_ADMIN', 'Env_Officer']
        for role in roles_to_check:
            r = client.get('/api/v1/notifications/unread', params={'role': role})
            assert r.status_code == 200, f'{role} unread HTTP {r.status_code}: {r.text}'
            d = r.json()['data']
            assert 'count' in d and 'messages' in d, f'keys missing: {d.keys()}'
            assert isinstance(d['count'], int), f'count not int: {type(d["count"])}'
            assert isinstance(d['messages'], list), f'messages not list: {type(d["messages"])}'
            print(f'    role={role}: unread count={d["count"]}')
            if d['messages']:
                mid = d['messages'][0]['id']
                cnt_before = d['count']
                r2 = client.put(f'/api/v1/notifications/{mid}/read')
                assert r2.status_code == 200, f'mark read HTTP {r2.status_code}'
                r3 = client.get('/api/v1/notifications/unread', params={'role': role})
                cnt_after = r3.json()['data']['count']
                print(f'      marked mid={mid}: count {cnt_before} -> {cnt_after}')

        role = 'water_admin'
        r = client.get('/api/v1/notifications/unread', params={'role': role})
        cnt_before = r.json()['data']['count']
        r = client.put('/api/v1/notifications/read-all', params={'role': role})
        assert r.status_code == 200, f'read-all HTTP {r.status_code}: {r.text}'
        marked = r.json()['data']['marked_count']
        r2 = client.get('/api/v1/notifications/unread', params={'role': role})
        cnt_after = r2.json()['data']['count']
        print(f'    read-all: marked={marked}, count {cnt_before} -> {cnt_after}')

    test('Q2_notifications', q2)

    print('\n[Q3] Report export CSV/Excel (not intercepted by detail)')
    def q3():
        today = date.today().isoformat()
        r = client.post('/api/v1/reports/generate', json={'basin': basin, 'report_date': today})
        assert r.status_code == 200, f'gen report HTTP {r.status_code}: {r.text}'
        report_id = r.json()['data']['id']
        print(f'    gen report id={report_id}')

        r = client.get('/api/v1/reports/export/csv', params={
            'basin': basin, 'start_date': today, 'end_date': today
        })
        assert r.status_code == 200, f'csv HTTP {r.status_code}: {r.text[:200]}'
        ct = r.headers.get('content-type', '')
        assert 'csv' in ct.lower(), f'CSV Content-Type wrong: {ct}'
        cd = r.headers.get('content-disposition', '')
        assert 'attachment' in cd.lower(), f'CSV not attachment: {cd}'
        content = r.content.decode('utf-8-sig')
        assert '蓄水量' in content, f'CSV 缺 蓄水量: {content[:300]}'
        assert '供水量' in content
        assert '水质达标率' in content
        assert '生态流量满足率' in content
        lines = content.splitlines()
        first_data = lines[1] if len(lines) > 1 else ''
        first_data_safe = first_data[:120].encode('ascii', errors='replace').decode('ascii')
        print(f'    CSV: {ct} | {cd[:80]}...')
        print(f'    CSV first data row: {first_data_safe}')

        r = client.get('/api/v1/reports/export/excel', params={
            'basin': basin, 'start_date': today, 'end_date': today
        })
        assert r.status_code == 200, f'excel HTTP {r.status_code}: {r.text[:200]}'
        ct = r.headers.get('content-type', '')
        assert any(k in ct.lower() for k in ('spreadsheet', 'excel', 'openxml')), \
            f'Excel Content-Type wrong: {ct}'
        cd = r.headers.get('content-disposition', '')
        assert 'attachment' in cd.lower() and '.xlsx' in cd, f'Excel no xlsx attachment: {cd}'
        assert len(r.content) > 1000, f'Excel too small: {len(r.content)}B'
        print(f'    Excel: {ct} | {cd[:80]}... ({len(r.content)}B)')

        r = client.get(f'/api/v1/reports/{report_id}')
        assert r.status_code == 200, f'detail HTTP {r.status_code}: {r.text[:200]}'
        d = r.json()['data']
        assert 'reservoir_stats_detail' in d, 'detail missing reservoir_stats_detail'
        print(f'    detail OK, reservoir_stats_detail len={len(d["reservoir_stats_detail"])}')

    test('Q3_report_export', q3)

    print('\n[Q4] WebSocket push on business triggers')
    def q4():
        from app.services import NotificationService
        from app.routers.notifications import manager as mgr

        assert NotificationService.manager is mgr, 'NotificationService.manager not bound'
        print(f'    manager bound OK: {mgr}')

        pushed = []
        class HookManager:
            def __init__(self): self.cc = 0
            async def push_to_roles(self, roles, msg):
                self.cc += 1; pushed.append(('roles', roles, msg))
            async def push_to_users(self, uids, msg):
                self.cc += 1; pushed.append(('users', uids, msg))
            async def push_to_all(self, msg):
                self.cc += 1; pushed.append(('all', None, msg))
            async def connect(self, ws, cid): pass
            def disconnect(self, cid): pass

        real_mgr = NotificationService.manager
        hook = HookManager()
        NotificationService.manager = hook
        print(f'    [DEBUG] NS.loop = {NotificationService.loop}')
        try:
            before0 = hook.cc
            r = client.post('/api/v1/dispatch/smart-calculate', json={'basin': basin})
            time.sleep(0.3)
            delta = hook.cc - before0
            print(f'    (4a) smart-calculate: push delta={delta}, status={r.status_code}, text={r.text[:300]}')
            assert r.status_code == 200, f'smart HTTP {r.status_code}: {r.text[:500]}'
            assert hook.cc > before0, 'dispatch did not trigger WS push'

            before = hook.cc
            r = client.post('/api/v1/quality/upload', params={
                'station_code': 'WQS001', 'cod': 55, 'nh3n': 3.5
            })
            time.sleep(0.3)
            delta = hook.cc - before
            print(f'    (4b) quality upload: push delta={delta}, status={r.status_code}')
            assert r.status_code == 200, f'quality HTTP {r.status_code}: {r.text[:500]}'
            assert hook.cc > before, 'quality exceed did not trigger WS push'

            before2 = hook.cc
            from app.models import WaterRight, User
            from app.database import SessionLocal
            db = SessionLocal()
            try:
                farmer = db.query(User).filter(User.username == 'farmer1').first()
                wr = db.query(WaterRight).filter(WaterRight.user_id == farmer.id).first() if farmer else None
            finally:
                db.close()
            if farmer and wr:
                r = client.post('/api/v1/irrigation/applications', json={
                    'applicant_id': farmer.id, 'region': '东区', 'crop_type': 'rice',
                    'planting_area': 200, 'requested_amount': 5000,
                    'start_date': today, 'end_date': today
                })
                time.sleep(0.3)
                print(f'    (4c) irrigation: push delta={hook.cc - before2}, status={r.status_code}')

            if pushed:
                ptype, _, pdata = pushed[0]
                assert 'type' in pdata and pdata['type'] == 'notification', f'push format wrong: {pdata}'
                assert 'title' in pdata and 'message_id' in pdata, f'push missing keys: {list(pdata.keys())}'
                print(f'    first push: type={ptype}, msg_type={pdata.get("message_type")}, '
                      f'title={pdata["title"][:40]}')
        finally:
            NotificationService.manager = real_mgr

    test('Q4_websocket_push', q4)

    print('\n[Q5] Ecological flow with no design_discharge')
    def q5():
        from app.models import Reservoir, EcologicalFlowMonitor
        from app.database import SessionLocal
        db = SessionLocal()
        try:
            rsv = Reservoir(
                name='无设计流量测试库', code='RSV_NODED', basin=basin, region='测试区',
                max_capacity=1000, normal_level=80, dead_level=50, design_discharge=None,
                current_level=78, current_storage=800, current_outflow=2, current_inflow=2.5
            )
            db.add(rsv); db.flush()
            mon = EcologicalFlowMonitor(
                section_name='测试断面_NODED', section_code='ECO_NODED', basin=basin,
                upstream_reservoir_id=rsv.id, legal_minimum_flow=8.0, current_flow=3.0
            )
            db.add(mon); db.flush(); db.commit()
            mon_id = mon.id; rsv_id = rsv.id
            print(f'    test reservoir id={rsv_id} design_discharge=None, section id={mon_id} '
                  f'legal_min=8.0 current=3.0')
        finally:
            db.close()

        r = client.post(f'/api/v1/ecological/monitor/{mon_id}/report-flow', params={'current_flow': 3.0})
        assert r.status_code == 200, f'report-flow HTTP {r.status_code}: {r.text}'
        d = r.json()['data']
        print(f'    result: adjustment={bool(d["adjustment"])}, dispatch={bool(d["dispatch_instruction"])}')
        assert d['adjustment'] is not None, 'no adjustment record'
        assert d['dispatch_instruction'] is not None, 'no dispatch instruction'
        adj = d['adjustment']
        print(f'    adjustment: prev={adj["previous_release"]} -> new={adj["adjusted_release"]}')
        assert adj['adjusted_release'] >= 8.0 * 0.9, f'new {adj["adjusted_release"]} < 90% legal'

        db = SessionLocal()
        try:
            rsv2 = db.query(Reservoir).filter(Reservoir.id == rsv_id).first()
            print(f'    reservoir outflow updated to: {rsv2.current_outflow}')
            assert rsv2.current_outflow > 2, 'outflow not updated'
        finally:
            db.close()

    test('Q5_eco_nondesign_discharge', q5)

print('\n' + '=' * 70)
print('RESULTS SUMMARY')
for n, s in results:
    flag = '[PASS]' if s == 'PASS' else '[FAIL]'
    print(f'  {flag} {n}: {s}')
print('=' * 70)
passed = sum(1 for _, s in results if s == 'PASS')
print(f'TOTAL: {len(results)} items, {passed} PASSED')

with open('FIXES_SUMMARY.txt', 'w', encoding='utf-8') as f:
    f.write('Five Issues Regression Result\n' + '='*70 + '\n')
    for n, s in results:
        f.write(f'{n}: {s}\n')
    f.write(f'Total: {len(results)} items, {passed} passed\n')
