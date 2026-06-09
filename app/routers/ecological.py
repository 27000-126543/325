from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timedelta
import uuid
import json

from app.database import get_db
from app.models import (
    EcologicalFlowMonitor, EcologicalAdjustmentRecord,
    Reservoir, DispatchInstruction, DispatchStatus,
    DownstreamWaterUser
)
from app.schemas import (
    EcologicalFlowOut, EcoAdjustmentOut,
    DispatchInstructionOut, ResponseModel, PaginatedResponse
)
from app.services import NotificationService

router = APIRouter(prefix="/api/v1/ecological", tags=["4.EcologicalFlow"])


def generate_adjustment_instruction_code():
    return f"ECO{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"


@router.post("/monitors", response_model=ResponseModel, summary="创建生态流量监测断面")
def create_monitor(
    section_name: str, section_code: str, basin: str,
    upstream_reservoir_id: int, legal_minimum_flow: float,
    db: Session = Depends(get_db)
):
    existing = db.query(EcologicalFlowMonitor).filter(
        EcologicalFlowMonitor.section_code == section_code
    ).first()
    if existing:
        raise HTTPException(400, "监测断面编码已存在")
    m = EcologicalFlowMonitor(
        section_name=section_name, section_code=section_code, basin=basin,
        upstream_reservoir_id=upstream_reservoir_id,
        legal_minimum_flow=legal_minimum_flow
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return ResponseModel(data=EcologicalFlowOut.model_validate(m).model_dump())


@router.get("/monitors", response_model=PaginatedResponse, summary="生态流量监测断面列表")
def list_monitors(
    basin: Optional[str] = None, is_below: Optional[bool] = None,
    page: int = 1, page_size: int = 20, db: Session = Depends(get_db)
):
    q = db.query(EcologicalFlowMonitor)
    if basin:
        q = q.filter(EcologicalFlowMonitor.basin == basin)
    if is_below is not None:
        q = q.filter(EcologicalFlowMonitor.is_below_threshold == is_below)
    total = q.count()
    items = q.order_by(EcologicalFlowMonitor.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        data=[EcologicalFlowOut.model_validate(i) for i in items]
    )


@router.post("/monitor/{monitor_id}/report-flow", response_model=ResponseModel, summary="上报监测断面实时流量（低于阈值自动调整）")
def report_ecological_flow(
    monitor_id: int, current_flow: float,
    db: Session = Depends(get_db)
):
    monitor = db.query(EcologicalFlowMonitor).filter(
        EcologicalFlowMonitor.id == monitor_id
    ).first()
    if not monitor:
        raise HTTPException(404, "监测断面不存在")

    monitor.current_flow = current_flow
    monitor.last_check_time = datetime.utcnow()

    was_below = monitor.is_below_threshold
    monitor.is_below_threshold = current_flow < monitor.legal_minimum_flow

    adjustment = None
    dispatch_ins = None
    notified_user_ids = []

    if monitor.is_below_threshold:
        deficit = monitor.legal_minimum_flow - current_flow
        reservoir = db.query(Reservoir).filter(
            Reservoir.id == monitor.upstream_reservoir_id
        ).first()

        if reservoir:
            new_release = reservoir.current_outflow + deficit * 1.2
            if new_release > reservoir.design_discharge or 0 if not reservoir.design_discharge else new_release:
                new_release = min(new_release, reservoir.design_discharge or new_release)

            adjustment = EcologicalAdjustmentRecord(
                monitor_id=monitor_id,
                reservoir_id=reservoir.id,
                previous_release=reservoir.current_outflow,
                adjusted_release=new_release,
                reason=f"生态流量不足：当前{current_flow}m³/s < 法定阈值{monitor.legal_minimum_flow}m³/s，缺口{round(deficit,2)}m³/s，自动增加下泄",
                adjustment_deadline=datetime.utcnow() + timedelta(hours=2)
            )
            db.add(adjustment)

            dispatch_ins = DispatchInstruction(
                instruction_code=generate_adjustment_instruction_code(),
                reservoir_id=reservoir.id,
                instruction_type="eco_adjust",
                target_outflow=new_release,
                duration_hours=72,
                priority=1,
                reason=adjustment.reason,
                status=DispatchStatus.SENT,
                sent_at=datetime.utcnow()
            )
            db.add(dispatch_ins)

            reservoir.current_outflow = new_release
            reservoir.ecological_release = new_release
            monitor.last_adjustment_time = datetime.utcnow()

            downstream_users = db.query(DownstreamWaterUser).filter(
                DownstreamWaterUser.monitor_section_id == monitor_id
            ).all()

            for du in downstream_users:
                notified_user_ids.append(du.user_id)

            if notified_user_ids:
                monitor.last_notified_users = json.dumps(notified_user_ids)
                NotificationService.notify_ecological(
                    db, monitor.id,
                    f"生态流量告警并已自动调整: {monitor.section_name}",
                    f"当前流量{current_flow}m³/s < 法定{monitor.legal_minimum_flow}m³/s。"
                    f"上游水库[{reservoir.name}]下泄已调整为{round(new_release,2)}m³/s。"
                    f"请在2小时内调整取水计划！",
                    user_ids=notified_user_ids
                )

                for uid in notified_user_ids:
                    NotificationService.create_notification(
                        db,
                        message_type="ECOLOGICAL_WARNING",
                        title=f"【取水调整通知】{monitor.section_name}生态流量不足",
                        content=f"因生态流量不足，请于{adjustment.adjustment_deadline.strftime('%Y-%m-%d %H:%M')}前"
                                f"减少取水量，保证生态流量不低于{monitor.legal_minimum_flow}m³/s。"
                                f"违规取水将按超许可取水处罚。",
                        target_user_ids=[uid],
                        related_business_type="ecological_flow",
                        related_business_id=monitor_id
                    )

    elif was_below and not monitor.is_below_threshold:
        NotificationService.notify_ecological(
            db, monitor.id,
            f"生态流量已恢复: {monitor.section_name}",
            f"当前流量{current_flow}m³/s ≥ 法定阈值{monitor.legal_minimum_flow}m³/s，状态恢复正常。"
        )

    db.commit()
    if adjustment:
        db.refresh(adjustment)
    if dispatch_ins:
        db.refresh(dispatch_ins)

    return ResponseModel(data={
        "monitor": EcologicalFlowOut.model_validate(monitor).model_dump(),
        "adjustment": EcoAdjustmentOut.model_validate(adjustment).model_dump() if adjustment else None,
        "dispatch_instruction": DispatchInstructionOut.model_validate(dispatch_ins).model_dump() if dispatch_ins else None,
        "notified_downstream_users_count": len(notified_user_ids)
    })


@router.get("/adjustments", response_model=PaginatedResponse, summary="生态流量调整记录")
def list_adjustments(
    monitor_id: Optional[int] = None, reservoir_id: Optional[int] = None,
    page: int = 1, page_size: int = 20, db: Session = Depends(get_db)
):
    q = db.query(EcologicalAdjustmentRecord)
    if monitor_id:
        q = q.filter(EcologicalAdjustmentRecord.monitor_id == monitor_id)
    if reservoir_id:
        q = q.filter(EcologicalAdjustmentRecord.reservoir_id == reservoir_id)
    total = q.count()
    items = q.order_by(EcologicalAdjustmentRecord.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        data=[EcoAdjustmentOut.model_validate(i) for i in items]
    )


@router.get("/monitors/{monitor_id}/downstream-users", response_model=ResponseModel, summary="获取下游取水用户列表")
def get_downstream_users(monitor_id: int, db: Session = Depends(get_db)):
    users = db.query(DownstreamWaterUser).filter(
        DownstreamWaterUser.monitor_section_id == monitor_id
    ).all()
    return ResponseModel(data=[{
        "id": u.id, "user_id": u.user_id,
        "daily_intake_quota": u.daily_intake_quota,
        "current_intake": u.current_intake,
        "priority_level": u.priority_level
    } for u in users])


@router.post("/monitors/check-all", response_model=ResponseModel, summary="批量检查所有监测断面（定时任务调用）")
def check_all_monitors(db: Session = Depends(get_db)):
    monitors = db.query(EcologicalFlowMonitor).all()
    results = []
    for m in monitors:
        if m.last_check_time and (datetime.utcnow() - m.last_check_time) < timedelta(minutes=30):
            continue
        r = report_ecological_flow.__wrapped__(m.id, m.current_flow, db) \
            if hasattr(report_ecological_flow, '__wrapped__') \
            else report_ecological_flow(m.id, m.current_flow, db)
        results.append({
            "section": m.section_name,
            "flow": m.current_flow,
            "threshold": m.legal_minimum_flow,
            "is_below": m.is_below_threshold
        })
    return ResponseModel(data={"checked_count": len(results), "details": results})
