from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, date, timedelta
from io import BytesIO
import uuid
import json

from app.database import get_db
from app.models import (
    DailyReport, Reservoir, WaterQualityData, EcologicalFlowMonitor,
    RealTimeData, IrrigationApplication, WaterTradeContract,
    MaintenanceTask, MaintenanceStatus, IrrigationStatus
)
from app.schemas import (
    DailyReportOut, GenerateReportRequest, ResponseModel, PaginatedResponse
)
from app.config import settings
from app.services import NotificationService

router = APIRouter(prefix="/api/v1/reports", tags=["8.DailyReports"])


def generate_report_no():
    return f"DR{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"


@router.post("/generate", response_model=ResponseModel, summary="生成/刷新每日水资源综合报告")
def generate_daily_report(request: GenerateReportRequest, db: Session = Depends(get_db)):
    report_date = request.report_date or date.today()
    basin = request.basin
    basin_filter = lambda q: q.filter(Reservoir.basin == basin) if basin else q

    existing = db.query(DailyReport).filter(
        DailyReport.report_date == report_date
    )
    if basin:
        existing = existing.filter(DailyReport.basin == basin)
    existing = existing.first()

    start_dt = datetime.combine(report_date, datetime.min.time())
    end_dt = start_dt + timedelta(days=1)

    reservoirs = basin_filter(db.query(Reservoir)).all()

    total_storage = sum(r.current_storage or 0 for r in reservoirs)
    total_supply = 0
    reservoir_stats = []
    for r in reservoirs:
        ratio = round((r.current_storage / r.max_capacity * 100), 2) if r.max_capacity > 0 else 0
        daily_out = (r.current_outflow or 0) * 86400 / 10000
        total_supply += daily_out
        reservoir_stats.append({
            "id": r.id, "name": r.name, "code": r.code,
            "current_level": r.current_level, "current_storage": r.current_storage,
            "storage_ratio_percent": ratio,
            "daily_supply_10k_m3": round(daily_out, 2),
            "inflow": r.current_inflow, "outflow": r.current_outflow
        })

    q = db.query(WaterQualityData).filter(
        WaterQualityData.measured_at >= start_dt,
        WaterQualityData.measured_at < end_dt
    )
    quality_data = q.all()
    quality_count = len(quality_data)
    quality_pass = sum(1 for d in quality_data if not d.is_over_limit)
    avg_quality_rate = round((quality_pass / quality_count * 100), 2) if quality_count > 0 else 100.0

    station_quality = {}
    for d in quality_data:
        s = station_quality.setdefault(d.station_id, {"total": 0, "pass": 0})
        s["total"] += 1
        if not d.is_over_limit:
            s["pass"] += 1
    quality_station_stats = [{
        "station_id": sid, "total_samples": v["total"],
        "passed_samples": v["pass"],
        "rate_percent": round(v["pass"] / v["total"] * 100, 2) if v["total"] > 0 else 100
    } for sid, v in station_quality.items()]

    eco_q = db.query(EcologicalFlowMonitor)
    if basin:
        eco_q = eco_q.filter(EcologicalFlowMonitor.basin == basin)
    eco_monitors = eco_q.all()
    eco_count = len(eco_monitors)
    eco_pass = sum(1 for m in eco_monitors if not m.is_below_threshold)
    eco_satisfaction_rate = round((eco_pass / eco_count * 100), 2) if eco_count > 0 else 100.0
    eco_monitor_stats = [{
        "id": m.id, "section": m.section_name,
        "current_flow": m.current_flow,
        "legal_minimum": m.legal_minimum_flow,
        "is_satisfied": not m.is_below_threshold,
        "deficit": max(0, m.legal_minimum_flow - (m.current_flow or 0))
    } for m in eco_monitors]

    rain_q = db.query(RealTimeData).filter(
        RealTimeData.timestamp >= start_dt,
        RealTimeData.timestamp < end_dt,
        RealTimeData.rainfall.isnot(None)
    )
    rain_data = rain_q.all()
    rainfall_total = round(sum(d.rainfall for d in rain_data if d.rainfall), 2)

    irr_q = db.query(IrrigationApplication).filter(
        IrrigationApplication.created_at >= start_dt,
        IrrigationApplication.created_at < end_dt,
        IrrigationApplication.status == IrrigationStatus.APPROVED
    )
    irrigation_total = round(sum(a.approved_amount or 0 for a in irr_q.all()), 2)

    trade_q = db.query(WaterTradeContract).filter(
        WaterTradeContract.approved_at >= start_dt if hasattr(WaterTradeContract, 'approved_at') else True,
        WaterTradeContract.approval_status == "effective"
    )
    trade_volume = round(sum(c.trade_volume for c in trade_q.all()), 2)

    maint_q = db.query(MaintenanceTask).filter(
        MaintenanceTask.status.in_([
            MaintenanceStatus.COMPLETED, MaintenanceStatus.VERIFIED
        ])
    )
    if hasattr(MaintenanceTask, 'complete_time'):
        maint_q = maint_q.filter(MaintenanceTask.complete_time >= start_dt,
                                 MaintenanceTask.complete_time < end_dt)
    maintenance_completed = maint_q.count()

    warnings = (quality_count - quality_pass) + (eco_count - eco_pass)

    summary_parts = [
        f"{report_date.isoformat()}水资源报告：",
        f"总蓄水量{round(total_storage, 2)}万m³，日供水{round(total_supply, 2)}万m³，",
        f"水质达标率{avg_quality_rate}%，生态流量满足率{eco_satisfaction_rate}%，",
        f"降雨量{rainfall_total}mm，灌溉配水{irrigation_total}m³，"
        f"完成维护{maintenance_completed}项，告警{warnings}条。"
    ]

    if existing:
        existing.total_storage = total_storage
        existing.total_supply = round(total_supply, 2)
        existing.reservoir_stats = json.dumps(reservoir_stats)
        existing.avg_water_quality_rate = avg_quality_rate
        existing.quality_station_stats = json.dumps(quality_station_stats)
        existing.ecological_flow_satisfaction_rate = eco_satisfaction_rate
        existing.eco_monitor_stats = json.dumps(eco_monitor_stats)
        existing.rainfall_total = rainfall_total
        existing.irrigation_total = irrigation_total
        existing.trade_volume = trade_volume
        existing.maintenance_completed = maintenance_completed
        existing.warnings_count = warnings
        existing.summary = "".join(summary_parts)
        report = existing
    else:
        report = DailyReport(
            report_no=generate_report_no(),
            report_date=report_date,
            basin=basin,
            total_storage=total_storage,
            total_supply=round(total_supply, 2),
            reservoir_stats=json.dumps(reservoir_stats),
            avg_water_quality_rate=avg_quality_rate,
            quality_station_stats=json.dumps(quality_station_stats),
            ecological_flow_satisfaction_rate=eco_satisfaction_rate,
            eco_monitor_stats=json.dumps(eco_monitor_stats),
            rainfall_total=rainfall_total,
            irrigation_total=irrigation_total,
            trade_volume=trade_volume,
            maintenance_completed=maintenance_completed,
            warnings_count=warnings,
            summary="".join(summary_parts)
        )
        db.add(report)

    db.commit()
    db.refresh(report)

    NotificationService.notify_report(
        db, report.id,
        f"水资源综合报告已生成: {report_date}",
        report.summary or ""
    )

    return ResponseModel(data=DailyReportOut.model_validate(report).model_dump())


@router.get("", response_model=PaginatedResponse, summary="报告列表")
def list_reports(
    basin: Optional[str] = None, start_date: Optional[date] = None,
    end_date: Optional[date] = None, page: int = 1, page_size: int = 30,
    db: Session = Depends(get_db)
):
    q = db.query(DailyReport)
    if basin:
        q = q.filter(DailyReport.basin == basin)
    if start_date:
        q = q.filter(DailyReport.report_date >= start_date)
    if end_date:
        q = q.filter(DailyReport.report_date <= end_date)
    total = q.count()
    items = q.order_by(DailyReport.report_date.desc()).offset((page-1)*page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        data=[DailyReportOut.model_validate(i) for i in items]
    )


@router.get("/{report_id}", response_model=ResponseModel, summary="报告详情")
def get_report_detail(report_id: int, db: Session = Depends(get_db)):
    r = db.query(DailyReport).filter(DailyReport.id == report_id).first()
    if not r:
        raise HTTPException(404, "报告不存在")
    return ResponseModel(data={
        **DailyReportOut.model_validate(r).model_dump(),
        "reservoir_stats_detail": json.loads(r.reservoir_stats) if r.reservoir_stats else [],
        "quality_station_stats_detail": json.loads(r.quality_station_stats) if r.quality_station_stats else [],
        "eco_monitor_stats_detail": json.loads(r.eco_monitor_stats) if r.eco_monitor_stats else []
    })


@router.get("/export/csv", summary="按流域/日期范围导出报告CSV")
def export_reports_csv(
    basin: Optional[str] = Query(None),
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db)
):
    q = db.query(DailyReport).filter(
        DailyReport.report_date >= start_date,
        DailyReport.report_date <= end_date
    )
    if basin:
        q = q.filter(DailyReport.basin == basin)
    items = q.order_by(DailyReport.report_date.asc()).all()

    output = BytesIO()
    header = "报告编号,日期,流域,总蓄水量(m³),日供水量(10k m³),水质达标率(%)," \
             "生态流量满足率(%),降雨量(mm),灌溉配水(m³),水权交易量(m³)," \
             "维护完成数,告警数,摘要\n"
    output.write(header.encode("utf-8-sig"))
    for r in items:
        line = (
            f"{r.report_no},{r.report_date},{r.basin or ''},"
            f"{r.total_storage},{r.total_supply},{r.avg_water_quality_rate},"
            f"{r.ecological_flow_satisfaction_rate},{r.rainfall_total},{r.irrigation_total},"
            f"{r.trade_volume},{r.maintenance_completed},{r.warnings_count},"
            f"\"{(r.summary or '').replace('\"', '\"\"')}\"\n"
        )
        output.write(line.encode("utf-8-sig"))
    output.seek(0)

    filename = f"water_report_{start_date}_{end_date}.csv"
    return StreamingResponse(
        output,
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/export/excel", summary="按流域/日期范围导出报告Excel")
def export_reports_excel(
    basin: Optional[str] = Query(None),
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db)
):
    try:
        from openpyxl import Workbook
    except ImportError:
        raise HTTPException(500, "openpyxl未安装，请先pip install openpyxl")

    q = db.query(DailyReport).filter(
        DailyReport.report_date >= start_date,
        DailyReport.report_date <= end_date
    )
    if basin:
        q = q.filter(DailyReport.basin == basin)
    items = q.order_by(DailyReport.report_date.asc()).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "水资源综合报告"
    headers = ["报告编号", "日期", "流域", "总蓄水量(m³)", "日供水量(万m³)",
               "水质达标率(%)", "生态流量满足率(%)", "降雨量(mm)",
               "灌溉配水(m³)", "水权交易量(m³)", "维护完成数", "告警数", "摘要"]
    ws.append(headers)
    for r in items:
        ws.append([
            r.report_no, str(r.report_date), r.basin or "",
            r.total_storage, r.total_supply, r.avg_water_quality_rate,
            r.ecological_flow_satisfaction_rate, r.rainfall_total,
            r.irrigation_total, r.trade_volume, r.maintenance_completed,
            r.warnings_count, r.summary or ""
        ])

    ws2 = wb.create_sheet("水库统计")
    ws2.append(["日期", "水库ID", "水库名称", "当前水位(m)", "当前蓄水量(m³)",
                "蓄水率(%)", "日供水(万m³)", "入流(m³/s)", "出流(m³/s)"])
    for r in items:
        stats = json.loads(r.reservoir_stats) if r.reservoir_stats else []
        for s in stats:
            ws2.append([
                str(r.report_date), s["id"], s["name"], s["current_level"],
                s["current_storage"], s["storage_ratio_percent"],
                s["daily_supply_10k_m3"], s["inflow"], s["outflow"]
            ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    filename = f"water_report_{start_date}_{end_date}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
