from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime
import json

from app.database import get_db
from app.models import NotificationMessage, UserRole
from app.schemas import NotificationOut, ResponseModel, PaginatedResponse
from app.services import NotificationService as _NotificationService

router = APIRouter(tags=["9.Notifications"])

active_connections: List[WebSocket] = []


async def broadcast_message(message: dict):
    for ws in active_connections:
        try:
            await ws.send_json(message)
        except Exception:
            pass


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        for ws in list(self.active_connections.values()):
            try:
                await ws.send_json({
                    "type": "system",
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": {"online": len(self.active_connections)}
                })
            except Exception:
                pass

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]

    async def push_to_all(self, message: dict):
        payload = {
            **message,
            "timestamp": datetime.utcnow().isoformat()
        }
        dead = []
        for cid, ws in self.active_connections.items():
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(cid)
        for cid in dead:
            self.disconnect(cid)

    async def push_to_roles(self, roles: List[str], message: dict):
        payload = {
            **message,
            "target_roles": roles,
            "timestamp": datetime.utcnow().isoformat()
        }
        dead = []
        for cid, ws in self.active_connections.items():
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(cid)
        for cid in dead:
            self.disconnect(cid)

    async def push_to_users(self, user_ids: List[int], message: dict):
        payload = {
            **message,
            "target_user_ids": user_ids,
            "timestamp": datetime.utcnow().isoformat()
        }
        dead = []
        for cid, ws in self.active_connections.items():
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(cid)
        for cid in dead:
            self.disconnect(cid)


manager = ConnectionManager()

def _safe_json_list(v):
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

_NotificationService.manager = manager


@router.websocket("/ws/notifications")
async def notification_websocket(
    websocket: WebSocket,
    client_id: str = Query(..., description="瀹㈡埛绔敮涓€鏍囪瘑"),
    role: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None)
):
    await manager.connect(websocket, client_id)
    try:
        db = next(get_db())
        unread = _NotificationService.get_unread_messages(
            db, user_id=user_id, role=role, limit=20
        )
        if unread:
            await websocket.send_json({
                "type": "unread_list",
                "timestamp": datetime.utcnow().isoformat(),
                "data": [NotificationOut.model_validate(m).model_dump(mode="json") for m in unread]
            })

        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    })
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(client_id)


@router.get("/api/v1/notifications", response_model=PaginatedResponse, tags=["9.Notifications"])
def list_notifications(
    message_type: Optional[str] = None, is_read: Optional[bool] = None,
    related_business_type: Optional[str] = None,
    page: int = 1, page_size: int = 50, db: Session = Depends(get_db)
):
    q = db.query(NotificationMessage)
    if message_type:
        q = q.filter(NotificationMessage.message_type == message_type)
    if is_read is not None:
        q = q.filter(NotificationMessage.is_read == is_read)
    if related_business_type:
        q = q.filter(NotificationMessage.related_business_type == related_business_type)
    total = q.count()
    items = q.order_by(NotificationMessage.created_at.desc()).offset((page-1)*page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        data=[NotificationOut.model_validate(i) for i in items]
    )


@router.get("/api/v1/notifications/unread", response_model=ResponseModel, tags=["9.Notifications"])
def get_unread(user_id: Optional[int] = None, role: Optional[str] = None,
               limit: int = 50, db: Session = Depends(get_db)):
    msgs = _NotificationService.get_unread_messages(db, user_id=user_id, role=role, limit=limit)
    return ResponseModel(data={
        "count": len(msgs),
        "messages": [NotificationOut.model_validate(m).model_dump(mode="json") for m in msgs]
    })


@router.put("/api/v1/notifications/{msg_id}/read", response_model=ResponseModel, tags=["9.Notifications"])
def mark_read(msg_id: int, db: Session = Depends(get_db)):
    msg = db.query(NotificationMessage).filter(NotificationMessage.id == msg_id).first()
    if not msg:
        raise HTTPException(404, "消息不存在")
    msg.is_read = True
    msg.read_at = datetime.utcnow()
    db.commit()
    return ResponseModel(message="已标记已读")


@router.put("/api/v1/notifications/read-all", response_model=ResponseModel, tags=["9.Notifications"])
def mark_all_read(user_id: Optional[int] = None, role: Optional[str] = None,
                  db: Session = Depends(get_db)):
    all_unread = db.query(NotificationMessage).filter(NotificationMessage.is_read == False).all()
    to_mark = []
    for m in all_unread:
        roles = _safe_json_list(m.target_roles)
        user_ids = _safe_json_list(m.target_user_ids)
        roles_norm = [str(r).lower() for r in roles]
        hit = False
        if not roles and not user_ids:
            hit = True
        if user_id and user_id in user_ids:
            hit = True
        if role and str(role).lower() in roles_norm:
            hit = True
        if hit:
            to_mark.append(m)
    marked_count = 0
    now = datetime.utcnow()
    for m in to_mark:
        if not m.is_read:
            m.is_read = True
            m.read_at = now
            marked_count += 1
    db.commit()
    return ResponseModel(data={"marked_count": marked_count})


@router.post("/api/v1/notifications/push", response_model=ResponseModel, tags=["9.Notifications"])
async def manual_push(
    title: str, content: str = "",
    target_roles: Optional[str] = Query(None, description="逗号分隔角色"),
    target_user_ids: Optional[str] = Query(None, description="逗号分隔用户ID"),
    message_type: str = "SYSTEM",
    db: Session = Depends(get_db)
):
    role_list = [r.strip() for r in target_roles.split(",")] if target_roles else None
    user_list = [int(u.strip()) for u in target_user_ids.split(",")] if target_user_ids else None

    msg = _NotificationService.create_notification(
        db, message_type=message_type, title=title, content=content,
        target_roles=role_list, target_user_ids=user_list
    )

    await manager.push_to_all({
        "type": "notification",
        "message_type": message_type,
        "title": title,
        "content": content,
        "message_id": msg.id
    })

    return ResponseModel(data={"message_id": msg.id})

