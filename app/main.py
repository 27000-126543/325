from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
from datetime import datetime, date

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.database import engine, Base, SessionLocal
    from app import models
    import asyncio as _asyncio
    from app.services import NotificationService as _NS
    from app.routers.notifications import manager as _ws_manager
    Base.metadata.create_all(bind=engine)
    logger.info("数据库表已初始化")

    try:
        _NS.loop = _asyncio.get_running_loop()
        _NS.manager = _ws_manager
        logger.info("NotificationService已绑定WS事件循环")
    except Exception as _e:
        logger.warning(f"NS ws绑定异常: {_e}")

    def _seed_db():
        import hashlib
        import json as _json
        import datetime as _dt
        from datetime import date as d
        from app.models import UserRole

        db = SessionLocal()
        try:
            admin = db.query(models.User).filter(models.User.username == "admin").first()
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
                db.flush()

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

            if not db.query(models.WaterQualityStation).filter(models.WaterQualityStation.code == "WQS001").first():
                db.add(models.WaterQualityStation(
                    name="国控断面I", code="WQS001", basin="示范流域",
                    region="中区", river_section="干流中游"
                ))

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

            demo_regions = [
                ("示范县A", "REG001", "示范流域", 50, 100, 4000, 4500),
                ("示范县B", "REG002", "示范流域", 40, 80, 5500, 3800),
                ("示范县C", "REG003", "示范流域", 30, 60, 3000, 3500),
            ]
            for name, code, basin, pop, gdp_val, demand, supply in demo_regions:
                if not db.query(models.AdministrativeRegion).filter(models.AdministrativeRegion.code == code).first():
                    ws_idx = max(0, (demand - supply) / demand) if demand > 0 else 0
                    db.add(models.AdministrativeRegion(
                        name=name, code=code, basin=basin, population=pop,
                        gdp=gdp_val, annual_water_demand=demand, current_supply_capacity=supply,
                        water_shortage_index=round(ws_idx, 4)
                    ))

            db.flush()  # 给AdministrativeRegion分配id，后面查reg_a/b/c才能取到

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

            if not db.query(models.WaterProject).filter(models.WaterProject.code == "PRJ001").first():
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

            if not db.query(models.MaintenanceTeam).filter(models.MaintenanceTeam.code == "TEAM001").first():
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

            rsv_a = db.query(models.Reservoir).filter(models.Reservoir.code == "RSV001").first()
            if rsv_a and not db.query(models.EcologicalFlowMonitor).filter(
                models.EcologicalFlowMonitor.section_code == "ECO001"
            ).first():
                db.add(models.EcologicalFlowMonitor(
                    section_name="A坝下生态断面", section_code="ECO001",
                    basin="示范流域", upstream_reservoir_id=rsv_a.id,
                    legal_minimum_flow=10.0, current_flow=12.0,
                    is_below_threshold=False
                ))

            farmer1 = db.query(models.User).filter(models.User.username == "farmer1").first()
            if farmer1 and not db.query(models.WaterRight).filter(models.WaterRight.right_code == "WR001").first():
                db.add(models.WaterRight(
                    right_code="WR001", user_id=farmer1.id, water_source="示范水库A",
                    annual_quota=50000, used_amount=12000, remaining_amount=38000,
                    valid_from=d(date.today().year, 1, 1),
                    valid_to=d(date.today().year, 12, 31),
                    region="东区", approved_by=admin.id if admin else 1
                ))

            db.commit()
            logger.info("示范数据已初始化")
        except Exception as e:
            import traceback as _tb
            _tb.print_exc()
            db.rollback()
            logger.warning(f"初始化示范数据时跳过(可能已存在): {e}")
        finally:
            db.close()

    _seed_db()

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from app.database import SessionLocal as _SL
    from app.routers.ecological import check_all_monitors
    from app.routers.maintenance import generate_due_tasks
    from app.routers.reports import generate_daily_report
    from app.routers.transfer import check_overdue_schemes
    from app.schemas import GenerateReportRequest

    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    def run_eco_check():
        try:
            db = SessionLocal()
            check_all_monitors(db)
            db.close()
            logger.info(f"[{datetime.now()}] 生态流量定时巡检完成")
        except Exception as e:
            logger.error(f"生态流量巡检失败: {e}")

    def run_maintenance_gen():
        try:
            db = SessionLocal()
            generate_due_tasks(db)
            db.close()
            logger.info(f"[{datetime.now()}] 维护任务自动生成完成")
        except Exception as e:
            logger.error(f"维护任务生成失败: {e}")

    def run_daily_report():
        try:
            db = SessionLocal()
            from app import models
            basins = db.query(models.Reservoir.basin).distinct().all()
            basins = [b[0] for b in basins if b[0]]
            generate_daily_report(GenerateReportRequest(report_date=date.today(), basin=None), db)
            for b in basins:
                try:
                    generate_daily_report(GenerateReportRequest(report_date=date.today(), basin=b), db)
                except Exception as e:
                    logger.error(f"生成流域[{b}]日报失败: {e}")
            db.close()
            logger.info(f"[{datetime.now()}] 每日水资源综合报告生成完成")
        except Exception as e:
            logger.error(f"日报生成失败: {e}")

    def run_transfer_reminder():
        try:
            db = SessionLocal()
            check_overdue_schemes(db)
            db.close()
            logger.info(f"[{datetime.now()}] 调水方案超期催办完成")
        except Exception as e:
            logger.error(f"催办失败: {e}")

    scheduler.add_job(run_eco_check, "interval", minutes=15, id="eco_check")
    scheduler.add_job(run_maintenance_gen, CronTrigger(hour=1, minute=0), id="maintenance_gen")
    scheduler.add_job(run_daily_report, CronTrigger(hour=2, minute=30), id="daily_report")
    scheduler.add_job(run_transfer_reminder, "interval", hours=1, id="transfer_reminder")

    scheduler.start()
    logger.info("APScheduler定时任务已启动: 生态巡检(15min)/维护生成(01:00)/日报(02:30)/催办(1h)")

    yield

    scheduler.shutdown()
    logger.info("APScheduler定时任务已停止")


app = FastAPI(
    title="智慧流域水资源综合调度与生态保障系统",
    description="""
    ## 功能模块

    ### 1. 水库水文站与智能调度
    - 水库/水文站/闸站 CRUD
    - 实时水位/流量/雨量上传
    - 降雨预报录入
    - **基于降雨预报和库容的智能调度算法**：自动计算最佳泄洪/蓄水方案，生成并下发调度指令

    ### 2. 农业灌溉用水
    - 水权管理
    - 土壤墒情录入
    - 灌溉申请提交 + **作物/墒情/水权自动校验分配**
    - 超额拒绝并推荐节水方案

    ### 3. 水质监测与溯源
    - 水质站/排污口管理
    - 水质数据上传
    - **COD/氨氮超标自动触发溯源工单**
    - **水文流向分析 + 排污口智能排序推荐重点排查区**
    - **分级处罚建议推送环保部门**

    ### 4. 生态流量监控
    - 监测断面管理
    - 流量上报 + **低于阈值自动调整上游水库下泄**
    - **通知下游取水用户限时调整取水计划**

    ### 5. 水权交易
    - 买卖需求提交
    - **基于历史成交价和供需的智能匹配算法**
    - 自动生成交易合同 + **流域管理机构审批生效**

    ### 6. 跨区域调水
    - 行政区/输水管道管理
    - **基于缺水指数和管道容量自动生成备选方案**
    - **多方会签流程**
    - **超时自动催办**

    ### 7. 水利工程维护
    - 工程/维修班组管理
    - **维护周期到时自动生成保养任务**
    - **按技能和位置智能分配至维修班组**
    - 完成后**自动更新设备台账**

    ### 8. 水资源综合报告
    - **每日自动生成报告**（蓄水量/供水量/水质达标率/生态流量满足率等）
    - **按流域和日期导出CSV/Excel**

    ### 9. WebSocket实时推送
    - 所有调度指令、预警、交易状态实时推送给
      水政(water_admin)、环保(env_officer)、农业(agri_officer)、工程(engineer)管理人员
    """,
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health", tags=["系统"])
def health_check():
    return {"code": 200, "status": "ok", "timestamp": datetime.utcnow().isoformat()}


from app.database import get_db as _get_db

@app.get("/api/v1/stats", tags=["系统"])
def get_system_stats(db=Depends(_get_db)):
    from app import models
    from sqlalchemy import func
    return {
        "code": 200,
        "data": {
            "reservoirs": db.query(func.count(models.Reservoir.id)).scalar(),
            "stations": db.query(func.count(models.HydrologicalStation.id)).scalar(),
            "quality_stations": db.query(func.count(models.WaterQualityStation.id)).scalar(),
            "projects": db.query(func.count(models.WaterProject.id)).scalar(),
            "users": db.query(func.count(models.User.id)).scalar(),
            "pending_dispatches": db.query(models.DispatchInstruction).filter(
                models.DispatchInstruction.status == "pending"
            ).count(),
            "open_trades": db.query(models.WaterTradeOrder).filter(
                models.WaterTradeOrder.status == "open"
            ).count(),
            "pending_countersigns": db.query(models.CrossRegionTransfer).filter(
                models.CrossRegionTransfer.status == "countersigning"
            ).count(),
            "maintenance_in_progress": db.query(models.MaintenanceTask).filter(
                models.MaintenanceTask.status == "in_progress"
            ).count(),
            "eco_warnings": db.query(models.EcologicalFlowMonitor).filter(
                models.EcologicalFlowMonitor.is_below_threshold == True
            ).count(),
            "quality_warnings": db.query(models.WaterQualityData).filter(
                models.WaterQualityData.is_over_limit == True
            ).count(),
        }
    }


from app.routers.dispatch import router as dispatch_router
from app.routers.irrigation import router as irrigation_router
from app.routers.quality import router as quality_router
from app.routers.ecological import router as ecological_router
from app.routers.trade import router as trade_router
from app.routers.transfer import router as transfer_router
from app.routers.maintenance import router as maintenance_router
from app.routers.reports import router as reports_router
from app.routers.notifications import (
    router as notifications_router,
    manager as notification_manager
)

app.include_router(dispatch_router)
app.include_router(irrigation_router)
app.include_router(quality_router)
app.include_router(ecological_router)
app.include_router(trade_router)
app.include_router(transfer_router)
app.include_router(maintenance_router)
app.include_router(reports_router)
app.include_router(notifications_router)
