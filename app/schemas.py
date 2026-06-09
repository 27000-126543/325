from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from app.models import (
    UserRole, DispatchStatus, IrrigationStatus, OrderStatus,
    TransferStatus, MaintenanceStatus, WorkOrderStatus, CropType
)


class ResponseModel(BaseModel):
    code: int = 200
    message: str = "success"
    data: Optional[Any] = None


class PaginatedResponse(BaseModel):
    code: int = 200
    message: str = "success"
    total: int = 0
    page: int = 1
    page_size: int = 20
    data: List[Any] = []


class UserLogin(BaseModel):
    username: str
    password: str


class TokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    role: str
    full_name: str


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    full_name: str
    role: UserRole
    phone: Optional[str] = None
    email: Optional[str] = None
    organization: Optional[str] = None
    region: Optional[str] = None


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: UserRole
    phone: Optional[str] = None
    email: Optional[str] = None
    organization: Optional[str] = None
    region: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ReservoirCreate(BaseModel):
    name: str
    code: str
    basin: str
    region: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    max_capacity: float
    flood_limit_level: Optional[float] = None
    normal_level: Optional[float] = None
    dead_level: Optional[float] = None
    design_discharge: Optional[float] = None
    downstream_eco_threshold: Optional[float] = None


class ReservoirOut(ReservoirCreate):
    id: int
    current_level: float
    current_storage: float
    current_inflow: float
    current_outflow: float
    ecological_release: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class HydrologicalStationCreate(BaseModel):
    name: str
    code: str
    basin: str
    region: Optional[str] = None
    station_type: str = "hydrology"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    upstream_reservoir_id: Optional[int] = None
    warning_level: Optional[float] = None
    guarantee_level: Optional[float] = None


class HydrologicalStationOut(HydrologicalStationCreate):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class RealTimeDataUpload(BaseModel):
    station_id: Optional[int] = None
    reservoir_id: Optional[int] = None
    data_type: str = Field(..., description="water_level/flow_rate/rainfall/combined")
    water_level: Optional[float] = None
    flow_rate: Optional[float] = None
    rainfall: Optional[float] = None
    source: Optional[str] = "sensor"


class RealTimeDataOut(BaseModel):
    id: int
    station_id: Optional[int]
    reservoir_id: Optional[int]
    data_type: str
    water_level: Optional[float]
    flow_rate: Optional[float]
    rainfall: Optional[float]
    timestamp: datetime
    quality_flag: str

    class Config:
        from_attributes = True


class DispatchInstructionCreate(BaseModel):
    reservoir_id: int
    instruction_type: str = Field(..., description="flood_release/storage/eco_adjust/regular")
    target_level: Optional[float] = None
    target_outflow: Optional[float] = None
    duration_hours: Optional[int] = None
    priority: int = 5
    reason: Optional[str] = None


class DispatchInstructionOut(DispatchInstructionCreate):
    id: int
    instruction_code: str
    status: DispatchStatus
    created_at: datetime
    sent_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SmartDispatchRequest(BaseModel):
    basin: str
    forecast_hours: int = 72


class SmartDispatchResult(BaseModel):
    reservoir_name: str
    current_storage_ratio: float
    predicted_inflow: float
    recommended_action: str
    target_outflow: float
    risk_level: str
    explanation: str


class IrrigationApplicationCreate(BaseModel):
    applicant_id: int
    region: str
    crop_type: CropType
    planting_area: float
    requested_amount: float
    soil_moisture: Optional[float] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class IrrigationApplicationOut(IrrigationApplicationCreate):
    id: int
    application_no: str
    current_water_right_remaining: Optional[float] = None
    approved_amount: Optional[float] = None
    status: IrrigationStatus
    saving_suggestion: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class IrrigationReview(BaseModel):
    application_id: int
    is_approved: bool
    approved_amount: Optional[float] = None
    reviewer_id: int
    review_note: Optional[str] = None


class WaterQualityDataUpload(BaseModel):
    station_id: int
    cod: Optional[float] = None
    nh3n: Optional[float] = None
    tp: Optional[float] = None
    tn: Optional[float] = None
    ph: Optional[float] = None
    do: Optional[float] = None
    turbidity: Optional[float] = None
    temperature: Optional[float] = None


class WaterQualityDataOut(BaseModel):
    id: int
    station_id: int
    cod: Optional[float]
    nh3n: Optional[float]
    tp: Optional[float]
    tn: Optional[float]
    ph: Optional[float]
    do: Optional[float]
    is_over_limit: bool
    over_limit_items: Optional[Dict]
    measured_at: datetime

    class Config:
        from_attributes = True


class WorkOrderOut(BaseModel):
    id: int
    work_order_no: str
    station_id: int
    over_limit_items: Dict
    hydrological_analysis: Optional[str]
    suggested_investigation_areas: Optional[List]
    priority_outlets: Optional[List]
    penalty_suggestion: Optional[str]
    status: WorkOrderStatus
    assigned_to: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


class WorkOrderInvestigation(BaseModel):
    work_order_id: int
    result: str
    confirmed_outlet_id: Optional[int] = None
    penalty_amount: Optional[float] = None
    penalty_suggestion: Optional[str] = None


class EcologicalFlowOut(BaseModel):
    id: int
    section_name: str
    section_code: str
    basin: str
    legal_minimum_flow: float
    current_flow: float
    is_below_threshold: bool
    last_check_time: Optional[datetime]
    last_adjustment_time: Optional[datetime]

    class Config:
        from_attributes = True


class EcoAdjustmentOut(BaseModel):
    id: int
    monitor_id: int
    reservoir_id: int
    previous_release: float
    adjusted_release: float
    reason: str
    notified_users: Optional[List]
    adjustment_deadline: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class WaterRightCreate(BaseModel):
    right_code: str
    user_id: int
    water_source: Optional[str] = None
    annual_quota: float
    valid_from: date
    valid_to: date
    region: str
    approved_by: int


class WaterRightOut(WaterRightCreate):
    id: int
    used_amount: float
    remaining_amount: float
    created_at: datetime

    class Config:
        from_attributes = True


class TradeOrderCreate(BaseModel):
    order_type: str = Field(..., description="buy/sell")
    user_id: int
    water_right_id: int
    water_volume: float
    expected_price: float
    region: str
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None


class TradeOrderOut(TradeOrderCreate):
    id: int
    order_no: str
    status: OrderStatus
    matched_order_id: Optional[int] = None
    final_price: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TradeContractOut(BaseModel):
    id: int
    contract_no: str
    buyer_id: int
    seller_id: int
    trade_volume: float
    unit_price: float
    total_amount: float
    historical_avg_price: Optional[float]
    approval_status: OrderStatus
    effective_date: Optional[date]
    created_at: datetime

    class Config:
        from_attributes = True


class ContractApprove(BaseModel):
    contract_id: int
    approver_id: int
    is_approved: bool
    remarks: Optional[str] = None


class RegionOut(BaseModel):
    id: int
    name: str
    code: str
    basin: str
    water_shortage_index: float
    annual_water_demand: Optional[float]
    current_supply_capacity: Optional[float]

    class Config:
        from_attributes = True


class TransferSchemeOut(BaseModel):
    id: int
    scheme_no: str
    scheme_name: Optional[str]
    from_region_id: int
    to_region_id: int
    transfer_volume: float
    estimated_duration_days: Optional[int]
    priority_score: float
    status: TransferStatus
    required_countersign_regions: Optional[List]
    signed_regions: Optional[List]
    overdue_deadline: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class CountersignRequest(BaseModel):
    transfer_id: int
    region_id: int
    signer_id: int
    is_approved: bool
    opinion: Optional[str] = None


class GenerateTransferRequest(BaseModel):
    basin: str
    target_volume: Optional[float] = None


class ProjectCreate(BaseModel):
    name: str
    code: str
    project_type: str
    basin: Optional[str] = None
    region: Optional[str] = None
    built_date: Optional[date] = None
    maintenance_cycle_days: int = 365
    responsible_team: Optional[str] = None


class ProjectOut(ProjectCreate):
    id: int
    last_maintenance_date: Optional[date]
    next_maintenance_date: Optional[date]
    health_status: str
    created_at: datetime

    class Config:
        from_attributes = True


class MaintenanceTaskOut(BaseModel):
    id: int
    task_no: str
    project_id: int
    task_type: str
    priority: int
    description: Optional[str]
    status: MaintenanceStatus
    assigned_team_id: Optional[int]
    scheduled_date: Optional[date]
    created_at: datetime

    class Config:
        from_attributes = True


class MaintenanceComplete(BaseModel):
    task_id: int
    report: str
    parts_used: Optional[List] = None
    actual_duration_hours: Optional[float] = None


class DailyReportOut(BaseModel):
    id: int
    report_no: str
    report_date: date
    basin: Optional[str]
    total_storage: float
    total_supply: float
    avg_water_quality_rate: float
    ecological_flow_satisfaction_rate: float
    rainfall_total: float
    irrigation_total: float
    trade_volume: float
    maintenance_completed: int
    warnings_count: int
    summary: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class GenerateReportRequest(BaseModel):
    report_date: Optional[date] = None
    basin: Optional[str] = None


class NotificationOut(BaseModel):
    id: int
    message_no: str
    message_type: str
    title: str
    content: Optional[str]
    target_roles: Optional[List]
    target_user_ids: Optional[List] = None
    related_business_type: Optional[str]
    related_business_id: Optional[int]
    is_read: bool
    pushed_at: Optional[datetime]
    created_at: datetime

    @field_validator('target_roles', 'target_user_ids', mode='before')
    @classmethod
    def _norm_json_list(cls, v):
        import json as _json
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                p = _json.loads(v)
                return p if isinstance(p, list) else []
            except (ValueError, TypeError):
                return []
        return []

    class Config:
        from_attributes = True


class SoilMoistureCreate(BaseModel):
    region: str
    monitoring_point: Optional[str] = None
    crop_type: Optional[CropType] = None
    moisture_content: float
    field_capacity: Optional[float] = None
    wilting_point: Optional[float] = None
