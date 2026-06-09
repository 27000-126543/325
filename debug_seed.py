import sys, os
sys.path.insert(0, '.')
os.chdir('d:/新项目/325')

# 手动模拟lifespan
from app.database import Base, engine, SessionLocal
from app import models

print('--- 1. create_all ---')
Base.metadata.create_all(bind=engine)
print('tables created.')

print()
print('--- 2. call _seed_db ---')

# 从main.py复制_seed_db逻辑（含import）
import hashlib
from datetime import date
from app.models import UserRole

def d(y, m, day):
    return date(y, m, day)

try:
    db = SessionLocal()
    admin = db.query(models.User).filter(models.User.role == UserRole.ADMIN).first()
    if not admin:
        admin = models.User(
            username="admin",
            password_hash=hashlib.sha256("admin123".encode()).hexdigest(),
            full_name="系统管理员",
            role=UserRole.ADMIN,
            phone="13800000000",
            email="admin@basin.gov.cn",
            organization="流域管理局",
            region="全局"
        )
        db.add(admin)
        print(f'[CREATE] admin added (pending id={admin.id})')
    else:
        print(f'[EXIST] admin id={admin.id}')

    demo_users = [
        ("water_admin", "水政管理员", UserRole.WATER_ADMIN),
        ("env_officer", "环保管理员", UserRole.ENV_OFFICER),
        ("agri_officer", "农业管理员", UserRole.AGRI_OFFICER),
        ("engineer1", "工程管理员", UserRole.ENGINEER),
        ("basin_mgr", "流域管理局长", UserRole.BASIN_MANAGER),
        ("farmer1", "种植户张三", UserRole.WATER_USER),
        ("farmer2", "种植户李四", UserRole.WATER_USER),
    ]
    for uname, fname, role in demo_users:
        if not db.query(models.User).filter(models.User.username == uname).first():
            db.add(models.User(
                username=uname,
                password_hash=hashlib.sha256("123456".encode()).hexdigest(),
                full_name=fname, role=role,
                organization="示范单位", region="示范流域"
            ))
            print(f'[CREATE] user {uname}')

    print()
    print('--- BEFORE COMMIT users: admin.id still?', admin.id)
    db.flush()  # 强制获取id
    print('AFTER FLUSH: admin.id =', admin.id)

    demo_reservoirs = [
        ("示范水库A", "RSV001", "示范流域", "东区", 5000, 120, 100, 50, 100, 10),
        ("示范水库B", "RSV002", "示范流域", "西区", 3000, 110, 95, 45, 80, 8),
        ("示范水库C", "RSV003", "示范流域", "南区", 2000, 105, 90, 40, 60, 5),
    ]
    for name, code, basin, region, max_cap, flood, normal, dead, design, eco in demo_reservoirs:
        if not db.query(models.Reservoir).filter(models.Reservoir.code == code).first():
            r = models.Reservoir(
                name=name, code=code, basin=basin, region=region,
                max_capacity=max_cap, flood_limit_level=flood,
                normal_level=normal, dead_level=dead,
                design_discharge=design, downstream_eco_threshold=eco,
                current_level=normal * 0.8,
                current_storage=max_cap * 0.75,
                current_inflow=30,
                current_outflow=25,
                ecological_release=eco
            )
            db.add(r)
            print(f'[CREATE] reservoir {code}')

    demo_stations = [
        ("水文站甲", "HYD001", "示范流域", "东区", "hydrology", 120, 115, "RSV001"),
        ("水文站乙", "HYD002", "示范流域", "西区", "hydrology", 115, 110, "RSV002"),
        ("雨量站A", "RAIN001", "示范流域", "南区", "rainfall", None, None, None),
    ]
    for name, code, basin, region, stype, warn, guar, rsv in demo_stations:
        if not db.query(models.HydrologicalStation).filter(models.HydrologicalStation.code == code).first():
            rsv_obj = db.query(models.Reservoir).filter(models.Reservoir.code == rsv).first()
            db.add(models.HydrologicalStation(
                name=name, code=code, basin=basin, region=region,
                station_type=stype, warning_level=warn, guarantee_level=guar,
                upstream_reservoir_id=rsv_obj.id if rsv_obj else None
            ))
            print(f'[CREATE] station {code}')

    if not db.query(models.WaterQualityStation).filter(models.WaterQualityStation.code == "WQS001").first():
        db.add(models.WaterQualityStation(
            name="国控断面I", code="WQS001", basin="示范流域",
            region="中区", river_section="干流中游"
        ))
        print('[CREATE] WQS001')

    if not db.query(models.PollutionOutlet).filter(models.PollutionOutlet.code == "PO001").first():
        db.add_all([
            models.PollutionOutlet(name="化工园排污口", code="PO001", enterprise_name="示范化工有限公司",
                                 region="中区上游", river_bank="北岸", outlet_type="industrial",
                                 design_discharge=50, permit_cod_limit=100, permit_nh3n_limit=15),
            models.PollutionOutlet(name="县城污水处理厂", code="PO002", enterprise_name="示范县污水厂",
                                 region="中区", river_bank="南岸", outlet_type="domestic",
                                 design_discharge=30, permit_cod_limit=80, permit_nh3n_limit=10),
            models.PollutionOutlet(name="食品厂排污口", code="PO003", enterprise_name="示范食品有限公司",
                                 region="中区上游", river_bank="北岸", outlet_type="industrial",
                                 design_discharge=20, permit_cod_limit=100, permit_nh3n_limit=15),
        ])
        print('[CREATE] 3 pollution outlets')

    demo_regions = [
        ("示范县A", "REG001", "示范流域", 50, 100, 5000, 4200),
        ("示范县B", "REG002", "示范流域", 40, 80, 4000, 4100),
        ("示范县C", "REG003", "示范流域", 30, 60, 3000, 3200),
    ]
    for name, code, basin, pop, gdp_val, demand, supply in demo_regions:
        if not db.query(models.AdministrativeRegion).filter(models.AdministrativeRegion.code == code).first():
            ws_idx = max(0, (demand - supply) / demand) if demand > 0 else 0
            db.add(models.AdministrativeRegion(
                name=name, code=code, basin=basin, population=pop,
                gdp=gdp_val, annual_water_demand=demand, current_supply_capacity=supply,
                water_shortage_index=round(ws_idx, 4)
            ))
            print(f'[CREATE] region {code}')

    reg_a = db.query(models.AdministrativeRegion).filter(models.AdministrativeRegion.code == "REG001").first()
    reg_b = db.query(models.AdministrativeRegion).filter(models.AdministrativeRegion.code == "REG002").first()
    reg_c = db.query(models.AdministrativeRegion).filter(models.AdministrativeRegion.code == "REG003").first()
    if reg_a and reg_b and not db.query(models.WaterPipeline).filter(models.WaterPipeline.code == "PIPE001").first():
        db.add_all([
            models.WaterPipeline(name="A→B干管", code="PIPE001", from_region_id=reg_a.id,
                                to_region_id=reg_b.id, design_capacity=800, length_km=52),
            models.WaterPipeline(name="C→B干管", code="PIPE002", from_region_id=reg_c.id,
                                to_region_id=reg_b.id, design_capacity=500, length_km=38),
            models.WaterPipeline(name="A→C联络管", code="PIPE003", from_region_id=reg_a.id,
                                to_region_id=reg_c.id, design_capacity=300, length_km=25),
        ])
        print('[CREATE] 3 pipelines')

    if not db.query(models.WaterProject).filter(models.WaterProject.code == "PRJ001").first():
        import datetime as _dt
        db.add_all([
            models.WaterProject(name="示范A大坝", code="PRJ001", project_type="dam",
                                basin="示范流域", region="东区",
                                built_date=d(1990, 6, 1), maintenance_cycle_days=180,
                                next_maintenance_date=date.today(),
                                responsible_team="水工一班"),
            models.WaterProject(name="北干渠", code="PRJ002", project_type="channel",
                                basin="示范流域", region="东区",
                                built_date=d(1985, 3, 15), maintenance_cycle_days=365,
                                next_maintenance_date=date.today() + _dt.timedelta(days=5),
                                responsible_team="渠道养护队"),
            models.WaterProject(name="1号泵站", code="PRJ003", project_type="pumping_station",
                                basin="示范流域", region="中区",
                                built_date=d(2010, 9, 20), maintenance_cycle_days=90,
                                next_maintenance_date=date.today() - _dt.timedelta(days=2),
                                responsible_team="机电维修班"),
            models.WaterProject(name="分水闸", code="PRJ004", project_type="gate",
                                basin="示范流域", region="西区",
                                built_date=d(2000, 5, 10), maintenance_cycle_days=270,
                                next_maintenance_date=date.today(),
                                responsible_team="水工二班"),
        ])
        print('[CREATE] 4 projects')

    if not db.query(models.MaintenanceTeam).filter(models.MaintenanceTeam.code == "TEAM001").first():
        import json as _json
        db.add_all([
            models.MaintenanceTeam(name="水工一班", code="TEAM001", region="东区",
                                   team_leader="王师傅", phone="13800000001", member_count=6,
                                   skills=_json.dumps(["结构检测", "防渗处理", "闸门维护"]),
                                   coverage_area="东区大坝闸站", current_workload=0),
            models.MaintenanceTeam(name="渠道养护队", code="TEAM002", region="东区",
                                   team_leader="李队长", phone="13800000002", member_count=8,
                                   skills=_json.dumps(["清淤疏浚", "衬砌修复", "土工布铺设"]),
                                   coverage_area="东区渠道工程", current_workload=0),
            models.MaintenanceTeam(name="机电维修班", code="TEAM003", region="中区",
                                   team_leader="赵工", phone="13800000003", member_count=4,
                                   skills=_json.dumps(["机电维修", "自动化控制", "液压系统"]),
                                   coverage_area="中区泵站设备", current_workload=20),
            models.MaintenanceTeam(name="水工二班", code="TEAM004", region="西区",
                                   team_leader="孙班长", phone="13800000004", member_count=5,
                                   skills=_json.dumps(["结构检测", "机械维修", "闸门维护"]),
                                   coverage_area="西区闸站工程", current_workload=0),
        ])
        print('[CREATE] 4 maintenance teams')

    print()
    print('--- 关键部分: 创建 ECO001 & WR001 ---')
    rsv_a = db.query(models.Reservoir).filter(models.Reservoir.code == "RSV001").first()
    print(f'rsv_a: {rsv_a} id={rsv_a.id if rsv_a else None}')
    eco_exists = db.query(models.EcologicalFlowMonitor).filter(
        models.EcologicalFlowMonitor.section_code == "ECO001"
    ).first()
    print(f'eco ECO001 exists: {eco_exists}')
    if rsv_a and not eco_exists:
        print('about to create ECO001, upstream_reservoir_id =', rsv_a.id)
        eco = models.EcologicalFlowMonitor(
            section_name="A坝下生态断面", section_code="ECO001",
            basin="示范流域", upstream_reservoir_id=rsv_a.id,
            legal_minimum_flow=10.0, current_flow=12.0,
            is_below_threshold=False
        )
        db.add(eco)
        print('[CREATE] ECO001 added')
    else:
        print(f'SKIP ECO001 (rsv_a?={bool(rsv_a)}, eco_exists?={bool(eco_exists)})')

    farmer1 = db.query(models.User).filter(models.User.username == "farmer1").first()
    print(f'farmer1: {farmer1} id={farmer1.id if farmer1 else None}')
    wr_exists = db.query(models.WaterRight).filter(models.WaterRight.right_code == "WR001").first()
    print(f'WR001 exists: {wr_exists}')
    if farmer1 and not wr_exists:
        print(f'about to create WR001: user_id={farmer1.id}, approved_by={admin.id if admin else 1}')
        wr = models.WaterRight(
            right_code="WR001", user_id=farmer1.id, water_source="示范水库A",
            annual_quota=50000, used_amount=12000, remaining_amount=38000,
            valid_from=d(date.today().year, 1, 1),
            valid_to=d(date.today().year, 12, 31),
            region="东区", approved_by=admin.id if admin else 1
        )
        db.add(wr)
        print('[CREATE] WR001 added')
    else:
        print(f'SKIP WR001 (farmer1?={bool(farmer1)}, wr_exists?={bool(wr_exists)})')

    print()
    print('--- COMMIT ---')
    db.commit()
    print('示范数据已初始化')

except Exception as e:
    import traceback as _tb
    print('!!! EXCEPTION IN SEED !!!')
    _tb.print_exc()
    db.rollback()
finally:
    db.close()

print()
print('--- 3. VERIFY ---')
db = SessionLocal()
monitors = db.query(models.EcologicalFlowMonitor).all()
print(f'EcologicalFlowMonitor count: {len(monitors)}')
for m in monitors:
    print(f'  - id={m.id} name={m.section_name} code={m.section_code} upstream_id={m.upstream_reservoir_id}')

wrs = db.query(models.WaterRight).all()
print(f'WaterRight count: {len(wrs)}')
for w in wrs:
    print(f'  - id={w.id} code={w.right_code} user_id={w.user_id} remaining={w.remaining_amount} approved_by={w.approved_by}')

users = db.query(models.User).count()
print(f'Users count: {users}')
reservoirs = db.query(models.Reservoir).count()
print(f'Reservoirs count: {reservoirs}')
db.close()
