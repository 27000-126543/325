from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from sqlalchemy.orm import Session
from app.models import NotificationMessage, UserRole, CropType
from app import models
import uuid
import json
import logging
import asyncio

logger = logging.getLogger(__name__)


def _safe_json_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            p = json.loads(v)
            return p if isinstance(p, list) else []
        except (ValueError, TypeError):
            return []
    return []


class NotificationService:
    manager = None
    loop = None

    @staticmethod
    def generate_message_no():
        return f"MSG{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"

    @staticmethod
    def _run_coro(coro):
        if NotificationService.loop is None or NotificationService.manager is None:
            return False
        try:
            loop = NotificationService.loop
            if not loop.is_running():
                return False

            def _submit():
                try:
                    t = asyncio.ensure_future(coro, loop=loop)
                    def _log_done(f):
                        try:
                            f.result()
                        except Exception as _ex:
                            logger.warning(f"WS push coro err: {_ex}")
                    t.add_done_callback(_log_done)
                except Exception as _e:
                    logger.warning(f"submit WS coro err: {_e}")

            loop.call_soon_threadsafe(_submit)
            return True
        except Exception as _e:
            logger.warning(f"_run_coro err: {_e}")
            return False

    @staticmethod
    def _dispatch_ws_push(msg: NotificationMessage):
        if NotificationService.manager is None:
            return
        roles = _safe_json_list(msg.target_roles)
        user_ids = _safe_json_list(msg.target_user_ids)
        payload = {
            "type": "notification",
            "message_type": msg.message_type,
            "title": msg.title,
            "content": msg.content,
            "message_id": msg.id,
            "message_no": msg.message_no,
            "related_business_type": msg.related_business_type,
            "related_business_id": msg.related_business_id
        }
        if roles:
            NotificationService._run_coro(
                NotificationService.manager.push_to_roles(roles, dict(payload))
            )
        if user_ids:
            NotificationService._run_coro(
                NotificationService.manager.push_to_users(user_ids, dict(payload))
            )
        if not roles and not user_ids:
            NotificationService._run_coro(
                NotificationService.manager.push_to_all(dict(payload))
            )

    @staticmethod
    def create_notification(
        db: Session,
        message_type: str,
        title: str,
        content: str = "",
        target_roles: Optional[List[str]] = None,
        target_user_ids: Optional[List[int]] = None,
        related_business_type: Optional[str] = None,
        related_business_id: Optional[int] = None,
        created_by: Optional[int] = None
    ) -> NotificationMessage:
        msg = NotificationMessage(
            message_no=NotificationService.generate_message_no(),
            message_type=message_type,
            title=title,
            content=content,
            target_roles=target_roles if target_roles else None,
            target_user_ids=target_user_ids if target_user_ids else None,
            related_business_type=related_business_type,
            related_business_id=related_business_id,
            pushed_at=datetime.utcnow(),
            created_by=created_by
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        logger.info(f"Notification created: {title}")
        NotificationService._dispatch_ws_push(msg)
        return msg

    @staticmethod
    def notify_dispatch(db: Session, instruction_id: int, title: str, content: str):
        return NotificationService.create_notification(
            db,
            message_type="DISPATCH",
            title=title,
            content=content,
            target_roles=[UserRole.BASIN_MANAGER, UserRole.WATER_ADMIN],
            related_business_type="dispatch_instruction",
            related_business_id=instruction_id
        )

    @staticmethod
    def notify_irrigation(db: Session, app_id: int, title: str, content: str, user_id: Optional[int] = None):
        targets = [UserRole.AGRI_OFFICER]
        user_ids = [user_id] if user_id else None
        return NotificationService.create_notification(
            db,
            message_type="IRRIGATION",
            title=title,
            content=content,
            target_roles=targets,
            target_user_ids=user_ids,
            related_business_type="irrigation_application",
            related_business_id=app_id
        )

    @staticmethod
    def notify_water_quality(db: Session, work_order_id: int, title: str, content: str):
        return NotificationService.create_notification(
            db,
            message_type="WATER_QUALITY",
            title=title,
            content=content,
            target_roles=[UserRole.ENV_OFFICER, UserRole.BASIN_MANAGER],
            related_business_type="traceability_work_order",
            related_business_id=work_order_id
        )

    @staticmethod
    def notify_ecological(db: Session, monitor_id: int, title: str, content: str, user_ids: Optional[List[int]] = None):
        return NotificationService.create_notification(
            db,
            message_type="ECOLOGICAL",
            title=title,
            content=content,
            target_roles=[UserRole.WATER_ADMIN, UserRole.BASIN_MANAGER],
            target_user_ids=user_ids,
            related_business_type="ecological_flow",
            related_business_id=monitor_id
        )

    @staticmethod
    def notify_trade(db: Session, contract_id: int, title: str, content: str, user_ids: Optional[List[int]] = None):
        return NotificationService.create_notification(
            db,
            message_type="TRADE",
            title=title,
            content=content,
            target_roles=[UserRole.BASIN_MANAGER],
            target_user_ids=user_ids,
            related_business_type="trade_contract",
            related_business_id=contract_id
        )

    @staticmethod
    def notify_transfer(db: Session, transfer_id: int, title: str, content: str, is_reminder: bool = False):
        msg_type = "TRANSFER_REMINDER" if is_reminder else "TRANSFER"
        return NotificationService.create_notification(
            db,
            message_type=msg_type,
            title=title,
            content=content,
            target_roles=[UserRole.BASIN_MANAGER, UserRole.WATER_ADMIN],
            related_business_type="cross_region_transfer",
            related_business_id=transfer_id
        )

    @staticmethod
    def notify_maintenance(db: Session, task_id: int, title: str, content: str, team_id: Optional[int] = None):
        return NotificationService.create_notification(
            db,
            message_type="MAINTENANCE",
            title=title,
            content=content,
            target_roles=[UserRole.ENGINEER, UserRole.BASIN_MANAGER],
            related_business_type="maintenance_task",
            related_business_id=task_id
        )

    @staticmethod
    def notify_report(db: Session, report_id: int, title: str, content: str):
        return NotificationService.create_notification(
            db,
            message_type="REPORT",
            title=title,
            content=content,
            target_roles=[UserRole.ADMIN, UserRole.BASIN_MANAGER]
        )

    @staticmethod
    def get_unread_messages(db: Session, user_id: Optional[int] = None, role: Optional[str] = None, limit: int = 50):
        query = db.query(NotificationMessage).filter(NotificationMessage.is_read == False)
        results = []
        messages = query.order_by(NotificationMessage.created_at.desc()).limit(limit * 5).all()
        for msg in messages:
            roles = _safe_json_list(msg.target_roles)
            user_ids = _safe_json_list(msg.target_user_ids)
            roles_norm = [str(r).lower() for r in roles]
            include = False
            if role and str(role).lower() in roles_norm:
                include = True
            if user_id and user_id in user_ids:
                include = True
            if not roles and not user_ids:
                include = True
            if include:
                results.append(msg)
                if len(results) >= limit:
                    break
        return results


class DispatchAlgorithm:
    @staticmethod
    def calculate_storage_ratio(current_storage: float, max_capacity: float) -> float:
        if max_capacity <= 0:
            return 0.0
        return round(current_storage / max_capacity, 4)

    @staticmethod
    def predict_inflow(current_inflow: float, predicted_rainfall: float, basin_factor: float = 0.3) -> float:
        return round(current_inflow + predicted_rainfall * basin_factor, 2)

    @staticmethod
    def generate_scheme(
        current_storage: float,
        max_capacity: float,
        current_level: float,
        flood_limit: Optional[float],
        normal_level: Optional[float],
        current_inflow: float,
        predicted_rainfall: float,
        ecological_threshold: Optional[float] = None
    ) -> Dict:
        ratio = DispatchAlgorithm.calculate_storage_ratio(current_storage, max_capacity)
        predicted_inflow = DispatchAlgorithm.predict_inflow(current_inflow, predicted_rainfall)

        if ratio >= 0.9 or (flood_limit and current_level >= flood_limit * 0.95):
            risk = "high"
            action = "flood_release"
            target = round(max(current_inflow * 1.5, max_capacity * 0.05), 2)
            explanation = f"库容比{ratio:.2%}接近或超过汛限，需紧急泄洪，预计入流{predicted_inflow}m³/s"
        elif ratio >= 0.75 or predicted_rainfall >= 50:
            risk = "medium"
            action = "pre_release"
            target = round(max(current_inflow * 1.2, max_capacity * 0.02), 2)
            explanation = f"库容比{ratio:.2%}较高，预报降雨{predicted_rainfall}mm，建议预泄腾库"
        elif ratio <= 0.3 and predicted_rainfall < 10:
            risk = "low"
            action = "storage"
            target = round(max(ecological_threshold or current_inflow * 0.8, 0), 2)
            explanation = f"库容比{ratio:.2%}偏低，预报无明显降雨，建议拦蓄补源"
        else:
            risk = "normal"
            action = "regular"
            eco_min = ecological_threshold if ecological_threshold else 0
            target = round(max(eco_min, current_inflow * 0.95), 2)
            explanation = f"运行正常，库容比{ratio:.2%}，维持常规调度，保证生态流量"

        return {
            "current_storage_ratio": round(ratio, 4),
            "predicted_inflow": predicted_inflow,
            "recommended_action": action,
            "target_outflow": target,
            "risk_level": risk,
            "explanation": explanation
        }


class CropWaterRequirement:
    _crop_coefficients = {
        CropType.RICE: 0.85,
        CropType.WHEAT: 0.6,
        CropType.CORN: 0.65,
        CropType.VEGETABLE: 0.75,
        CropType.FRUIT: 0.7,
        CropType.OTHER: 0.65,
    }

    _water_demand_per_mu = {
        CropType.RICE: 300,
        CropType.WHEAT: 180,
        CropType.CORN: 200,
        CropType.VEGETABLE: 250,
        CropType.FRUIT: 220,
        CropType.OTHER: 200,
    }

    @classmethod
    def calculate_irrigation_need(
        cls,
        crop_type: CropType,
        area_mu: float,
        soil_moisture: Optional[float],
        field_capacity: Optional[float] = None
    ) -> Dict[str, Any]:
        base_demand = cls._water_demand_per_mu.get(crop_type, 200)
        coefficient = cls._crop_coefficients.get(crop_type, 0.65)
        theoretical = round(base_demand * area_mu * coefficient, 2)

        moisture_factor = 1.0
        if soil_moisture is not None:
            fc = field_capacity if field_capacity and field_capacity > 0 else 30
            ratio = soil_moisture / fc
            if ratio < 0.5:
                moisture_factor = 1.3
            elif ratio < 0.7:
                moisture_factor = 1.1
            elif ratio > 0.85:
                moisture_factor = 0.7

        recommended = round(theoretical * moisture_factor, 2)

        suggestions = []
        if moisture_factor > 1.1:
            suggestions.append("墒情不足，建议采用滴灌/喷灌节水技术，可节水20-30%")
        if crop_type == CropType.RICE:
            suggestions.append("水稻建议采用浅湿灌溉模式，避免深水漫灌")
        elif crop_type == CropType.VEGETABLE:
            suggestions.append("蔬菜建议采用地膜覆盖，减少蒸发损失")
        if area_mu > 100:
            suggestions.append("大面积灌溉建议分批次轮灌，提高用水效率")

        return {
            "theoretical_demand": theoretical,
            "recommended_amount": recommended,
            "moisture_factor": moisture_factor,
            "saving_suggestions": suggestions
        }
