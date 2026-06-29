from datetime import datetime
from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError, jwt
import asyncio

from app.database import get_db, AsyncSessionLocal
from app.auth import get_current_user
from app.config import settings
from app.models.user import User
from app.models.chat import Conversation, ConversationMember, Message, ConversationType

router = APIRouter(prefix="/chat", tags=["chat"])
templates = Jinja2Templates(directory="app/templates")

# websocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active: dict[int, list[WebSocket]] = {}  # conv_id -> list of ws

    async def connect(self, ws: WebSocket, conv_id: int):
        await ws.accept()
        self.active.setdefault(conv_id, []).append(ws)

    def disconnect(self, ws: WebSocket, conv_id: int):
        conns = self.active.get(conv_id, [])
        if ws in conns:
            conns.remove(ws)

    async def broadcast(self, conv_id: int, data: dict):
        for ws in list(self.active.get(conv_id, [])):
            try:
                await ws.send_json(data)
            except Exception:
                pass


manager = ConnectionManager()


async def _get_or_create_general(db: AsyncSession, venue_id: int) -> Conversation:
    result = await db.execute(
        select(Conversation).where(
            Conversation.venue_id == venue_id,
            Conversation.type == ConversationType.general,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        conv = Conversation(type=ConversationType.general, name="Общий чат", venue_id=venue_id)
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
    return conv


async def _get_or_create_direct(db: AsyncSession, user1_id: int, user2_id: int, venue_id: int) -> Conversation:
    subq1 = select(ConversationMember.conversation_id).where(ConversationMember.user_id == user1_id)
    subq2 = select(ConversationMember.conversation_id).where(ConversationMember.user_id == user2_id)

    result = await db.execute(
        select(Conversation).where(
            Conversation.type == ConversationType.direct,
            Conversation.venue_id == venue_id,
            Conversation.id.in_(subq1),
            Conversation.id.in_(subq2),
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        conv = Conversation(type=ConversationType.direct, venue_id=venue_id)
        db.add(conv)
        await db.flush()
        db.add(ConversationMember(conversation_id=conv.id, user_id=user1_id))
        db.add(ConversationMember(conversation_id=conv.id, user_id=user2_id))
        await db.commit()
        await db.refresh(conv)
    return conv


@router.get("", response_class=HTMLResponse)
async def chat_index(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    general = await _get_or_create_general(db, user.venue_id)

    staff_result = await db.execute(
        select(User).where(User.venue_id == user.venue_id, User.id != user.id)
    )
    colleagues = staff_result.scalars().all()

    return templates.TemplateResponse("chat/index.html", {
        "request": request,
        "user": user,
        "general_id": general.id,
        "colleagues": colleagues,
    })


@router.get("/messages/{conv_id}")
async def get_messages(conv_id: int, request: Request, before_id: int = 0, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    query = (
        select(Message)
        .options(selectinload(Message.sender))
        .where(Message.conversation_id == conv_id, Message.is_deleted == False)
        .order_by(Message.created_at.desc())
        .limit(50)
    )
    if before_id:
        query = query.where(Message.id < before_id)

    result = await db.execute(query)
    messages = result.scalars().all()

    member_result = await db.execute(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conv_id,
            ConversationMember.user_id == user.id,
        )
    )
    member = member_result.scalar_one_or_none()
    if member:
        member.last_read_at = datetime.utcnow()
        await db.commit()

    return JSONResponse([{
        "id": m.id,
        "text": m.text,
        "sender_id": m.sender_id,
        "sender_name": m.sender.name,
        "sender_initials": m.sender.initials,
        "sender_color": m.sender.avatar_color,
        "created_at": m.created_at.strftime("%H:%M"),
        "is_mine": m.sender_id == user.id,
    } for m in reversed(messages)])


@router.get("/unread")
async def get_unread(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    member_result = await db.execute(
        select(ConversationMember).where(ConversationMember.user_id == user.id)
    )
    members = member_result.scalars().all()

    total_unread = 0
    for m in members:
        count_result = await db.execute(
            select(func.count(Message.id)).where(
                Message.conversation_id == m.conversation_id,
                Message.created_at > m.last_read_at,
                Message.sender_id != user.id,
                Message.is_deleted == False,
            )
        )
        total_unread += count_result.scalar() or 0

    return JSONResponse({"unread": total_unread})


@router.get("/direct/{colleague_id}")
async def get_direct_conv(colleague_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    conv = await _get_or_create_direct(db, user.id, colleague_id, user.venue_id)
    return JSONResponse({"conv_id": conv.id})


@router.websocket("/ws/{conv_id}")
async def websocket_endpoint(ws: WebSocket, conv_id: int, token: str = ""):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, Exception):
        await ws.close(code=4001)
        return

    await manager.connect(ws, conv_id)
    try:
        while True:
            data = await ws.receive_json()
            text = data.get("text", "").strip()
            if not text:
                continue

            async with AsyncSessionLocal() as db:
                user_result = await db.execute(select(User).where(User.id == user_id))
                user = user_result.scalar_one_or_none()
                if not user:
                    break

                msg = Message(conversation_id=conv_id, sender_id=user_id, text=text)
                db.add(msg)
                await db.commit()
                await db.refresh(msg)

            await manager.broadcast(conv_id, {
                "id": msg.id,
                "text": msg.text,
                "sender_id": user_id,
                "sender_name": user.name,
                "sender_initials": user.initials,
                "sender_color": user.avatar_color,
                "created_at": msg.created_at.strftime("%H:%M"),
            })
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws, conv_id)
