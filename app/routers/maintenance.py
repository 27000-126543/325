from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, date, timedelta
import uuid
import json

from app.database import get_db
from app.models import (
    WaterProject, MaintenanceTeam, MaintenanceTask, MaintenanceStatus
)
from app.schemas import (
    ProjectCreate, ProjectOut, MaintenanceTaskOut, MaintenanceComplete,
    ResponseModel, PaginatedResponse
)
from app.services import NotificationService

router = APIRouter(prefix="/api/v1/maintenance", tags=["7.Maintenance"])


def generate_task_no():
    return f"MT{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"


@router.post("/projects", response_model=ResponseModel, summary="创建水利工程（大坝、渠道）")
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    existing = db.query(WaterProject).filter(WaterProject.code == data.code).first()
    if existing:
        raise HTTPException(400, "工程编码已存在")
    p = WaterProject(**data.model_dump())
    if not p.next_maintenance_date and p.built_date:
        p.next_maintenance_date = p.built_date + timedelta(days=p.maintenance_cycle_days)
    elif not p.next_maintenance_date:
        p.next_maintenance_date = date.today() + timedelta(days=p.maintenance_cycle_days)
    db.add(p)
    db.commit()
    db.refresh(p)
    return ResponseModel(data=ProjectOut.model_validate(p).model_dump())


@router.get("/projects", response_model=PaginatedResponse, summary="水利工程列表")
def list_projects(
    project_type: Optional[str] = None, basin: Optional[str] = None,
    health_status: Optional[str] = None, need_maintenance: bool = False,
    page: int = 1, page_size: int = 20, db: Session = Depends(get_db)
):
    q = db.query(WaterProject)
    if project_type:
        q = q.filter(WaterProject.project_type == project_type)
    if basin:
        q = q.filter(WaterProject.basin == basin)
    if health_status:
        q = q.filter(WaterProject.health_status == health_status)
    if need_maintenance:
        today = date.today()
        q = q.filter(WaterProject.next_maintenance_date <= today)
    total = q.count()
    items = q.order_by(WaterProject.next_maintenance_date.asc()).offset((page-1)*page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        data=[ProjectOut.model_validate(i) for i in items]
    )


@router.post("/teams", response_model=ResponseModel, summary="创建维修班组")
def create_team(
    name: str, code: str, region: Optional[str] = None,
    team_leader: Optional[str] = None, phone: Optional[str] = None,
    member_count: int = 0, skills: Optional[List[str]] = None,
    coverage_area: Optional[str] = None, db: Session = Depends(get_db)
):
    existing = db.query(MaintenanceTeam).filter(MaintenanceTeam.code == code).first()
    if existing:
        raise HTTPException(400, "班组编码已存在")
    t = MaintenanceTeam(
        name=name, code=code, region=region, team_leader=team_leader,
        phone=phone, member_count=member_count,
        skills=json.dumps(skills) if skills else None,
        coverage_area=coverage_area
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return ResponseModel(data={
        "id": t.id, "name": t.name, "code": t.code, "team_leader": t.team_leader
    })


@router.get("/teams", response_model=ResponseModel, summary="维修班组列表")
def list_teams(region: Optional[str] = None, skill: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(MaintenanceTeam)
    if region:
        q = q.filter(MaintenanceTeam.region == region)
    teams = q.all()
    result = []
    for t in teams:
        s = json.loads(t.skills) if t.skills else []
        if skill and skill not in s:
            continue
        result.append({
            "id": t.id, "name": t.name, "code": t.code, "region": t.region,
            "team_leader": t.team_leader, "phone": t.phone,
            "member_count": t.member_count, "skills": s,
            "coverage_area": t.coverage_area, "current_workload": t.current_workload
        })
    return ResponseModel(data=result)


@router.post("/generate-tasks", response_model=ResponseModel, summary="检查维护周期到期自动生成保养任务并分配班组")
def generate_due_tasks(db: Session = Depends(get_db)):
    today = date.today()
    due_projects = db.query(WaterProject).filter(
        WaterProject.next_maintenance_date <= today
    ).all()

    tasks = []
    teams = db.query(MaintenanceTeam).all()

    for p in due_projects:
        existing = db.query(MaintenanceTask).filter(
            MaintenanceTask.project_id == p.id,
            MaintenanceTask.status.in_([
                MaintenanceStatus.PENDING,
                MaintenanceStatus.ASSIGNED,
                MaintenanceStatus.IN_PROGRESS
            ])
        ).first()
        if existing:
            continue

        required_skills = []
        task_type = "routine"
        priority = 3
        duration_hours = 4.0
        description = ""

        if p.project_type == "dam":
            required_skills = ["结构检测", "防渗处理", "闸门维护"]
            task_type = "大坝检修"
            priority = 1
            duration_hours = 8.0
            description = "大坝结构安全检查：坝体渗漏监测、闸门启闭测试、溢洪道清淤、边坡稳定性检查"
        elif p.project_type == "channel":
            required_skills = ["清淤疏浚", "衬砌修复"]
            task_type = "渠道养护"
            priority = 2
            duration_hours = 6.0
            description = "渠道维护：清淤疏浚、衬砌修复、闸门除锈润滑、量水设施校准"
        elif p.project_type == "pumping_station":
            required_skills = ["机电维修", "自动化控制"]
            task_type = "泵站维保"
            duration_hours = 8.0
            description = "泵站维护：水泵机组检修、电气系统检测、控制柜清洁保养"
        elif p.project_type == "gate":
            required_skills = ["机械维修", "液压系统"]
            task_type = "闸站检修"
            priority = 2
            description = "闸站维护：门体除锈防腐、启闭机润滑、液压系统检测、止水橡胶更换"

        best_team = None
        best_score = -1
        for t in teams:
            t_skills = json.loads(t.skills) if t.skills else []
            skill_match = sum(1 for s in required_skills if s in t_skills) / max(len(required_skills), 1)
            region_match = 1.0 if p.region and t.region and p.region == t.region else 0.3
            workload_bonus = max(0, 1 - (t.current_workload or 0) / 10)
            score = skill_match * 0.5 + region_match * 0.3 + workload_bonus * 0.2
            if score > best_score:
                best_score = score
                best_team = t

        scheduled = today + timedelta(days=3)

        task = MaintenanceTask(
            task_no=generate_task_no(),
            project_id=p.id,
            task_type=task_type,
            required_skills=json.dumps(required_skills),
            priority=priority,
            description=description,
            expected_duration_hours=duration_hours,
            status=MaintenanceStatus.ASSIGNED if best_team else MaintenanceStatus.PENDING,
            assigned_team_id=best_team.id if best_team else None,
            scheduled_date=scheduled
        )
        db.add(task)

        if best_team:
            best_team.current_workload = (best_team.current_workload or 0) + duration_hours

        tasks.append(task)

    db.commit()
    for t in tasks:
        db.refresh(t)
        team = db.query(MaintenanceTeam).filter(
            MaintenanceTeam.id == t.assigned_team_id
        ).first() if t.assigned_team_id else None
        NotificationService.notify_maintenance(
            db, t.id,
            f"新维护任务: {t.task_no}",
            f"工程ID:{t.project_id} 类型:{t.task_type} 优先级:{t.priority} "
            f"{'已分配班组:' + team.name if team else '待分配班组'} 计划日期:{t.scheduled_date}"
        )

    return ResponseModel(data={
        "generated_count": len(tasks),
        "tasks": [MaintenanceTaskOut.model_validate(t).model_dump() for t in tasks]
    })


@router.get("/tasks", response_model=PaginatedResponse, summary="维护任务列表")
def list_tasks(
    status: Optional[MaintenanceStatus] = None,
    project_id: Optional[int] = None, assigned_team_id: Optional[int] = None,
    priority_ge: Optional[int] = None, page: int = 1, page_size: int = 20,
    db: Session = Depends(get_db)
):
    q = db.query(MaintenanceTask)
    if status:
        q = q.filter(MaintenanceTask.status == status)
    if project_id:
        q = q.filter(MaintenanceTask.project_id == project_id)
    if assigned_team_id:
        q = q.filter(MaintenanceTask.assigned_team_id == assigned_team_id)
    if priority_ge:
        q = q.filter(MaintenanceTask.priority <= priority_ge)
    total = q.count()
    items = q.order_by(MaintenanceTask.priority.asc(), MaintenanceTask.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        data=[MaintenanceTaskOut.model_validate(i) for i in items]
    )


@router.put("/tasks/{task_id}/assign", response_model=ResponseModel, summary="手动分配任务至班组")
def assign_task(task_id: int, team_id: int, scheduled_date: Optional[date] = None,
                assignee_id: Optional[int] = None, db: Session = Depends(get_db)):
    task = db.query(MaintenanceTask).filter(MaintenanceTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    team = db.query(MaintenanceTeam).filter(MaintenanceTeam.id == team_id).first()
    if not team:
        raise HTTPException(404, "班组不存在")

    task.assigned_team_id = team_id
    task.assignee_id = assignee_id
    task.scheduled_date = scheduled_date or task.scheduled_date or date.today()
    task.status = MaintenanceStatus.ASSIGNED

    db.commit()
    db.refresh(task)

    NotificationService.notify_maintenance(
        db, task.id,
        f"维护任务已分配: {task.task_no}",
        f"分配至班组[{team.name}]，计划日期:{task.scheduled_date}"
    )

    return ResponseModel(data=MaintenanceTaskOut.model_validate(task).model_dump())


@router.put("/tasks/{task_id}/start", response_model=ResponseModel, summary="开始维护作业")
def start_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(MaintenanceTask).filter(MaintenanceTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status not in (MaintenanceStatus.ASSIGNED, MaintenanceStatus.PENDING):
        raise HTTPException(400, f"当前状态{task.status.value}不可开始")
    task.status = MaintenanceStatus.IN_PROGRESS
    task.start_time = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return ResponseModel(data=MaintenanceTaskOut.model_validate(task).model_dump())


@router.post("/tasks/complete", response_model=ResponseModel, summary="完成维护作业并更新设备台账")
def complete_task(data: MaintenanceComplete, db: Session = Depends(get_db)):
    task = db.query(MaintenanceTask).filter(MaintenanceTask.id == data.task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status != MaintenanceStatus.IN_PROGRESS:
        raise HTTPException(400, f"当前状态{task.status.value}不可完成")

    task.status = MaintenanceStatus.COMPLETED
    task.complete_time = datetime.utcnow()
    task.maintenance_report = data.report
    task.parts_used = json.dumps(data.parts_used) if data.parts_used else None

    if task.assigned_team_id:
        team = db.query(MaintenanceTeam).filter(
            MaintenanceTeam.id == task.assigned_team_id
        ).first()
        if team:
            team.current_workload = max(0, (team.current_workload or 0) - (task.expected_duration_hours or 0))

    project = db.query(WaterProject).filter(WaterProject.id == task.project_id).first()
    ledger_updated = False
    if project:
        today = date.today()
        project.last_maintenance_date = today
        project.next_maintenance_date = today + timedelta(days=project.maintenance_cycle_days)

        specs = json.loads(project.specifications) if project.specifications else {}
        history = specs.get("maintenance_history", [])
        history.append({
            "task_id": task.id,
            "date": today.isoformat(),
            "type": task.task_type,
            "report": data.report[:200],
            "parts": data.parts_used or []
        })
        specs["maintenance_history"] = history[-20:]
        project.specifications = json.dumps(specs)

        health_score = 0.85
        if "渗漏" in data.report or "裂纹" in data.report or "严重" in data.report:
            health_score = 0.6
        if "正常" in data.report or "良好" in data.report:
            health_score = 0.95
        if health_score >= 0.8:
            project.health_status = "normal"
        elif health_score >= 0.6:
            project.health_status = "attention"
        else:
            project.health_status = "fault"

        task.ledger_updated = True
        ledger_updated = True

    db.commit()
    db.refresh(task)

    NotificationService.notify_maintenance(
        db, task.id,
        f"维护任务已完成: {task.task_no}",
        f"设备台账已{'更新' if ledger_updated else '待更新'}。下次维护日期: {project.next_maintenance_date if project else '未知'}"
    )

    return ResponseModel(data={
        "task": MaintenanceTaskOut.model_validate(task).model_dump(),
        "ledger_updated": ledger_updated,
        "project_health": project.health_status if project else None,
        "next_maintenance": project.next_maintenance_date.isoformat() if project and project.next_maintenance_date else None
    })


@router.put("/tasks/{task_id}/verify", response_model=ResponseModel, summary="工程管理员验收")
def verify_task(task_id: int, verifier_id: int, passed: bool = True,
                verification_note: Optional[str] = None, db: Session = Depends(get_db)):
    task = db.query(MaintenanceTask).filter(MaintenanceTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status != MaintenanceStatus.COMPLETED:
        raise HTTPException(400, "任务未完成")

    if passed:
        task.status = MaintenanceStatus.VERIFIED
    task.verified_by = verifier_id
    db.commit()
    db.refresh(task)
    return ResponseModel(data=MaintenanceTaskOut.model_validate(task).model_dump())
