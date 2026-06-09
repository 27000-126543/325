from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import uuid
import math

from app.database import get_db
from app.models import (
    WaterQualityStation, WaterQualityData, PollutionOutlet,
    TraceabilityWorkOrder, WorkOrderStatus, HydrologicalStation,
    RealTimeData, UserRole
)
from app.schemas import (
    WaterQualityDataUpload, WaterQualityDataOut, WorkOrderOut,
    WorkOrderInvestigation, ResponseModel, PaginatedResponse
)
from app.config import settings
from app.services import NotificationService

router = APIRouter(prefix="/api/v1/quality", tags=["3.WaterQuality"])


def generate_work_order_no():
    return f"WO{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"


@router.post("/stations", response_model=ResponseModel, summary="创建水质监测站")
def create_station(
    name: str, code: str, basin: str, region: Optional[str] = None,
    river_section: Optional[str] = None, latitude: Optional[float] = None,
    longitude: Optional[float] = None, db: Session = Depends(get_db)
):
    existing = db.query(WaterQualityStation).filter(WaterQualityStation.code == code).first()
    if existing:
        raise HTTPException(400, "监测站编码已存在")
    s = WaterQualityStation(
        name=name, code=code, basin=basin, region=region,
        river_section=river_section, latitude=latitude, longitude=longitude
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return ResponseModel(data={"id": s.id, "name": s.name, "code": s.code})


@router.post("/outlets", response_model=ResponseModel, summary="创建排污口")
def create_outlet(
    name: str, code: str, enterprise_name: Optional[str] = None,
    region: Optional[str] = None, river_bank: Optional[str] = None,
    latitude: Optional[float] = None, longitude: Optional[float] = None,
    design_discharge: Optional[float] = None, permit_cod_limit: float = 100.0,
    permit_nh3n_limit: float = 15.0, outlet_type: str = "industrial",
    db: Session = Depends(get_db)
):
    existing = db.query(PollutionOutlet).filter(PollutionOutlet.code == code).first()
    if existing:
        raise HTTPException(400, "排污口编码已存在")
    o = PollutionOutlet(
        name=name, code=code, enterprise_name=enterprise_name, region=region,
        river_bank=river_bank, latitude=latitude, longitude=longitude,
        design_discharge=design_discharge, permit_cod_limit=permit_cod_limit,
        permit_nh3n_limit=permit_nh3n_limit, outlet_type=outlet_type
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    return ResponseModel(data={"id": o.id, "name": o.name, "code": o.code})


@router.post("/data/upload", response_model=ResponseModel, summary="上传水质监测数据（超标自动触发溯源工单）")
def upload_quality_data(data: WaterQualityDataUpload, db: Session = Depends(get_db)):
    station = db.query(WaterQualityStation).filter(
        WaterQualityStation.id == data.station_id
    ).first()
    if not station:
        raise HTTPException(404, "监测站不存在")

    over_limit_items = {}
    if data.cod is not None and data.cod > settings.WATER_QUALITY_COD_LIMIT:
        over_limit_items["cod"] = {"value": data.cod, "limit": settings.WATER_QUALITY_COD_LIMIT,
                                     "ratio": round(data.cod / settings.WATER_QUALITY_COD_LIMIT, 2)}
    if data.nh3n is not None and data.nh3n > settings.WATER_QUALITY_NH3N_LIMIT:
        over_limit_items["nh3n"] = {"value": data.nh3n, "limit": settings.WATER_QUALITY_NH3N_LIMIT,
                                      "ratio": round(data.nh3n / settings.WATER_QUALITY_NH3N_LIMIT, 2)}

    qd = WaterQualityData(
        **data.model_dump(),
        is_over_limit=len(over_limit_items) > 0,
        over_limit_items=over_limit_items if over_limit_items else None
    )
    db.add(qd)
    db.commit()
    db.refresh(qd)

    work_order = None
    if qd.is_over_limit:
        work_order = _generate_traceability_work_order(db, station, qd, over_limit_items)

    return ResponseModel(data={
        "quality_data": WaterQualityDataOut.model_validate(qd).model_dump(),
        "work_order": WorkOrderOut.model_validate(work_order).model_dump() if work_order else None
    })


def _generate_traceability_work_order(
    db: Session, station: WaterQualityStation, qd: WaterQualityData,
    over_limit_items: Dict
) -> TraceabilityWorkOrder:
    since = datetime.utcnow() - timedelta(hours=6)
    flow_data = db.query(RealTimeData).filter(
        RealTimeData.station_id.in_(
            db.query(HydrologicalStation.id).filter(
                HydrologicalStation.basin == station.basin
            )
        ),
        RealTimeData.flow_rate.isnot(None),
        RealTimeData.timestamp >= since
    ).order_by(RealTimeData.timestamp.desc()).first()

    avg_flow = flow_data.flow_rate if flow_data else 5.0
    flow_direction = "自西向东" if avg_flow >= 0 else "自东向西"
    dispersion_km = round(max(2.0, math.sqrt(avg_flow) * 1.5), 1)
    hydro_analysis = (
        f"断面近6小时平均流速{avg_flow}m³/s，水流方向{flow_direction}，"
        f"污染物扩散范围约上游{dispersion_km}km。结合超标倍数，溯源重点在断面上游{dispersion_km}km范围内。"
    )

    region = station.region or station.basin
    outlets = db.query(PollutionOutlet).filter(
        (PollutionOutlet.region == region) | (PollutionOutlet.region.like(f"%{region}%"))
    ).all()

    suggested_areas = []
    if station.latitude and station.longitude:
        suggested_areas.append({
            "area_name": f"监测断面上游{dispersion_km}km核心排查区",
            "center_lat": station.latitude,
            "center_lng": station.longitude,
            "radius_m": dispersion_km * 1000,
            "priority": "high"
        })

    scored_outlets = []
    for o in outlets:
        score = 0
        if o.latitude and station.latitude and o.longitude and station.longitude:
            dist = math.sqrt((o.latitude - station.latitude) ** 2 +
                           (o.longitude - station.longitude) ** 2)
            dist_km = dist * 111
            if dist_km <= dispersion_km:
                score += 50
            elif dist_km <= dispersion_km * 2:
                score += 20
        if o.design_discharge:
            score += min(20, o.design_discharge / 5)
        if o.outlet_type == "industrial":
            score += 15
        elif o.outlet_type == "domestic":
            score += 10
        scored_outlets.append({
            "outlet_id": o.id, "name": o.name, "code": o.code,
            "enterprise_name": o.enterprise_name, "score": score,
            "region": o.region, "outlet_type": o.outlet_type
        })
    scored_outlets.sort(key=lambda x: x["score"], reverse=True)
    priority_outlets = scored_outlets[:10]

    total_ratio = sum(v["ratio"] for v in over_limit_items.values())
    penalty_base = total_ratio * 5000
    if total_ratio >= 5:
        severity = "严重超标"
        penalty_suggestion = (
            f"超标项目: {', '.join(over_limit_items.keys())}，综合超标倍数{round(total_ratio,1)}倍，"
            f"属{severity}。建议：1) 责令立即停产整改；2) 罚款人民币{round(penalty_base, 2)}-{round(penalty_base*3,2)}元；"
            f"3) 约谈企业负责人；4) 纳入重点监管名录，加密监测频次至每日1次。"
        )
    elif total_ratio >= 2:
        severity = "中度超标"
        penalty_suggestion = (
            f"超标项目: {', '.join(over_limit_items.keys())}，综合超标倍数{round(total_ratio,1)}倍，"
            f"属{severity}。建议：1) 限期7日内整改；2) 罚款人民币{round(penalty_base,2)}-{round(penalty_base*2,2)}元；"
            f"3) 增加监测频次至每周3次。"
        )
    else:
        severity = "轻度超标"
        penalty_suggestion = (
            f"超标项目: {', '.join(over_limit_items.keys())}，综合超标倍数{round(total_ratio,1)}倍，"
            f"属{severity}。建议：1) 责令书面检查并提交整改方案；2) 罚款人民币{round(penalty_base,2)}元；"
            f"3) 增加监测频次至每周1次。"
        )

    wo = TraceabilityWorkOrder(
        work_order_no=generate_work_order_no(),
        station_id=station.id,
        quality_data_id=qd.id,
        over_limit_items=over_limit_items,
        hydrological_analysis=hydro_analysis,
        suggested_investigation_areas=suggested_areas if suggested_areas else None,
        priority_outlets=priority_outlets if priority_outlets else None,
        status=WorkOrderStatus.CREATED,
        penalty_suggestion=penalty_suggestion
    )
    db.add(wo)
    db.commit()
    db.refresh(wo)

    NotificationService.notify_water_quality(
        db, wo.id,
        f"水质超标告警工单: {wo.work_order_no}",
        f"监测站[{station.name}] 超标项: {', '.join(over_limit_items.keys())} "
        f"综合超标{round(total_ratio,1)}倍。{severity}，请立即排查。"
    )

    return wo


@router.get("/data", response_model=PaginatedResponse, summary="水质数据列表")
def list_quality_data(
    station_id: Optional[int] = None, is_over_limit: Optional[bool] = None,
    start_time: Optional[datetime] = None, end_time: Optional[datetime] = None,
    page: int = 1, page_size: int = 20, db: Session = Depends(get_db)
):
    q = db.query(WaterQualityData)
    if station_id:
        q = q.filter(WaterQualityData.station_id == station_id)
    if is_over_limit is not None:
        q = q.filter(WaterQualityData.is_over_limit == is_over_limit)
    if start_time:
        q = q.filter(WaterQualityData.measured_at >= start_time)
    if end_time:
        q = q.filter(WaterQualityData.measured_at <= end_time)
    total = q.count()
    items = q.order_by(WaterQualityData.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        data=[WaterQualityDataOut.model_validate(i) for i in items]
    )


@router.get("/work-orders", response_model=PaginatedResponse, summary="溯源工单列表")
def list_work_orders(
    status: Optional[WorkOrderStatus] = None, station_id: Optional[int] = None,
    page: int = 1, page_size: int = 20, db: Session = Depends(get_db)
):
    q = db.query(TraceabilityWorkOrder)
    if status:
        q = q.filter(TraceabilityWorkOrder.status == status)
    if station_id:
        q = q.filter(TraceabilityWorkOrder.station_id == station_id)
    total = q.count()
    items = q.order_by(TraceabilityWorkOrder.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        data=[WorkOrderOut.model_validate(i) for i in items]
    )


@router.get("/work-orders/{wo_id}", response_model=ResponseModel, summary="溯源工单详情")
def get_work_order_detail(wo_id: int, db: Session = Depends(get_db)):
    wo = db.query(TraceabilityWorkOrder).filter(TraceabilityWorkOrder.id == wo_id).first()
    if not wo:
        raise HTTPException(404, "工单不存在")
    station = db.query(WaterQualityStation).filter(WaterQualityStation.id == wo.station_id).first()
    outlet = None
    if wo.confirmed_outlet_id:
        outlet = db.query(PollutionOutlet).filter(PollutionOutlet.id == wo.confirmed_outlet_id).first()

    return ResponseModel(data={
        "work_order": WorkOrderOut.model_validate(wo).model_dump(),
        "station": {"id": station.id, "name": station.name, "region": station.region,
                    "river_section": station.river_section} if station else None,
        "confirmed_outlet": {"id": outlet.id, "name": outlet.name, "code": outlet.code,
                             "enterprise": outlet.enterprise_name} if outlet else None
    })


@router.post("/work-orders/investigate", response_model=ResponseModel, summary="提交排查结果")
def submit_investigation(data: WorkOrderInvestigation, db: Session = Depends(get_db)):
    wo = db.query(TraceabilityWorkOrder).filter(
        TraceabilityWorkOrder.id == data.work_order_id
    ).first()
    if not wo:
        raise HTTPException(404, "工单不存在")

    wo.investigation_result = data.result
    if data.confirmed_outlet_id:
        wo.confirmed_outlet_id = data.confirmed_outlet_id
    if data.penalty_amount:
        wo.penalty_amount = data.penalty_amount
    if data.penalty_suggestion:
        wo.penalty_suggestion = data.penalty_suggestion
    wo.status = WorkOrderStatus.INVESTIGATING

    db.commit()
    db.refresh(wo)

    NotificationService.notify_water_quality(
        db, wo.id, f"工单排查进展: {wo.work_order_no}",
        f"排查结果: {data.result[:100]}"
    )

    return ResponseModel(data=WorkOrderOut.model_validate(wo).model_dump())


@router.put("/work-orders/{wo_id}/confirm", response_model=ResponseModel, summary="确认污染源并推送处罚")
def confirm_pollution_source(
    wo_id: int, outlet_id: int, penalty_amount: float,
    db: Session = Depends(get_db)
):
    wo = db.query(TraceabilityWorkOrder).filter(TraceabilityWorkOrder.id == wo_id).first()
    if not wo:
        raise HTTPException(404, "工单不存在")
    outlet = db.query(PollutionOutlet).filter(PollutionOutlet.id == outlet_id).first()
    if not outlet:
        raise HTTPException(404, "排污口不存在")

    wo.confirmed_outlet_id = outlet_id
    wo.penalty_amount = penalty_amount
    wo.status = WorkOrderStatus.PENALTY_ISSUED

    db.commit()
    db.refresh(wo)

    NotificationService.notify_water_quality(
        db, wo.id,
        f"处罚建议已生成: {wo.work_order_no}",
        f"确认污染源[{outlet.name}]，处罚金额: ¥{penalty_amount:,.2f}，已推送环保部门。"
    )

    return ResponseModel(data={
        "work_order": WorkOrderOut.model_validate(wo).model_dump(),
        "confirmed_outlet": {"id": outlet.id, "name": outlet.name,
                             "enterprise": outlet.enterprise_name},
        "penalty": penalty_amount
    })


@router.put("/work-orders/{wo_id}/close", response_model=ResponseModel, summary="关闭工单")
def close_work_order(wo_id: int, db: Session = Depends(get_db)):
    wo = db.query(TraceabilityWorkOrder).filter(TraceabilityWorkOrder.id == wo_id).first()
    if not wo:
        raise HTTPException(404, "工单不存在")
    wo.status = WorkOrderStatus.CLOSED
    wo.closed_at = datetime.utcnow()
    db.commit()
    return ResponseModel(message="工单已关闭")


@router.get("/outlets", response_model=PaginatedResponse, summary="排污口列表")
def list_outlets(
    region: Optional[str] = None, outlet_type: Optional[str] = None,
    page: int = 1, page_size: int = 50, db: Session = Depends(get_db)
):
    q = db.query(PollutionOutlet)
    if region:
        q = q.filter(PollutionOutlet.region == region)
    if outlet_type:
        q = q.filter(PollutionOutlet.outlet_type == outlet_type)
    total = q.count()
    items = q.offset((page-1)*page_size).limit(page_size).all()
    return PaginatedResponse(total=total, page=page, page_size=page_size, data=[{
        "id": i.id, "name": i.name, "code": i.code, "enterprise_name": i.enterprise_name,
        "region": i.region, "river_bank": i.river_bank, "outlet_type": i.outlet_type,
        "design_discharge": i.design_discharge, "permit_cod_limit": i.permit_cod_limit,
        "latitude": i.latitude, "longitude": i.longitude
    } for i in items])
