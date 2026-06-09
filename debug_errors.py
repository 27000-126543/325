from fastapi.testclient import TestClient
import traceback
import sys
sys.path.insert(0, '.')

from app.main import app

with TestClient(app) as client:
    # 触发lifespan启动
    r = client.get('/api/v1/health')
    print('health:', r.status_code)

    print()
    print('=== 1. smart-dispatch ===')
    try:
        r = client.post('/api/v1/dispatch/smart-calculate', json={'basin': '示范流域', 'forecast_hours': 72})
        print('status:', r.status_code)
        if r.status_code != 200:
            print(r.text)
        else:
            print(r.json())
    except Exception:
        traceback.print_exc()

    print()
    print('=== 2. irrigation application ===')
    try:
        r = client.post('/api/v1/irrigation/applications', json={
            'applicant_id': 7, 'region': '东区', 'crop_type': 'rice',
            'planting_area': 500.0, 'requested_amount': 150000.0,
            'start_date': '2026-06-10', 'end_date': '2026-06-20'
        })
        print('status:', r.status_code)
        if r.status_code != 200:
            print(r.text[:3000])
        else:
            d = r.json()
            print('code:', d.get('code'))
            print('application_no:', d.get('data', {}).get('application', {}).get('application_no'))
    except Exception:
        traceback.print_exc()

print()
print('=== 3. 检查生态监测断面创建状态 ===')
from app.database import SessionLocal
from app import models
db = SessionLocal()
monitors = db.query(models.EcologicalFlowMonitor).all()
print(f'Monitors count: {len(monitors)}')
for m in monitors:
    print(f'  - id={m.id} name={m.section_name} code={m.section_code}')

wr = db.query(models.WaterRight).filter(models.WaterRight.right_code == 'WR001').first()
print(f'WaterRight WR001: user_id={wr.user_id if wr else None} remaining={wr.remaining_amount if wr else None}')

farmer1 = db.query(models.User).filter(models.User.username == 'farmer1').first()
print(f'farmer1 id: {farmer1.id if farmer1 else None}')

rsv_a = db.query(models.Reservoir).filter(models.Reservoir.code == 'RSV001').first()
print(f'RSV001 id: {rsv_a.id if rsv_a else None}')

admin = db.query(models.User).filter(models.User.role == 'ADMIN').first()
print(f'admin id: {admin.id if admin else None}')
db.close()
