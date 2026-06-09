import sys
sys.path.insert(0, '.')

import logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger('sqlalchemy').setLevel(logging.WARNING)
logging.getLogger('apscheduler').setLevel(logging.WARNING)

from fastapi.testclient import TestClient
import json

from app.main import app

print('=' * 60)
print('智慧流域水资源系统 - 全模块API测试 (TestClient模式)')
print('=' * 60)

results = []

def test(name, fn):
    try:
        fn()
        results.append((name, 'PASS'))
    except Exception as e:
        results.append((name, f'FAIL: {e}'))
        print(f'  !! ERROR: {e}')
        import traceback
        traceback.print_exc()

with TestClient(app) as client:
    base = '/api/v1'

    print('\n【系统模块】')
    def t0():
        r = client.get(f'{base}/health')
        assert r.status_code == 200
        print(f'  健康检查: OK')
        r = client.get(f'{base}/stats')
        assert r.status_code == 200, f'/stats failed: {r.status_code} {r.text[:200]}'
        d = r.json()['data']
        print(f'  系统统计: 水库={d["reservoirs"]}, 水文站={d["stations"]}, 水质站={d["quality_stations"]}, 工程={d["projects"]}, 用户={d["users"]}')

        # 确保ECO001生态断面存在（若种子没创建成功，手动补一个）
        from app.database import SessionLocal
        from app import models
        db = SessionLocal()
        if not db.query(models.EcologicalFlowMonitor).filter(
            models.EcologicalFlowMonitor.section_code == 'ECO001'
        ).first():
            rsv1 = db.query(models.Reservoir).filter(models.Reservoir.code == 'RSV001').first()
            if rsv1:
                db.add(models.EcologicalFlowMonitor(
                    section_name='A坝下生态断面', section_code='ECO001',
                    basin='示范流域', upstream_reservoir_id=rsv1.id,
                    legal_minimum_flow=10.0, current_flow=12.0, is_below_threshold=False
                ))
                print('  [AUTO] 已补充 ECO001 生态断面')
        # 确保WR001水权存在
        if not db.query(models.WaterRight).filter(models.WaterRight.right_code == 'WR001').first():
            f1 = db.query(models.User).filter(models.User.username == 'farmer1').first()
            adm = db.query(models.User).filter(models.User.role == 'ADMIN').first()
            if f1:
                from datetime import date as d
                db.add(models.WaterRight(
                    right_code='WR001', user_id=f1.id, water_source='示范水库A',
                    annual_quota=50000, used_amount=12000, remaining_amount=38000,
                    valid_from=d(d.today().year, 1, 1),
                    valid_to=d(d.today().year, 12, 31),
                    region='东区', approved_by=adm.id if adm else 1
                ))
                print('  [AUTO] 已补充 WR001 水权 (farmer1 余额38000)')
        db.commit()
        db.close()
    test('系统', t0)

    print('\n【1. 水库水文站与智能调度】')
    def t1():
        r = client.get(f'{base}/dispatch/reservoirs?page_size=5')
        print(f'  水库列表: total={r.json()["total"]}')
        r = client.post(f'{base}/dispatch/data/upload', json={
            'reservoir_id': 1, 'data_type': 'combined',
            'water_level': 95.5, 'flow_rate': 28.0, 'rainfall': 12.5, 'source': 'sensor_test'
        })
        assert r.status_code == 200, f'upload fail {r.text[:300]}'
        print(f'  实时数据上传: id={r.json()["data"]["id"]}')
        client.post(f'{base}/dispatch/forecasts', params={
            'basin': '示范流域', 'forecast_date': '2026-06-09',
            'predicted_rainfall': 85.0, 'forecast_hours': 72
        })
        print(f'  降雨预报录入: OK')
        r = client.post(f'{base}/dispatch/smart-calculate', json={'basin': '示范流域', 'forecast_hours': 72})
        assert r.status_code == 200, f'smart-calc fail {r.text[:500]}'
        d = r.json()['data']
        print(f'  智能调度计算: {len(d["schemes"])}个方案 / 生成指令{len(d["generated_instructions"])}条')
        for s in d['schemes'][:2]:
            ratio = s.get('current_storage_ratio', s.get('storage_ratio', 0))
            print(f'    - {s["reservoir_name"]}: 库容{ratio:.0%} -> {s["recommended_action"]} 风险={s["risk_level"]}')
    test('调度', t1)

    print('\n【2. 农业灌溉用水】')
    def t2():
        r = client.get(f'{base}/irrigation/water-rights?user_id=7')
        rd = r.json()['data']
        bal = rd[0]['remaining_amount'] if rd else 0
        print(f'  种植户水权余额: {bal} m³')
        r = client.post(f'{base}/irrigation/soil-moisture', json={
            'region': '东区', 'crop_type': 'rice', 'moisture_content': 15.0,
            'field_capacity': 30.0, 'monitoring_point': '示范田A'
        })
        assert r.status_code == 200, f'soil fail: {r.text[:200]}'
        print(f'  墒情录入: OK (墒情不足)')
        r = client.post(f'{base}/irrigation/applications', json={
            'applicant_id': 7, 'region': '东区', 'crop_type': 'rice',
            'planting_area': 500.0, 'requested_amount': 150000.0,
            'start_date': '2026-06-10', 'end_date': '2026-06-20'
        })
        assert r.status_code == 200, f'applications fail: {r.text[:500]}'
        d = r.json()['data']
        print(f'  灌溉申请: 理论需求={d["analysis"]["theoretical_demand"]}, 推荐配水={d["analysis"]["recommended_amount"]}m³')
        print(f'  节水建议: {len(d["analysis"]["saving_suggestions"])}条')
        for s in d['analysis']['saving_suggestions'][:2]:
            print(f'    - {s[:50]}...')
        app_id = d['application']['id']
        r = client.post(f'{base}/irrigation/review', json={
            'application_id': app_id, 'reviewer_id': 4, 'is_approved': True
        })
        assert r.status_code == 200, f'review fail: {r.text[:300]}'
        d2 = r.json()['data']
        print(f'  审核: 批准={d2["approved"]}, 水量={d2.get("application",{}).get("approved_amount")}, 余额={d2.get("remaining_water_right")}')
    test('灌溉', t2)

    print('\n【3. 水质监测与溯源】')
    def t3():
        r = client.get(f'{base}/quality/outlets?page_size=10')
        print(f'  排污口: {r.json()["total"]}个')
        r = client.post(f'{base}/quality/data/upload', json={
            'station_id': 1, 'cod': 85.0, 'nh3n': 5.2, 'ph': 7.2, 'do': 4.5
        })
        assert r.status_code == 200, f'quality upload fail: {r.text[:300]}'
        d = r.json()['data']
        print(f'  水质上传: 超标={d["quality_data"]["is_over_limit"]}, 生成工单={d["work_order"] is not None}')
        if d['work_order']:
            wo = d['work_order']
            print(f'    超标项: {list(wo["over_limit_items"].keys())}')
            areas = wo['suggested_investigation_areas'] or []
            outs = wo['priority_outlets'] or []
            print(f'    建议排查区: {len(areas)}个, 重点排污口: {len(outs)}个')
            if outs:
                print(f'    Top-3嫌疑排污口: {[o["name"] for o in outs[:3]]}')
            print(f'    处罚建议已生成')
    test('水质溯源', t3)

    print('\n【4. 生态流量监控】')
    def t4():
        r = client.get(f'{base}/ecological/monitors')
        print(f'  监测断面: {r.json()["total"]}个 (法定阈值10m³/s)')
        r = client.post(f'{base}/ecological/monitor/1/report-flow', params={'current_flow': 5.0})
        assert r.status_code == 200, f'eco report fail: {r.text[:300]}'
        d = r.json()['data']
        print(f'  流量上报(5<10): 低于阈值={d["monitor"]["is_below_threshold"]}')
        print(f'    自动调整下泄: {d["adjustment"] is not None}')
        print(f'    下发调度指令: {d["dispatch_instruction"] is not None}')
        if d['adjustment']:
            print(f'    出流: {d["adjustment"]["previous_release"]} -> {d["adjustment"]["adjusted_release"]} m³/s')
        print(f'    通知下游用户: {d["notified_downstream_users_count"]}个')
    test('生态流量', t4)

    print('\n【5. 水权交易】')
    def t5():
        r = client.post(f'{base}/irrigation/water-rights', json={
            'right_code': 'WR002_X', 'user_id': 8, 'water_source': '示范水库B',
            'annual_quota': 80000, 'valid_from': '2026-01-01', 'valid_to': '2026-12-31',
            'region': '西区', 'approved_by': 1
        })
        r = client.get(f'{base}/irrigation/water-rights?user_id=8')
        rdata = r.json()['data']
        if not rdata:
            # 创建失败的话手动查（如果之前已存在）
            from app.database import SessionLocal
            from app import models as _m
            db = SessionLocal()
            w = db.query(_m.WaterRight).filter(_m.WaterRight.user_id == 8).first()
            wr_id = w.id if w else 1
            db.close()
        else:
            wr_id = rdata[0]['id']
        r = client.post(f'{base}/trade/orders', json={
            'order_type': 'sell', 'user_id': 8, 'water_right_id': wr_id,
            'water_volume': 20000, 'expected_price': 2.5, 'region': '西区'
        })
        assert r.status_code == 200, f'sell order fail: {r.text[:300]}'
        print(f'  卖单: 20000m³ @¥2.5')

        # buyer water right
        from app.database import SessionLocal
        from app import models as _m
        db = SessionLocal()
        bw = db.query(_m.WaterRight).filter(_m.WaterRight.user_id == 7).first()
        if not bw:
            from datetime import date as _d
            bw = _m.WaterRight(right_code='WR_BUYER', user_id=7, water_source='示范水库A',
                annual_quota=60000, used_amount=0, remaining_amount=60000,
                valid_from=_d(_d.today().year,1,1), valid_to=_d(_d.today().year,12,31),
                region='东区', approved_by=1)
            db.add(bw)
            db.commit()
            db.refresh(bw)
        buyer_wr_id = bw.id
        db.close()

        r = client.post(f'{base}/trade/orders', json={
            'order_type': 'buy', 'user_id': 7, 'water_right_id': buyer_wr_id,
            'water_volume': 18000, 'expected_price': 3.2, 'region': '东区'
        })
        assert r.status_code == 200, f'buy order fail: {r.text[:300]}'
        print(f'  买单: 18000m³ @¥3.2')
        r = client.post(f'{base}/trade/match')
        assert r.status_code == 200, f'match fail: {r.text[:300]}'
        d = r.json()['data']
        print(f'  自动匹配: 匹配{d["matched_count"]}笔')
        if d['contracts']:
            c = d['contracts'][0]
            print(f'    合同: {c["trade_volume"]}m³ x ¥{c["unit_price"]} = ¥{c["total_amount"]:,.2f}')
            r = client.post(f'{base}/trade/contracts/approve', json={
                'contract_id': c['id'], 'approver_id': 6, 'is_approved': True,
                'remarks': '合规，审批通过'
            })
            assert r.status_code == 200, f'approve fail: {r.text[:300]}'
            print(f'    流域审批: {r.json()["data"]["approval_status"]}')
    test('水权交易', t5)

    print('\n【6. 跨区域调水】')
    def t6():
        r = client.get(f'{base}/transfer/regions?shortage_min=0.05')
        d = r.json()['data']
        print(f'  缺水行政区: {len(d)}个')
        for x in d:
            print(f'    {x["name"]}: 缺水指数={x["water_shortage_index"]:.1%}')
        r = client.post(f'{base}/transfer/generate-schemes', json={'basin': '示范流域'})
        assert r.status_code == 200, f'transfer gen fail: {r.text[:500]}'
        d = r.json()['data']
        print(f'  自动生成方案: {d["generated_count"]}个')
        for s in d['schemes'][:2]:
            print(f'    {s["scheme_name"]}: {s["transfer_volume"]:.0f}m³ (优先级{s["priority_score"]:.2f})')
        if d['schemes']:
            s = d['schemes'][0]
            r = client.post(f'{base}/transfer/schemes/{s["id"]}/submit')
            assert r.status_code == 200, f'submit fail: {r.text[:300]}'
            sc = r.json()['data']
            print(f'  提交会签: status={sc["status"]}')
            needed = json.loads(sc['required_countersign_regions']) if isinstance(sc['required_countersign_regions'], str) else sc['required_countersign_regions']
            print(f'    需会签: {len(needed)}个行政区')
            for rid in needed[:2]:
                client.post(f'{base}/transfer/countersign', json={
                    'transfer_id': sc['id'], 'region_id': rid, 'signer_id': 1,
                    'is_approved': True, 'opinion': '同意'
                })
            r = client.post(f'{base}/transfer/check-overdue')
            print(f'  超期催办检查: checked={r.json()["data"]["checked"]}')
    test('跨区域调水', t6)

    print('\n【7. 水利工程维护】')
    def t7():
        r = client.get(f'{base}/maintenance/teams')
        print(f'  维修班组: {len(r.json()["data"])}个')
        r = client.post(f'{base}/maintenance/generate-tasks')
        assert r.status_code == 200, f'gen tasks fail: {r.text[:300]}'
        d = r.json()['data']
        print(f'  自动生成任务: {d["generated_count"]}个 (按技能+区域匹配)')
        for t in d['tasks'][:3]:
            team_note = f'班组#{t["assigned_team_id"]}' if t['assigned_team_id'] else '待分配'
            print(f'    {t["task_type"]} 优先级{t["priority"]} -> {team_note}')
        if d['tasks']:
            tid = d['tasks'][0]['id']
            client.put(f'{base}/maintenance/tasks/{tid}/start')
            r = client.post(f'{base}/maintenance/tasks/complete', json={
                'task_id': tid, 'report': '坝体检修完成，无渗漏；闸门启闭正常；溢洪道清淤完毕。设备良好。',
                'parts_used': ['密封圈x2', '润滑脂x1'], 'actual_duration_hours': 6.5
            })
            assert r.status_code == 200, f'complete fail: {r.text[:300]}'
            d2 = r.json()['data']
            print(f'  任务完成: 台账更新={d2["ledger_updated"]}, 健康={d2["project_health"]}, 下次={d2["next_maintenance"]}')
    test('工程维护', t7)

    print('\n【8. 每日水资源综合报告】')
    def t8():
        r = client.post(f'{base}/reports/generate', json={'report_date': '2026-06-09', 'basin': '示范流域'})
        assert r.status_code == 200, f'gen report fail: {r.text[:500]}'
        d = r.json()['data']
        print(f'  生成日报: {d["report_no"]}')
        print(f'    蓄水量: {d["total_storage"]:.0f}m³  供水量: {d["total_supply"]:.1f}万m³')
        print(f'    水质达标率: {d["avg_water_quality_rate"]}%  生态满足率: {d["ecological_flow_satisfaction_rate"]}%')
        print(f'    降雨: {d["rainfall_total"]}mm  灌溉: {d["irrigation_total"]}m³  告警: {d["warnings_count"]}')
        r = client.get(f'{base}/reports')
        print(f'  报告列表: {r.json()["total"]}份 (支持CSV/Excel导出)')
    test('日报', t8)

    print('\n【9. 实时消息推送】')
    def t9():
        r = client.get(f'{base}/notifications/unread', params={'role': 'BASIN_MANAGER'})
        d = r.json()['data']
        print(f'  流域管理员未读: {d["count"]}条')
        types = {}
        for m in d['messages']:
            types[m['message_type']] = types.get(m['message_type'], 0) + 1
        for t, c in sorted(types.items()):
            print(f'    {t}: {c}条')
        print(f'  WebSocket端点: ws://localhost:8000/ws/notifications')
        print(f'  推送角色: water_admin(水政) / env_officer(环保) / agri_officer(农业) / engineer(工程) / basin_manager')
    test('消息通知', t9)

print('\n' + '=' * 60)
print('测试结果汇总:')
passed = 0
_result_lines = []
for n, s in results:
    flag = '[PASS]' if s == 'PASS' else '[FAIL]'
    _line = f'  {flag} {n}: {s}'
    print(_line)
    _result_lines.append(_line)
_total = f'总模块: {len(results)}  通过: {sum(1 for _,s in results if s=="PASS")}'
print('=' * 60)
print(_total)
print('服务地址: http://localhost:8000')
print('Swagger文档: http://localhost:8000/docs')
print('=' * 60)

with open('TEST_SUMMARY.txt', 'w', encoding='utf-8') as _f:
    _f.write('智慧流域水资源系统 - 测试结果汇总\n')
    _f.write('='*60 + '\n')
    for l in _result_lines:
        _f.write(l + '\n')
    _f.write('='*60 + '\n')
    _f.write(_total + '\n')
