from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, date
import uuid

from app.database import get_db
from app.models import (
    IrrigationApplication, IrrigationStatus, WaterRight,
    SoilMoistureData, CropType, DownstreamWaterUser
)
from app.schemas import (
    IrrigationApplicationCreate, IrrigationApplicationOut,
    IrrigationReview, ResponseModel, PaginatedResponse,
    SoilMoistureCreate, WaterRightCreate, WaterRightOut
)
from app.services import CropWaterRequirement, NotificationService

router = APIRouter(prefix="/api/v1/irrigation", tags=["2.Irrigation"])


def generate_application_no():
    return f"IRR{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"


@router.post("/water-rights", response_model=ResponseModel, summary="创建水权")
def create_water_right(data: WaterRightCreate, db: Session = Depends(get_db)):
    existing = db.query(WaterRight).filter(WaterRight.right_code == data.right_code).first()
    if existing:
        raise HTTPException(400, "水权编码已存在")
    wr = WaterRight(
        **data.model_dump(),
        remaining_amount=data.annual_quota
    )
    db.add(wr)
    db.commit()
    db.refresh(wr)
    return ResponseModel(data=WaterRightOut.model_validate(wr))


@router.get("/water-rights", response_model=PaginatedResponse, summary="水权列表")
def list_water_rights(
    user_id: Optional[int] = None, region: Optional[str] = None,
    page: int = 1, page_size: int = 20, db: Session = Depends(get_db)
):
    q = db.query(WaterRight)
    if user_id:
        q = q.filter(WaterRight.user_id == user_id)
    if region:
        q = q.filter(WaterRight.region == region)
    total = q.count()
    items = q.order_by(WaterRight.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        data=[WaterRightOut.model_validate(i) for i in items]
    )


@router.post("/soil-moisture", response_model=ResponseModel, summary="录入土壤墒情数据")
def add_soil_moisture(data: SoilMoistureCreate, db: Session = Depends(get_db)):
    sm = SoilMoistureData(**data.model_dump())
    db.add(sm)
    db.commit()
    db.refresh(sm)
    return ResponseModel(data={"id": sm.id, "region": sm.region,
                               "moisture_content": sm.moisture_content})


@router.get("/soil-moisture/latest", response_model=ResponseModel, summary="查询区域最新墒情")
def get_latest_moisture(region: str, crop_type: Optional[CropType] = None, db: Session = Depends(get_db)):
    q = db.query(SoilMoistureData).filter(SoilMoistureData.region == region)
    if crop_type:
        q = q.filter(SoilMoistureData.crop_type == crop_type)
    items = q.order_by(SoilMoistureData.measured_at.desc()).limit(10).all()
    return ResponseModel(data=[{
        "id": i.id, "monitoring_point": i.monitoring_point,
        "crop_type": i.crop_type.value if i.crop_type else None,
        "moisture_content": i.moisture_content, "field_capacity": i.field_capacity,
        "measured_at": i.measured_at
    } for i in items])


@router.post("/applications", response_model=ResponseModel, summary="提交灌溉用水申请")
def create_application(data: IrrigationApplicationCreate, db: Session = Depends(get_db)):
    if data.requested_amount <= 0:
        raise HTTPException(400, "申请水量必须大于0")
    if data.planting_area <= 0:
        raise HTTPException(400, "种植面积必须大于0")

    water_right = db.query(WaterRight).filter(
        WaterRight.user_id == data.applicant_id,
        WaterRight.valid_from <= date.today(),
        WaterRight.valid_to >= date.today()
    ).order_by(WaterRight.id.desc()).first()

    remaining = water_right.remaining_amount if water_right else 0

    moisture = None
    if data.soil_moisture is None:
        latest_moisture = db.query(SoilMoistureData).filter(
            SoilMoistureData.region == data.region,
            SoilMoistureData.crop_type == data.crop_type
        ).order_by(SoilMoistureData.measured_at.desc()).first()
        if latest_moisture:
            moisture = latest_moisture.moisture_content
    else:
        moisture = data.soil_moisture

    calc = CropWaterRequirement.calculate_irrigation_need(
        data.crop_type, data.planting_area, moisture
    )

    app = IrrigationApplication(
        **data.model_dump(exclude={"soil_moisture"}),
        application_no=generate_application_no(),
        current_water_right_remaining=remaining,
        status=IrrigationStatus.PENDING,
        soil_moisture=moisture if data.soil_moisture is None else data.soil_moisture
    )
    db.add(app)
    db.commit()
    db.refresh(app)

    NotificationService.notify_irrigation(
        db, app.id,
        f"新灌溉申请: {app.application_no}",
        f"作物:{data.crop_type.value} 面积:{data.planting_area}亩 申请:{data.requested_amount}m³ "
        f"建议配水:{calc['recommended_amount']}m³ 水权余额:{remaining}m³"
    )

    return ResponseModel(data={
        "application": IrrigationApplicationOut.model_validate(app).model_dump(),
        "analysis": calc
    })


@router.get("/applications", response_model=PaginatedResponse, summary="灌溉申请列表")
def list_applications(
    applicant_id: Optional[int] = None, status: Optional[IrrigationStatus] = None,
    region: Optional[str] = None, page: int = 1, page_size: int = 20,
    db: Session = Depends(get_db)
):
    q = db.query(IrrigationApplication)
    if applicant_id:
        q = q.filter(IrrigationApplication.applicant_id == applicant_id)
    if status:
        q = q.filter(IrrigationApplication.status == status)
    if region:
        q = q.filter(IrrigationApplication.region == region)
    total = q.count()
    items = q.order_by(IrrigationApplication.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        data=[IrrigationApplicationOut.model_validate(i) for i in items]
    )


@router.post("/review", response_model=ResponseModel, summary="审核灌溉申请（自动校验+分配）")
def review_application(data: IrrigationReview, db: Session = Depends(get_db)):
    app = db.query(IrrigationApplication).filter(
        IrrigationApplication.id == data.application_id
    ).first()
    if not app:
        raise HTTPException(404, "申请不存在")
    if app.status != IrrigationStatus.PENDING:
        raise HTTPException(400, "申请已审核")

    water_right = db.query(WaterRight).filter(
        WaterRight.user_id == app.applicant_id
    ).order_by(WaterRight.id.desc()).first()

    calc = CropWaterRequirement.calculate_irrigation_need(
        app.crop_type, app.planting_area, app.soil_moisture
    )

    if not water_right:
        app.status = IrrigationStatus.REJECTED
        app.saving_suggestion = "用户无有效水权；" + "；".join(calc["saving_suggestions"])
        db.commit()
        NotificationService.notify_irrigation(
            db, app.id, f"灌溉申请被拒绝: {app.application_no}",
            "原因: 无有效水权", user_id=app.applicant_id
        )
        return ResponseModel(data={
            "approved": False, "reason": "无有效水权",
            "saving_suggestions": calc["saving_suggestions"]
        })

    remaining = water_right.remaining_amount
    requested = app.requested_amount
    recommended = calc["recommended_amount"]

    suggestions = calc["saving_suggestions"].copy()

    if not data.is_approved:
        app.status = IrrigationStatus.REJECTED
        app.saving_suggestion = data.review_note or "审核拒绝；" + "；".join(suggestions)
        app.reviewed_by = data.reviewer_id
        app.reviewed_at = datetime.utcnow()
        db.commit()
        NotificationService.notify_irrigation(
            db, app.id, f"灌溉申请审核: {app.application_no}",
            "申请已拒绝", user_id=app.applicant_id
        )
        return ResponseModel(data={"approved": False, "reason": data.review_note or "人工拒绝"})

    approved_amount = data.approved_amount if data.approved_amount else min(requested, recommended)

    if approved_amount > remaining:
        shortage = approved_amount - remaining
        suggestions.append(f"当前水权余额不足{remaining}m³，申请超额{shortage}m³，建议减少申请量或参与水权交易")
        app.status = IrrigationStatus.REJECTED
        app.saving_suggestion = "；".join(suggestions)
        app.reviewed_by = data.reviewer_id
        app.reviewed_at = datetime.utcnow()
        db.commit()
        NotificationService.notify_irrigation(
            db, app.id, f"灌溉申请超额被拒: {app.application_no}",
            f"申请{approved_amount}m³，水权余额{remaining}m³，缺口{shortage}m³。建议: {'；'.join(suggestions)}",
            user_id=app.applicant_id
        )
        return ResponseModel(data={
            "approved": False,
            "reason": f"水权余额不足，申请{approved_amount}m³ > 余额{remaining}m³",
            "saving_suggestions": suggestions
        })

    app.status = IrrigationStatus.APPROVED
    app.approved_amount = approved_amount
    app.saving_suggestion = "；".join(suggestions) if suggestions else None
    app.reviewed_by = data.reviewer_id
    app.reviewed_at = datetime.utcnow()

    water_right.used_amount += approved_amount
    water_right.remaining_amount = water_right.annual_quota - water_right.used_amount

    db.commit()
    db.refresh(app)

    NotificationService.notify_irrigation(
        db, app.id, f"灌溉申请通过: {app.application_no}",
        f"批准水量:{approved_amount}m³ 水权剩余:{water_right.remaining_amount}m³",
        user_id=app.applicant_id
    )

    return ResponseModel(data={
        "approved": True,
        "application": IrrigationApplicationOut.model_validate(app).model_dump(),
        "remaining_water_right": water_right.remaining_amount
    })


@router.put("/applications/{app_id}/complete", response_model=ResponseModel, summary="标记灌溉完成")
def mark_application_completed(app_id: int, db: Session = Depends(get_db)):
    app = db.query(IrrigationApplication).filter(IrrigationApplication.id == app_id).first()
    if not app:
        raise HTTPException(404, "申请不存在")
    app.status = IrrigationStatus.COMPLETED
    db.commit()
    return ResponseModel(message="已标记完成")


@router.post("/downstream-users", response_model=ResponseModel, summary="添加下游取水用户")
def add_downstream_user(
    user_id: int, monitor_section_id: int,
    daily_intake_quota: float, priority_level: int = 5,
    db: Session = Depends(get_db)
):
    d = DownstreamWaterUser(
        user_id=user_id, monitor_section_id=monitor_section_id,
        daily_intake_quota=daily_intake_quota, priority_level=priority_level
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return ResponseModel(data={"id": d.id})
