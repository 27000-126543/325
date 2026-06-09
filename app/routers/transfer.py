from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, date, timedelta
import uuid
import json

from app.database import get_db
from app.models import (
    AdministrativeRegion, WaterPipeline, CrossRegionTransfer,
    TransferStatus, CountersignRecord
)
from app.schemas import (
    RegionOut, TransferSchemeOut, CountersignRequest,
    GenerateTransferRequest, ResponseModel, PaginatedResponse
)
from app.services import NotificationService

router = APIRouter(prefix="/api/v1/transfer", tags=["6.CrossRegionTransfer"])


def generate_scheme_no():
    return f"TR{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"


def _normalize_json_list(val):
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    return []


def _normalize_scheme(s: CrossRegionTransfer) -> CrossRegionTransfer:
    s.required_countersign_regions = _normalize_json_list(s.required_countersign_regions)
    s.signed_regions = _normalize_json_list(s.signed_regions)
    return s


@router.post("/regions", response_model=ResponseModel, summary="创建行政区数据")
def create_region(
    name: str, code: str, basin: str,
    population: Optional[float] = None, gdp: Optional[float] = None,
    annual_water_demand: Optional[float] = None,
    current_supply_capacity: Optional[float] = None,
    manager_id: Optional[int] = None, db: Session = Depends(get_db)
):
    existing = db.query(AdministrativeRegion).filter(AdministrativeRegion.code == code).first()
    if existing:
        raise HTTPException(400, "行政区编码已存在")
    r = AdministrativeRegion(
        name=name, code=code, basin=basin, population=population, gdp=gdp,
        annual_water_demand=annual_water_demand,
        current_supply_capacity=current_supply_capacity, manager_id=manager_id
    )
    if annual_water_demand and annual_water_demand > 0 and current_supply_capacity is not None:
        r.water_shortage_index = round(
            max(0, (annual_water_demand - current_supply_capacity) / annual_water_demand), 4
        )
    db.add(r)
    db.commit()
    db.refresh(r)
    return ResponseModel(data=RegionOut.model_validate(r).model_dump())


@router.get("/regions", response_model=PaginatedResponse, summary="行政区列表")
def list_regions(
    basin: Optional[str] = None, shortage_min: Optional[float] = None,
    page: int = 1, page_size: int = 50, db: Session = Depends(get_db)
):
    q = db.query(AdministrativeRegion)
    if basin:
        q = q.filter(AdministrativeRegion.basin == basin)
    if shortage_min is not None:
        q = q.filter(AdministrativeRegion.water_shortage_index >= shortage_min)
    total = q.count()
    items = q.order_by(AdministrativeRegion.water_shortage_index.desc()).offset((page-1)*page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        data=[RegionOut.model_validate(i) for i in items]
    )


@router.post("/pipelines", response_model=ResponseModel, summary="创建输水管道")
def create_pipeline(
    name: str, code: str, from_region_id: int, to_region_id: int,
    design_capacity: float, length_km: Optional[float] = None,
    db: Session = Depends(get_db)
):
    existing = db.query(WaterPipeline).filter(WaterPipeline.code == code).first()
    if existing:
        raise HTTPException(400, "管道编码已存在")
    p = WaterPipeline(
        name=name, code=code, from_region_id=from_region_id,
        to_region_id=to_region_id, design_capacity=design_capacity, length_km=length_km
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return ResponseModel(data={"id": p.id, "name": p.name, "code": p.code})


@router.get("/pipelines", response_model=ResponseModel, summary="输水管道列表")
def list_pipelines(from_region_id: Optional[int] = None, to_region_id: Optional[int] = None,
                   db: Session = Depends(get_db)):
    q = db.query(WaterPipeline)
    if from_region_id:
        q = q.filter(WaterPipeline.from_region_id == from_region_id)
    if to_region_id:
        q = q.filter(WaterPipeline.to_region_id == to_region_id)
    items = q.all()
    return ResponseModel(data=[{
        "id": i.id, "name": i.name, "code": i.code,
        "from_region_id": i.from_region_id, "to_region_id": i.to_region_id,
        "design_capacity": i.design_capacity, "current_utilization": i.current_utilization,
        "length_km": i.length_km, "status": i.status
    } for i in items])


@router.post("/generate-schemes", response_model=ResponseModel, summary="根据缺水指数和管道容量自动生成调水方案")
def generate_transfer_schemes(request: GenerateTransferRequest, db: Session = Depends(get_db)):
    regions = db.query(AdministrativeRegion).filter(
        AdministrativeRegion.basin == request.basin
    ).all()
    if not regions:
        raise HTTPException(404, "该流域无行政区数据")

    shortage_regions = sorted(
        [r for r in regions if r.water_shortage_index > 0.1],
        key=lambda x: x.water_shortage_index, reverse=True
    )
    surplus_regions = sorted(
        [r for r in regions if r.water_shortage_index < 0.2],
        key=lambda x: x.water_shortage_index
    )

    schemes = []

    for to_r in shortage_regions:
        deficit = 0
        if to_r.annual_water_demand and to_r.current_supply_capacity is not None:
            deficit = max(0, to_r.annual_water_demand - to_r.current_supply_capacity) * 0.3

        if request.target_volume:
            deficit = max(deficit, request.target_volume)

        if deficit <= 0:
            continue

        for from_r in surplus_regions:
            if from_r.id == to_r.id:
                continue

            pipeline = db.query(WaterPipeline).filter(
                WaterPipeline.from_region_id == from_r.id,
                WaterPipeline.to_region_id == to_r.id,
                WaterPipeline.status == "operational"
            ).first()

            if not pipeline:
                continue

            available = pipeline.design_capacity * (1 - pipeline.current_utilization) * 0.8
            surplus = 0
            if from_r.current_supply_capacity and from_r.annual_water_demand:
                surplus = max(0, from_r.current_supply_capacity - from_r.annual_water_demand * 0.8)

            transfer_vol = round(min(deficit, available, surplus), 2)
            if transfer_vol <= 0:
                continue

            priority = (
                to_r.water_shortage_index * 0.5
                + (1 - from_r.water_shortage_index) * 0.3
                + (transfer_vol / max(deficit, 1)) * 0.2
            )

            required_signs = [from_r.id, to_r.id]
            basin_regions = [r.id for r in regions if r.water_shortage_index > 0.3]
            for br in basin_regions:
                if br not in required_signs:
                    required_signs.append(br)

            scheme = CrossRegionTransfer(
                scheme_no=generate_scheme_no(),
                scheme_name=f"{from_r.name}→{to_r.name} 调水方案",
                from_region_id=from_r.id,
                to_region_id=to_r.id,
                pipeline_id=pipeline.id,
                transfer_volume=transfer_vol,
                estimated_duration_days=max(1, int(transfer_vol / (pipeline.design_capacity * 0.05))),
                water_shortage_index=to_r.water_shortage_index,
                priority_score=round(priority, 4),
                status=TransferStatus.DRAFT,
                required_countersign_regions=required_signs,
                signed_regions=[],
                overdue_deadline=datetime.utcnow() + timedelta(days=3)
            )
            db.add(scheme)
            schemes.append(scheme)
            deficit -= transfer_vol

            if deficit <= 0:
                break

    db.commit()
    for s in schemes:
        db.refresh(s)
        _normalize_scheme(s)

    schemes.sort(key=lambda x: x.priority_score, reverse=True)

    return ResponseModel(data={
        "basin": request.basin,
        "shortage_count": len(shortage_regions),
        "generated_count": len(schemes),
        "schemes": [TransferSchemeOut.model_validate(s).model_dump() for s in schemes]
    })


@router.post("/schemes/{scheme_id}/submit", response_model=ResponseModel, summary="提交方案进入会签流程")
def submit_scheme_for_countersign(scheme_id: int, creator_id: Optional[int] = None,
                                  db: Session = Depends(get_db)):
    scheme = db.query(CrossRegionTransfer).filter(
        CrossRegionTransfer.id == scheme_id
    ).first()
    if not scheme:
        raise HTTPException(404, "方案不存在")
    if scheme.status != TransferStatus.DRAFT:
        raise HTTPException(400, "方案状态不正确")

    scheme.status = TransferStatus.COUNTERSIGNING
    scheme.created_by = creator_id
    scheme.created_at = datetime.utcnow()
    scheme.overdue_deadline = datetime.utcnow() + timedelta(days=3)
    scheme.signed_regions = []

    db.commit()
    db.refresh(scheme)
    _normalize_scheme(scheme)

    NotificationService.notify_transfer(
        db, scheme.id,
        f"调水方案进入会签: {scheme.scheme_name or scheme.scheme_no}",
        f"调水量:{scheme.transfer_volume}m³，请相关行政区于3天内完成会签。"
    )

    return ResponseModel(data=TransferSchemeOut.model_validate(scheme).model_dump())


@router.get("/schemes", response_model=PaginatedResponse, summary="调水方案列表")
def list_schemes(
    status: Optional[TransferStatus] = None,
    from_region_id: Optional[int] = None, to_region_id: Optional[int] = None,
    page: int = 1, page_size: int = 20, db: Session = Depends(get_db)
):
    q = db.query(CrossRegionTransfer)
    if status:
        q = q.filter(CrossRegionTransfer.status == status)
    if from_region_id:
        q = q.filter(CrossRegionTransfer.from_region_id == from_region_id)
    if to_region_id:
        q = q.filter(CrossRegionTransfer.to_region_id == to_region_id)
    total = q.count()
    items = q.order_by(CrossRegionTransfer.priority_score.desc(), CrossRegionTransfer.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    for i in items:
        _normalize_scheme(i)
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        data=[TransferSchemeOut.model_validate(i) for i in items]
    )


@router.post("/countersign", response_model=ResponseModel, summary="行政区会签/审批")
def submit_countersign(data: CountersignRequest, db: Session = Depends(get_db)):
    scheme = db.query(CrossRegionTransfer).filter(
        CrossRegionTransfer.id == data.transfer_id
    ).first()
    if not scheme:
        raise HTTPException(404, "方案不存在")
    if scheme.status != TransferStatus.COUNTERSIGNING:
        raise HTTPException(400, "方案不在会签状态")

    required = _normalize_json_list(scheme.required_countersign_regions)
    if data.region_id not in required:
        raise HTTPException(400, "该行政区无需会签")

    signed = _normalize_json_list(scheme.signed_regions)
    if data.region_id in signed:
        raise HTTPException(400, "该行政区已会签")

    record = CountersignRecord(
        transfer_id=data.transfer_id, region_id=data.region_id,
        signer_id=data.signer_id, is_approved=data.is_approved,
        opinion=data.opinion
    )
    db.add(record)

    if not data.is_approved:
        scheme.status = TransferStatus.REJECTED
        db.commit()
        NotificationService.notify_transfer(
            db, scheme.id,
            f"调水方案被拒绝: {scheme.scheme_no}",
            f"行政区{data.region_id}拒绝。意见: {data.opinion or '无'}"
        )
        return ResponseModel(data={"approved": False, "reason": data.opinion or "被行政区拒绝"})

    signed.append(data.region_id)
    scheme.signed_regions = list(signed)  # 用新list对象触发SQLAlchemy变更检测

    if set(signed) >= set(required):
        scheme.status = TransferStatus.APPROVED

        pipeline = db.query(WaterPipeline).filter(
            WaterPipeline.id == scheme.pipeline_id
        ).first()
        if pipeline and pipeline.design_capacity > 0:
            pipeline.current_utilization = min(
                1.0, pipeline.current_utilization + scheme.transfer_volume / pipeline.design_capacity
            )

        NotificationService.notify_transfer(
            db, scheme.id,
            f"调水方案已全部会签通过: {scheme.scheme_no}",
            f"调水量:{scheme.transfer_volume}m³，方案已生效，可执行。"
        )
    else:
        remaining = set(required) - set(signed)
        NotificationService.notify_transfer(
            db, scheme.id,
            f"调水方案会签进展: {scheme.scheme_no}",
            f"已完成{len(signed)}/{len(required)}，等待行政区: {list(remaining)}"
        )

    db.commit()
    db.refresh(scheme)
    _normalize_scheme(scheme)

    return ResponseModel(data={
        "scheme": TransferSchemeOut.model_validate(scheme).model_dump(),
        "signed_count": len(signed),
        "total_required": len(required),
        "remaining_regions": list(set(required) - set(signed))
    })


@router.post("/schemes/check-overdue", response_model=ResponseModel, summary="检查并催办超期会签方案（定时任务）")
def check_overdue_schemes(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    overdue = db.query(CrossRegionTransfer).filter(
        CrossRegionTransfer.status == TransferStatus.COUNTERSIGNING,
        CrossRegionTransfer.overdue_deadline <= now
    ).all()

    reminded = 0
    for s in overdue:
        signed = _normalize_json_list(s.signed_regions)
        required = _normalize_json_list(s.required_countersign_regions)
        remaining = set(required) - set(signed)

        if s.last_reminder_at and (now - s.last_reminder_at) < timedelta(hours=6):
            continue

        s.last_reminder_at = now
        reminded += 1
        NotificationService.notify_transfer(
            db, s.id,
            f"【催办】调水方案会签超时: {s.scheme_no}",
            f"方案已超期，仍有{len(remaining)}个行政区({list(remaining)})未会签，请立即处理！",
            is_reminder=True
        )

        if s.overdue_deadline + timedelta(days=1) <= now:
            s.status = TransferStatus.OVERDUE

    db.commit()
    return ResponseModel(data={"checked": len(overdue), "reminded": reminded})


@router.put("/schemes/{scheme_id}/execute", response_model=ResponseModel, summary="启动/完成调水执行")
def update_scheme_execution(scheme_id: int, action: str = Query(..., description="start/complete"),
                            db: Session = Depends(get_db)):
    scheme = db.query(CrossRegionTransfer).filter(
        CrossRegionTransfer.id == scheme_id
    ).first()
    if not scheme:
        raise HTTPException(404, "方案不存在")

    if action == "start":
        if scheme.status != TransferStatus.APPROVED:
            raise HTTPException(400, "方案未审批通过")
        scheme.status = TransferStatus.EXECUTING
        scheme.execution_start = datetime.utcnow()
    elif action == "complete":
        if scheme.status != TransferStatus.EXECUTING:
            raise HTTPException(400, "方案未在执行中")
        scheme.status = TransferStatus.COMPLETED
        scheme.execution_end = datetime.utcnow()
    else:
        raise HTTPException(400, "action参数无效")

    db.commit()
    db.refresh(scheme)
    _normalize_scheme(scheme)
    return ResponseModel(data=TransferSchemeOut.model_validate(scheme).model_dump())


@router.get("/countersign-records/{transfer_id}", response_model=ResponseModel, summary="查询会签记录")
def get_countersign_records(transfer_id: int, db: Session = Depends(get_db)):
    records = db.query(CountersignRecord).filter(
        CountersignRecord.transfer_id == transfer_id
    ).all()
    return ResponseModel(data=[{
        "region_id": r.region_id, "signer_id": r.signer_id,
        "is_approved": r.is_approved, "opinion": r.opinion, "signed_at": r.signed_at
    } for r in records])
