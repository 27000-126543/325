from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean,
    Date, Enum as SAEnum, JSON
)
from sqlalchemy.orm import relationship
from datetime import datetime, date
from app.database import Base
import enum


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    BASIN_MANAGER = "basin_manager"
    WATER_ADMIN = "water_admin"
    ENV_OFFICER = "env_officer"
    AGRI_OFFICER = "agri_officer"
    ENGINEER = "engineer"
    WATER_USER = "water_user"


class DispatchStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    EXECUTING = "executing"
    COMPLETED = "completed"
    REJECTED = "rejected"


class IrrigationStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class OrderStatus(str, enum.Enum):
    OPEN = "open"
    MATCHED = "matched"
    APPROVING = "approving"
    EFFECTIVE = "effective"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TransferStatus(str, enum.Enum):
    DRAFT = "draft"
    COUNTERSIGNING = "countersigning"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    REJECTED = "rejected"
    OVERDUE = "overdue"


class MaintenanceStatus(str, enum.Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    VERIFIED = "verified"


class WorkOrderStatus(str, enum.Enum):
    CREATED = "created"
    INVESTIGATING = "investigating"
    CONFIRMED = "confirmed"
    PENALTY_ISSUED = "penalty_issued"
    CLOSED = "closed"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False)
    phone = Column(String(20))
    email = Column(String(100))
    organization = Column(String(200))
    region = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)


class Reservoir(Base):
    __tablename__ = "reservoirs"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    code = Column(String(30), unique=True, index=True)
    basin = Column(String(100), nullable=False)
    region = Column(String(100))
    latitude = Column(Float)
    longitude = Column(Float)
    max_capacity = Column(Float, nullable=False)
    flood_limit_level = Column(Float)
    normal_level = Column(Float)
    dead_level = Column(Float)
    design_discharge = Column(Float)
    current_level = Column(Float, default=0.0)
    current_storage = Column(Float, default=0.0)
    current_inflow = Column(Float, default=0.0)
    current_outflow = Column(Float, default=0.0)
    ecological_release = Column(Float, default=0.0)
    downstream_eco_threshold = Column(Float)
    operator_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class HydrologicalStation(Base):
    __tablename__ = "hydrological_stations"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    code = Column(String(30), unique=True, index=True)
    basin = Column(String(100), nullable=False)
    region = Column(String(100))
    station_type = Column(String(20), default="hydrology")
    latitude = Column(Float)
    longitude = Column(Float)
    upstream_reservoir_id = Column(Integer, ForeignKey("reservoirs.id"))
    warning_level = Column(Float)
    guarantee_level = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)


class RealTimeData(Base):
    __tablename__ = "realtime_data"
    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("hydrological_stations.id"))
    reservoir_id = Column(Integer, ForeignKey("reservoirs.id"))
    data_type = Column(String(20), nullable=False)
    water_level = Column(Float)
    flow_rate = Column(Float)
    rainfall = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    source = Column(String(50))
    quality_flag = Column(String(10), default="valid")


class RainfallForecast(Base):
    __tablename__ = "rainfall_forecasts"
    id = Column(Integer, primary_key=True, index=True)
    basin = Column(String(100), nullable=False)
    region = Column(String(100))
    forecast_date = Column(Date, nullable=False)
    forecast_hours = Column(Integer, default=24)
    predicted_rainfall = Column(Float, nullable=False)
    probability = Column(Float, default=0.7)
    forecast_model = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)


class DispatchInstruction(Base):
    __tablename__ = "dispatch_instructions"
    id = Column(Integer, primary_key=True, index=True)
    instruction_code = Column(String(50), unique=True, index=True)
    reservoir_id = Column(Integer, ForeignKey("reservoirs.id"))
    instruction_type = Column(String(20), nullable=False)
    target_level = Column(Float)
    target_outflow = Column(Float)
    duration_hours = Column(Integer)
    priority = Column(Integer, default=5)
    reason = Column(Text)
    status = Column(SAEnum(DispatchStatus), default=DispatchStatus.PENDING)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime)
    executed_at = Column(DateTime)
    completed_at = Column(DateTime)
    result_note = Column(Text)


class GateStation(Base):
    __tablename__ = "gate_stations"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    code = Column(String(30), unique=True, index=True)
    reservoir_id = Column(Integer, ForeignKey("reservoirs.id"))
    gate_type = Column(String(20))
    max_opening = Column(Float)
    current_opening = Column(Float, default=0.0)
    current_discharge = Column(Float, default=0.0)
    operator_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


class CropType(str, enum.Enum):
    RICE = "rice"
    WHEAT = "wheat"
    CORN = "corn"
    VEGETABLE = "vegetable"
    FRUIT = "fruit"
    OTHER = "other"


class SoilMoistureData(Base):
    __tablename__ = "soil_moisture_data"
    id = Column(Integer, primary_key=True, index=True)
    region = Column(String(100), nullable=False)
    monitoring_point = Column(String(100))
    crop_type = Column(SAEnum(CropType))
    moisture_content = Column(Float, nullable=False)
    field_capacity = Column(Float)
    wilting_point = Column(Float)
    measured_at = Column(DateTime, default=datetime.utcnow)


class WaterRight(Base):
    __tablename__ = "water_rights"
    id = Column(Integer, primary_key=True, index=True)
    right_code = Column(String(50), unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    water_source = Column(String(100))
    annual_quota = Column(Float, nullable=False)
    used_amount = Column(Float, default=0.0)
    remaining_amount = Column(Float, default=0.0)
    valid_from = Column(Date, nullable=False)
    valid_to = Column(Date, nullable=False)
    region = Column(String(100))
    approved_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


class IrrigationApplication(Base):
    __tablename__ = "irrigation_applications"
    id = Column(Integer, primary_key=True, index=True)
    application_no = Column(String(50), unique=True, index=True)
    applicant_id = Column(Integer, ForeignKey("users.id"))
    region = Column(String(100))
    crop_type = Column(SAEnum(CropType), nullable=False)
    planting_area = Column(Float, nullable=False)
    requested_amount = Column(Float, nullable=False)
    soil_moisture = Column(Float)
    current_water_right_remaining = Column(Float)
    approved_amount = Column(Float)
    status = Column(SAEnum(IrrigationStatus), default=IrrigationStatus.PENDING)
    saving_suggestion = Column(Text)
    reviewed_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime)
    start_date = Column(Date)
    end_date = Column(Date)


class WaterQualityStation(Base):
    __tablename__ = "water_quality_stations"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    code = Column(String(30), unique=True, index=True)
    basin = Column(String(100), nullable=False)
    region = Column(String(100))
    river_section = Column(String(100))
    latitude = Column(Float)
    longitude = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)


class WaterQualityData(Base):
    __tablename__ = "water_quality_data"
    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("water_quality_stations.id"))
    cod = Column(Float)
    nh3n = Column(Float)
    tp = Column(Float)
    tn = Column(Float)
    ph = Column(Float)
    do = Column(Float)
    turbidity = Column(Float)
    temperature = Column(Float)
    is_over_limit = Column(Boolean, default=False)
    over_limit_items = Column(JSON)
    measured_at = Column(DateTime, default=datetime.utcnow, index=True)


class PollutionOutlet(Base):
    __tablename__ = "pollution_outlets"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    code = Column(String(30), unique=True, index=True)
    enterprise_name = Column(String(200))
    region = Column(String(100))
    river_bank = Column(String(10))
    latitude = Column(Float)
    longitude = Column(Float)
    design_discharge = Column(Float)
    permit_cod_limit = Column(Float)
    permit_nh3n_limit = Column(Float)
    outlet_type = Column(String(30))
    created_at = Column(DateTime, default=datetime.utcnow)


class TraceabilityWorkOrder(Base):
    __tablename__ = "traceability_work_orders"
    id = Column(Integer, primary_key=True, index=True)
    work_order_no = Column(String(50), unique=True, index=True)
    station_id = Column(Integer, ForeignKey("water_quality_stations.id"))
    quality_data_id = Column(Integer, ForeignKey("water_quality_data.id"))
    over_limit_items = Column(JSON)
    hydrological_analysis = Column(Text)
    suggested_investigation_areas = Column(JSON)
    priority_outlets = Column(JSON)
    status = Column(SAEnum(WorkOrderStatus), default=WorkOrderStatus.CREATED)
    assigned_to = Column(Integer, ForeignKey("users.id"))
    penalty_suggestion = Column(Text)
    investigation_result = Column(Text)
    confirmed_outlet_id = Column(Integer, ForeignKey("pollution_outlets.id"))
    penalty_amount = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime)


class EcologicalFlowMonitor(Base):
    __tablename__ = "ecological_flow_monitors"
    id = Column(Integer, primary_key=True, index=True)
    section_name = Column(String(100), nullable=False)
    section_code = Column(String(30), unique=True, index=True)
    basin = Column(String(100), nullable=False)
    upstream_reservoir_id = Column(Integer, ForeignKey("reservoirs.id"))
    legal_minimum_flow = Column(Float, nullable=False)
    current_flow = Column(Float, default=0.0)
    is_below_threshold = Column(Boolean, default=False)
    last_check_time = Column(DateTime)
    last_adjustment_time = Column(DateTime)
    last_notified_users = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EcologicalAdjustmentRecord(Base):
    __tablename__ = "eco_adjustment_records"
    id = Column(Integer, primary_key=True, index=True)
    monitor_id = Column(Integer, ForeignKey("ecological_flow_monitors.id"))
    reservoir_id = Column(Integer, ForeignKey("reservoirs.id"))
    previous_release = Column(Float)
    adjusted_release = Column(Float)
    reason = Column(Text)
    notified_users = Column(JSON)
    adjustment_deadline = Column(DateTime)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


class WaterTradeOrder(Base):
    __tablename__ = "water_trade_orders"
    id = Column(Integer, primary_key=True, index=True)
    order_no = Column(String(50), unique=True, index=True)
    order_type = Column(String(10), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"))
    water_right_id = Column(Integer, ForeignKey("water_rights.id"))
    water_volume = Column(Float, nullable=False)
    expected_price = Column(Float, nullable=False)
    region = Column(String(100))
    valid_from = Column(Date)
    valid_to = Column(Date)
    status = Column(SAEnum(OrderStatus), default=OrderStatus.OPEN)
    matched_order_id = Column(Integer, ForeignKey("water_trade_orders.id"))
    final_price = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)


class WaterTradeContract(Base):
    __tablename__ = "water_trade_contracts"
    id = Column(Integer, primary_key=True, index=True)
    contract_no = Column(String(50), unique=True, index=True)
    buy_order_id = Column(Integer, ForeignKey("water_trade_orders.id"))
    sell_order_id = Column(Integer, ForeignKey("water_trade_orders.id"))
    buyer_id = Column(Integer, ForeignKey("users.id"))
    seller_id = Column(Integer, ForeignKey("users.id"))
    trade_volume = Column(Float, nullable=False)
    unit_price = Column(Float, nullable=False)
    total_amount = Column(Float, nullable=False)
    historical_avg_price = Column(Float)
    approval_status = Column(SAEnum(OrderStatus), default=OrderStatus.APPROVING)
    approved_by = Column(Integer, ForeignKey("users.id"))
    approved_at = Column(DateTime)
    effective_date = Column(Date)
    expiry_date = Column(Date)
    remarks = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class TradePriceHistory(Base):
    __tablename__ = "trade_price_history"
    id = Column(Integer, primary_key=True, index=True)
    basin = Column(String(100), nullable=False)
    region = Column(String(100))
    trade_date = Column(Date, nullable=False)
    avg_price = Column(Float, nullable=False)
    total_volume = Column(Float, default=0.0)
    transaction_count = Column(Integer, default=0)
    price_trend = Column(String(10))
    created_at = Column(DateTime, default=datetime.utcnow)


class AdministrativeRegion(Base):
    __tablename__ = "administrative_regions"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    code = Column(String(30), unique=True, index=True)
    basin = Column(String(100), nullable=False)
    population = Column(Float)
    gdp = Column(Float)
    annual_water_demand = Column(Float)
    current_supply_capacity = Column(Float)
    water_shortage_index = Column(Float, default=0.0)
    manager_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


class WaterPipeline(Base):
    __tablename__ = "water_pipelines"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    code = Column(String(30), unique=True, index=True)
    from_region_id = Column(Integer, ForeignKey("administrative_regions.id"))
    to_region_id = Column(Integer, ForeignKey("administrative_regions.id"))
    design_capacity = Column(Float, nullable=False)
    current_utilization = Column(Float, default=0.0)
    length_km = Column(Float)
    status = Column(String(20), default="operational")
    created_at = Column(DateTime, default=datetime.utcnow)


class CrossRegionTransfer(Base):
    __tablename__ = "cross_region_transfers"
    id = Column(Integer, primary_key=True, index=True)
    scheme_no = Column(String(50), unique=True, index=True)
    scheme_name = Column(String(200))
    from_region_id = Column(Integer, ForeignKey("administrative_regions.id"))
    to_region_id = Column(Integer, ForeignKey("administrative_regions.id"))
    pipeline_id = Column(Integer, ForeignKey("water_pipelines.id"))
    transfer_volume = Column(Float, nullable=False)
    estimated_duration_days = Column(Integer)
    water_shortage_index = Column(Float)
    priority_score = Column(Float)
    status = Column(SAEnum(TransferStatus), default=TransferStatus.DRAFT)
    required_countersign_regions = Column(JSON)
    signed_regions = Column(JSON, default=list)
    overdue_deadline = Column(DateTime)
    last_reminder_at = Column(DateTime)
    execution_start = Column(DateTime)
    execution_end = Column(DateTime)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


class CountersignRecord(Base):
    __tablename__ = "countersign_records"
    id = Column(Integer, primary_key=True, index=True)
    transfer_id = Column(Integer, ForeignKey("cross_region_transfers.id"))
    region_id = Column(Integer, ForeignKey("administrative_regions.id"))
    signer_id = Column(Integer, ForeignKey("users.id"))
    is_approved = Column(Boolean)
    opinion = Column(Text)
    signed_at = Column(DateTime, default=datetime.utcnow)


class WaterProject(Base):
    __tablename__ = "water_projects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    code = Column(String(30), unique=True, index=True)
    project_type = Column(String(30), nullable=False)
    basin = Column(String(100))
    region = Column(String(100))
    latitude = Column(Float)
    longitude = Column(Float)
    built_date = Column(Date)
    last_maintenance_date = Column(Date)
    next_maintenance_date = Column(Date)
    maintenance_cycle_days = Column(Integer, default=365)
    health_status = Column(String(20), default="normal")
    responsible_team = Column(String(100))
    specifications = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MaintenanceTeam(Base):
    __tablename__ = "maintenance_teams"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    code = Column(String(30), unique=True, index=True)
    region = Column(String(100))
    team_leader = Column(String(100))
    phone = Column(String(20))
    member_count = Column(Integer, default=0)
    skills = Column(JSON)
    coverage_area = Column(String(200))
    current_workload = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)


class MaintenanceTask(Base):
    __tablename__ = "maintenance_tasks"
    id = Column(Integer, primary_key=True, index=True)
    task_no = Column(String(50), unique=True, index=True)
    project_id = Column(Integer, ForeignKey("water_projects.id"))
    task_type = Column(String(30), nullable=False)
    required_skills = Column(JSON)
    priority = Column(Integer, default=3)
    description = Column(Text)
    expected_duration_hours = Column(Float)
    status = Column(SAEnum(MaintenanceStatus), default=MaintenanceStatus.PENDING)
    assigned_team_id = Column(Integer, ForeignKey("maintenance_teams.id"))
    assignee_id = Column(Integer, ForeignKey("users.id"))
    scheduled_date = Column(Date)
    start_time = Column(DateTime)
    complete_time = Column(DateTime)
    parts_used = Column(JSON)
    maintenance_report = Column(Text)
    ledger_updated = Column(Boolean, default=False)
    verified_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


class DailyReport(Base):
    __tablename__ = "daily_reports"
    id = Column(Integer, primary_key=True, index=True)
    report_no = Column(String(50), unique=True, index=True)
    report_date = Column(Date, nullable=False)
    basin = Column(String(100))
    total_storage = Column(Float, default=0.0)
    total_supply = Column(Float, default=0.0)
    reservoir_stats = Column(JSON)
    avg_water_quality_rate = Column(Float, default=100.0)
    quality_station_stats = Column(JSON)
    ecological_flow_satisfaction_rate = Column(Float, default=100.0)
    eco_monitor_stats = Column(JSON)
    rainfall_total = Column(Float, default=0.0)
    irrigation_total = Column(Float, default=0.0)
    trade_volume = Column(Float, default=0.0)
    maintenance_completed = Column(Integer, default=0)
    warnings_count = Column(Integer, default=0)
    summary = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class NotificationMessage(Base):
    __tablename__ = "notification_messages"
    id = Column(Integer, primary_key=True, index=True)
    message_no = Column(String(50), unique=True, index=True)
    message_type = Column(String(30), nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text)
    target_roles = Column(JSON)
    target_user_ids = Column(JSON)
    related_business_type = Column(String(30))
    related_business_id = Column(Integer)
    is_read = Column(Boolean, default=False)
    pushed_at = Column(DateTime)
    read_at = Column(DateTime)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


class DownstreamWaterUser(Base):
    __tablename__ = "downstream_water_users"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    monitor_section_id = Column(Integer, ForeignKey("ecological_flow_monitors.id"))
    daily_intake_quota = Column(Float)
    current_intake = Column(Float, default=0.0)
    priority_level = Column(Integer, default=5)
    created_at = Column(DateTime, default=datetime.utcnow)
