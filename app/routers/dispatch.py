from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, date, timedelta
import uuid

from app.database import get_db
from app.models import (
    Reservoir, HydrologicalStation, RealTimeData, RainfallForecast,
    DispatchInstruction, DispatchStatus, GateStation
)
from app.schemas import (
    ReservoirCreate, ReservoirOut, HydrologicalStationCreate, HydrologicalStationOut,
    RealTimeDataUpload, RealTimeDataOut, DispatchInstructionCreate,
    DispatchInstructionOut, SmartDispatchRequest, SmartDispatchResult,
    ResponseModel, PaginatedResponse
)
from app.services import DispatchAlgorithm, NotificationService

router = APIRouter(prefix="/api/v1/dispatch", tags=["1.Dispatch"])


def generate_instruction_code():
    return f"DIS{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"


@router.post("/reservoirs", response_model=ResponseModel, summary="创建水库信息")
def create_reservoir(data: ReservoirCreate, db: Session = Depends(get_db)):
    existing = db.query(Reservoir).filter(Reservoir.code == data.code).first()
    if existing:
        raise HTTPException(400, "水库编码已存在")
    r = Reservoir(**data.model_dump())
    r.current_storage = r.current_storage or 0
    db.add(r)
    db.commit()
    db.refresh(r)
    return ResponseModel(data=ReservoirOut.model_validate(r))


@router.get("/reservoirs", response_model=PaginatedResponse, summary="水库列表")
def list_reservoirs(
    basin: Optional[str] = None, page: int = 1, page_size: int = 20, db: Session = Depends(get_db)
):
    q = db.query(Reservoir)
    if basin:
        q = q.filter(Reservoir.basin == basin)
    total = q.count()
    items = q.order_by(Reservoir.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        data=[ReservoirOut.model_validate(i) for i in items]
    )


@router.post("/stations", response_model=ResponseModel, summary="创建水文站")
def create_station(data: HydrologicalStationCreate, db: Session = Depends(get_db)):
    existing = db.query(HydrologicalStation).filter(HydrologicalStation.code == data.code).first()
    if existing:
        raise HTTPException(400, "水文站编码已存在")
    s = HydrologicalStation(**data.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return ResponseModel(data=HydrologicalStationOut.model_validate(s))


@router.get("/stations", response_model=PaginatedResponse, summary="水文站列表")
def list_stations(
    basin: Optional[str] = None, station_type: Optional[str] = None,
    page: int = 1, page_size: int = 20, db: Session = Depends(get_db)
):
    q = db.query(HydrologicalStation)
    if basin:
        q = q.filter(HydrologicalStation.basin == basin)
    if station_type:
        q = q.filter(HydrologicalStation.station_type == station_type)
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        data=[HydrologicalStationOut.model_validate(i) for i in items]
    )


@router.post("/data/upload", response_model=ResponseModel, summary="上传实时水位/流量/雨量数据")
def upload_realtime_data(data: RealTimeDataUpload, db: Session = Depends(get_db)):
    if not data.station_id and not data.reservoir_id:
        raise HTTPException(400, "必须指定station_id或reservoir_id")

    rd = RealTimeData(**data.model_dump())
    db.add(rd)

    if data.reservoir_id and data.water_level is not None:
        r = db.query(Reservoir).filter(Reservoir.id == data.reservoir_id).first()
        if r:
            r.current_level = data.water_level
            if r.max_capacity and r.normal_level and r.normal_level > 0:
                ratio = min(data.water_level / r.normal_level, 1.0) if data.water_level <= r.normal_level else 1.0
                r.current_storage = r.max_capacity * ratio
    if data.reservoir_id and data.flow_rate is not None:
        r = db.query(Reservoir).filter(Reservoir.id == data.reservoir_id).first()
        if r:
            r.current_outflow = data.flow_rate

    db.commit()
    db.refresh(rd)
    return ResponseModel(data=RealTimeDataOut.model_validate(rd))


@router.get("/data/latest", response_model=ResponseModel, summary="查询最新实时数据")
def get_latest_data(station_id: Optional[int] = None, reservoir_id: Optional[int] = None,
                    hours: int = 24, db: Session = Depends(get_db)):
    since = datetime.utcnow() - timedelta(hours=hours)
    q = db.query(RealTimeData).filter(RealTimeData.timestamp >= since)
    if station_id:
        q = q.filter(RealTimeData.station_id == station_id)
    if reservoir_id:
        q = q.filter(RealTimeData.reservoir_id == reservoir_id)
    items = q.order_by(RealTimeData.timestamp.desc()).limit(100).all()
    return ResponseModel(data=[RealTimeDataOut.model_validate(i) for i in items])


@router.post("/instructions", response_model=ResponseModel, summary="创建调度指令")
def create_instruction(data: DispatchInstructionCreate, db: Session = Depends(get_db)):
    r = db.query(Reservoir).filter(Reservoir.id == data.reservoir_id).first()
    if not r:
        raise HTTPException(404, "水库不存在")
    ins = DispatchInstruction(
        **data.model_dump(),
        instruction_code=generate_instruction_code(),
        status=DispatchStatus.PENDING
    )
    db.add(ins)
    db.commit()
    db.refresh(ins)
    NotificationService.notify_dispatch(
        db, ins.id,
        f"新调度指令: {ins.instruction_code}",
        f"水库[{r.name}] {data.instruction_type} 目标出流:{data.target_outflow}m³/s"
    )
    return ResponseModel(data=DispatchInstructionOut.model_validate(ins))


@router.get("/instructions", response_model=PaginatedResponse, summary="调度指令列表")
def list_instructions(
    reservoir_id: Optional[int] = None,
    status: Optional[DispatchStatus] = None,
    page: int = 1, page_size: int = 20, db: Session = Depends(get_db)
):
    q = db.query(DispatchInstruction)
    if reservoir_id:
        q = q.filter(DispatchInstruction.reservoir_id == reservoir_id)
    if status:
        q = q.filter(DispatchInstruction.status == status)
    total = q.count()
    items = q.order_by(DispatchInstruction.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        data=[DispatchInstructionOut.model_validate(i) for i in items]
    )


@router.put("/instructions/{instruction_id}/status", response_model=ResponseModel, summary="下发/执行调度指令状态更新")
def update_instruction_status(
    instruction_id: int,
    status: DispatchStatus,
    operator_id: Optional[int] = None,
    note: Optional[str] = None,
    db: Session = Depends(get_db)
):
    ins = db.query(DispatchInstruction).filter(DispatchInstruction.id == instruction_id).first()
    if not ins:
        raise HTTPException(404, "指令不存在")
    ins.status = status
    now = datetime.utcnow()
    if status == DispatchStatus.SENT:
        ins.sent_at = now
    elif status == DispatchStatus.EXECUTING:
        ins.executed_at = now
    elif status == DispatchStatus.COMPLETED:
        ins.completed_at = now
        if note:
            ins.result_note = note

        r = db.query(Reservoir).filter(Reservoir.id == ins.reservoir_id).first()
        if r and ins.target_outflow is not None:
            r.current_outflow = ins.target_outflow

    db.commit()
    db.refresh(ins)
    NotificationService.notify_dispatch(
        db, ins.id,
        f"调度指令状态更新: {status.value}",
        f"指令[{ins.instruction_code}] 状态已更新为{status.value}"
    )
    return ResponseModel(data=DispatchInstructionOut.model_validate(ins))


@router.post("/smart-calculate", response_model=ResponseModel, summary="智能调度方案计算")
def smart_dispatch(request: SmartDispatchRequest, db: Session = Depends(get_db)
):
    reservoirs = db.query(Reservoir).filter(Reservoir.basin == request.basin).all()
    if not reservoirs:
        raise HTTPException(404, "该流域无水库数据")

    forecast = db.query(RainfallForecast).filter(
        RainfallForecast.basin == request.basin
    ).order_by(RainfallForecast.created_at.desc()).first()
    predicted_rainfall = forecast.predicted_rainfall if forecast else 0

    results = []
    created_instructions = []

    for r in reservoirs:
        scheme = DispatchAlgorithm.generate_scheme(
            current_storage=r.current_storage or 0,
            max_capacity=r.max_capacity,
            current_level=r.current_level or 0,
            flood_limit=r.flood_limit_level,
            normal_level=r.normal_level,
            current_inflow=r.current_inflow or 0,
            predicted_rainfall=predicted_rainfall,
            ecological_threshold=r.downstream_eco_threshold
        )

        results.append(SmartDispatchResult(
            reservoir_name=r.name,
            **scheme
        ))

        if scheme["risk_level"] in ("high", "medium"):
            ins = DispatchInstruction(
                instruction_code=generate_instruction_code(),
                reservoir_id=r.id,
                instruction_type=scheme["recommended_action"] if scheme["recommended_action"] in [
                    "flood_release", "pre_release", "storage", "regular"
                ] else "regular",
                target_outflow=scheme["target_outflow"],
                duration_hours=request.forecast_hours,
                priority=1 if scheme["risk_level"] == "high" else 3,
                reason=scheme["explanation"],
                status=DispatchStatus.PENDING
            )
            db.add(ins)
            created_instructions.append(ins)

    db.commit()
    for ins in created_instructions:
        db.refresh(ins)
        NotificationService.notify_dispatch(
            db, ins.id,
            f"智能调度生成指令: {ins.instruction_code}",
            ins.reason or ""
        )

    return ResponseModel(data={
        "basin": request.basin,
        "predicted_rainfall": predicted_rainfall,
        "schemes": [r.model_dump() for r in results],
        "generated_instructions": [DispatchInstructionOut.model_validate(i).model_dump() for i in created_instructions]
    })


@router.post("/forecasts", response_model=ResponseModel, summary="录入降雨预报")
def add_forecast(
    basin: str, region: Optional[str] = None,
    forecast_date: date = Query(...), predicted_rainfall: float = Query(...),
    forecast_hours: int = 24, probability: float = 0.7,
    forecast_model: str = "default", db: Session = Depends(get_db)
):
    f = RainfallForecast(
        basin=basin, region=region, forecast_date=forecast_date,
        forecast_hours=forecast_hours, predicted_rainfall=predicted_rainfall,
        probability=probability, forecast_model=forecast_model
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return ResponseModel(data={"id": f.id, "forecast_date": f.forecast_date,
                        "predicted_rainfall": f.predicted_rainfall})


@router.post("/gates", response_model=ResponseModel, summary="创建闸站")
def create_gate(
    name: str, code: str, reservoir_id: int,
    gate_type: str = "sluice", max_opening: float = 10.0,
    operator_id: Optional[int] = None, db: Session = Depends(get_db)
):
    g = GateStation(
        name=name, code=code, reservoir_id=reservoir_id,
        gate_type=gate_type, max_opening=max_opening, operator_id=operator_id
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return ResponseModel(data={"id": g.id, "name": g.name, "code": g.code})
