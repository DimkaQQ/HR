from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError, jwt

from app.database import get_db, AsyncSessionLocal
from app.auth import get_current_user
from app.config import settings
from app.models.user import User
from app.models.chat import Conversation, ConversationMember, Message, ConversationType

router = APIRouter(prefix="/chat", tags=["chat"])
templates = Jinja2Templates(directory="app/templates")


# ── Connection Manager ────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self._conns: dict[int, list[WebSocket]] = {}

    async def connect(self, ws: WebSocket, user_id: int):
        await ws.accept()
        self._conns.setdefault(user_id, []).append(ws)

    def disconnect(self, ws: WebSocket, user_id: int):
        conns = self._conns.get(user_id, [])
        if ws in conns:
            conns.remove(ws)
        if not conns:
            self._conns.pop(user_id, None)

    def is_online(self, user_id: int) -> bool:
        return bool(self._conns.get(user_id))

    def online_ids(self) -> set[int]:
        return {uid for uid, c in self._conns.items() if c}

    async def send(self, user_id: int, data: dict):
        dead = []
        for ws in list(self._conns.get(user_id, [])):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, user_id)

    async def broadcast(self, user_ids: list[int] | set[int], data: dict):
        for uid in user_ids:
            await self.send(uid, data)


manager = ConnectionManager()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _msg_payload(msg: Message, reply: Optional[Message] = None) -> dict:
    sender = msg.sender
    reply_data = None
    if reply:
        rs = reply.sender
        reply_data = {
            "id": reply.id,
            "sender_name": rs.name if rs else "?",
            "text": ("Сообщение удалено" if reply.is_deleted else reply.text[:120]),
        }
    return {
        "type": "message",
        "id": msg.id,
        "conv_id": msg.conversation_id,
        "text": ("Сообщение удалено" if msg.is_deleted else msg.text),
        "sender_id": msg.sender_id,
        "sender_name": sender.name if sender else "?",
        "sender_initials": sender.initials if sender else "??",
        "sender_color": sender.avatar_color if sender else "#C8A84B",
        "sender_role": sender.role.value if sender else "staff",
        "created_at": msg.created_at.isoformat(),
        "is_deleted": msg.is_deleted,
        "reply_to_id": msg.reply_to_id,
        "reply_to": reply_data,
    }


async def _conv_member_ids(db: AsyncSession, conv: Conversation, venue_id: int) -> list[int]:
    if conv.type == ConversationType.general:
        r = await db.execute(select(User.id).where(User.venue_id == venue_id))
        return [row[0] for row in r.all()]
    r = await db.execute(
        select(ConversationMember.user_id).where(ConversationMember.conversation_id == conv.id)
    )
    return [row[0] for row in r.all()]


async def _ensure_general(db: AsyncSession, venue_id: int) -> Conversation:
    r = await db.execute(
        select(Conversation).where(
            Conversation.venue_id == venue_id,
            Conversation.type == ConversationType.general,
        )
    )
    conv = r.scalar_one_or_none()
    if not conv:
        conv = Conversation(type=ConversationType.general, name="Общий чат", venue_id=venue_id)
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
    return conv


async def _ensure_direct(db: AsyncSession, uid1: int, uid2: int, venue_id: int) -> Conversation:
    sq1 = select(ConversationMember.conversation_id).where(ConversationMember.user_id == uid1)
    sq2 = select(ConversationMember.conversation_id).where(ConversationMember.user_id == uid2)
    r = await db.execute(
        select(Conversation).where(
            Conversation.type == ConversationType.direct,
            Conversation.venue_id == venue_id,
            Conversation.id.in_(sq1),
            Conversation.id.in_(sq2),
        )
    )
    conv = r.scalar_one_or_none()
    if not conv:
        conv = Conversation(type=ConversationType.direct, venue_id=venue_id)
        db.add(conv)
        await db.flush()
        db.add(ConversationMember(conversation_id=conv.id, user_id=uid1))
        db.add(ConversationMember(conversation_id=conv.id, user_id=uid2))
        await db.commit()
        await db.refresh(conv)
    return conv


async def _ensure_member(db: AsyncSession, conv_id: int, user_id: int) -> ConversationMember:
    r = await db.execute(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conv_id,
            ConversationMember.user_id == user_id,
        )
    )
    m = r.scalar_one_or_none()
    if not m:
        m = ConversationMember(conversation_id=conv_id, user_id=user_id, last_read_at=datetime.utcnow())
        db.add(m)
        await db.commit()
    return m


# ── HTTP Endpoints ────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def chat_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    return templates.TemplateResponse("chat/index.html", {"request": request, "user": user})


@router.get("/conversations")
async def list_conversations(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    general = await _ensure_general(db, user.venue_id)

    # My memberships
    mr = await db.execute(
        select(ConversationMember).where(ConversationMember.user_id == user.id)
    )
    my_memberships = {m.conversation_id: m for m in mr.scalars().all()}

    async def _last_msg(conv_id: int):
        r = await db.execute(
            select(Message)
            .options(selectinload(Message.sender))
            .where(Message.conversation_id == conv_id, Message.is_deleted.is_(False))
            .order_by(desc(Message.created_at))
            .limit(1)
        )
        return r.scalar_one_or_none()

    async def _unread(conv_id: int, last_read: datetime) -> int:
        r = await db.execute(
            select(func.count(Message.id)).where(
                Message.conversation_id == conv_id,
                Message.created_at > last_read,
                Message.sender_id != user.id,
                Message.is_deleted.is_(False),
            )
        )
        return r.scalar() or 0

    result = []

    # General chat
    gm = my_memberships.get(general.id)
    if not gm:
        gm = await _ensure_member(db, general.id, user.id)

    g_last = await _last_msg(general.id)
    result.append({
        "id": general.id,
        "type": "general",
        "name": "Общий чат",
        "initials": "#",
        "color": "#C8A84B",
        "partner_id": None,
        "online": True,
        "last_seen": None,
        "unread_count": await _unread(general.id, gm.last_read_at),
        "last_message": _fmt_last(g_last, user.id) if g_last else None,
    })

    # Colleagues → DMs
    cr = await db.execute(
        select(User).where(User.venue_id == user.venue_id, User.id != user.id).order_by(User.name)
    )
    for colleague in cr.scalars().all():
        sq1 = select(ConversationMember.conversation_id).where(ConversationMember.user_id == user.id)
        sq2 = select(ConversationMember.conversation_id).where(ConversationMember.user_id == colleague.id)
        dr = await db.execute(
            select(Conversation).where(
                Conversation.type == ConversationType.direct,
                Conversation.venue_id == user.venue_id,
                Conversation.id.in_(sq1),
                Conversation.id.in_(sq2),
            )
        )
        dm = dr.scalar_one_or_none()
        dm_last = await _last_msg(dm.id) if dm else None
        dm_mem = my_memberships.get(dm.id) if dm else None

        result.append({
            "id": dm.id if dm else None,
            "type": "direct",
            "name": colleague.name,
            "initials": colleague.initials,
            "color": colleague.avatar_color,
            "partner_id": colleague.id,
            "partner_role": colleague.role.value,
            "online": manager.is_online(colleague.id),
            "last_seen": colleague.last_seen.isoformat() if colleague.last_seen else None,
            "unread_count": (await _unread(dm.id, dm_mem.last_read_at) if dm and dm_mem else 0),
            "last_message": _fmt_last(dm_last, user.id) if dm_last else None,
        })

    # Group conversations where user is a member
    gr = await db.execute(
        select(Conversation)
        .join(ConversationMember, ConversationMember.conversation_id == Conversation.id)
        .where(ConversationMember.user_id == user.id, Conversation.type == ConversationType.group)
    )
    for conv in gr.scalars().all():
        gm_mem = my_memberships.get(conv.id)
        if not gm_mem:
            gm_mem = await _ensure_member(db, conv.id, user.id)
        g_last = await _last_msg(conv.id)
        name = conv.name or "Группа"
        initials = name[:2].upper()
        result.append({
            "id": conv.id,
            "type": "group",
            "name": name,
            "initials": initials,
            "color": "#5B8FF9",
            "partner_id": None,
            "partner_role": None,
            "online": False,
            "last_seen": None,
            "unread_count": await _unread(conv.id, gm_mem.last_read_at),
            "last_message": _fmt_last(g_last, user.id) if g_last else None,
        })

    return JSONResponse(result)


def _fmt_last(msg: Message, viewer_id: int) -> dict:
    return {
        "text": ("Сообщение удалено" if msg.is_deleted else msg.text),
        "sender_name": msg.sender.name if msg.sender else "?",
        "created_at": msg.created_at.isoformat(),
        "is_mine": msg.sender_id == viewer_id,
    }


@router.get("/messages/{conv_id}")
async def get_messages(
    conv_id: int,
    request: Request,
    before_id: int = 0,
    limit: int = 40,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)

    q = (
        select(Message)
        .options(selectinload(Message.sender))
        .where(Message.conversation_id == conv_id)
        .order_by(desc(Message.id))
        .limit(limit)
    )
    if before_id:
        q = q.where(Message.id < before_id)

    r = await db.execute(q)
    messages = list(reversed(r.scalars().all()))

    # Load reply messages
    reply_ids = {m.reply_to_id for m in messages if m.reply_to_id}
    reply_map: dict[int, Message] = {}
    if reply_ids:
        rr = await db.execute(
            select(Message).options(selectinload(Message.sender)).where(Message.id.in_(reply_ids))
        )
        reply_map = {m.id: m for m in rr.scalars().all()}

    # Mark as read
    member = await _ensure_member(db, conv_id, user.id)
    member.last_read_at = datetime.utcnow()
    await db.commit()

    # Others' last_read_at for read-receipt on my messages
    or_ = await db.execute(
        select(ConversationMember.last_read_at).where(
            ConversationMember.conversation_id == conv_id,
            ConversationMember.user_id != user.id,
        )
    )
    others_reads = [row[0] for row in or_.all()]
    max_other_read = max(others_reads) if others_reads else None

    out = []
    for m in messages:
        p = _msg_payload(m, reply_map.get(m.reply_to_id) if m.reply_to_id else None)
        p["is_mine"] = m.sender_id == user.id
        p["read_by_others"] = bool(
            m.sender_id == user.id and max_other_read and max_other_read >= m.created_at
        )
        out.append(p)

    return JSONResponse(out)


@router.get("/unread")
async def total_unread(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    mr = await db.execute(select(ConversationMember).where(ConversationMember.user_id == user.id))
    total = 0
    for m in mr.scalars().all():
        r = await db.execute(
            select(func.count(Message.id)).where(
                Message.conversation_id == m.conversation_id,
                Message.created_at > m.last_read_at,
                Message.sender_id != user.id,
                Message.is_deleted.is_(False),
            )
        )
        total += r.scalar() or 0
    return JSONResponse({"unread": total})


@router.get("/direct/{partner_id}")
async def get_or_create_direct(partner_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    conv = await _ensure_direct(db, user.id, partner_id, user.venue_id)
    return JSONResponse({"conv_id": conv.id})


@router.get("/users")
async def list_users(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    r = await db.execute(
        select(User).where(User.venue_id == user.venue_id, User.id != user.id).order_by(User.name)
    )
    return JSONResponse([
        {
            "id": u.id,
            "name": u.name,
            "initials": u.initials,
            "color": u.avatar_color,
            "role": u.role.value,
            "online": manager.is_online(u.id),
        }
        for u in r.scalars().all()
    ])


class GroupCreate(BaseModel):
    name: str
    user_ids: list[int]


@router.post("/group")
async def create_group(body: GroupCreate, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    conv_name = body.name.strip() or "Группа"
    conv = Conversation(type=ConversationType.group, name=conv_name, venue_id=user.venue_id)
    db.add(conv)
    await db.flush()

    member_ids = list({user.id} | set(body.user_ids))
    for uid in member_ids:
        db.add(ConversationMember(conversation_id=conv.id, user_id=uid, last_read_at=datetime.utcnow()))

    await db.commit()
    await db.refresh(conv)

    return JSONResponse({
        "id": conv.id,
        "type": "group",
        "name": conv_name,
        "initials": conv_name[:2].upper(),
        "color": "#5B8FF9",
        "partner_id": None,
        "partner_role": None,
        "online": False,
        "last_seen": None,
        "unread_count": 0,
        "last_message": None,
    })


@router.delete("/messages/{msg_id}")
async def delete_message(msg_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    r = await db.execute(
        select(Message).options(selectinload(Message.sender))
        .where(Message.id == msg_id, Message.sender_id == user.id)
    )
    msg = r.scalar_one_or_none()
    if not msg:
        raise HTTPException(404)

    msg.is_deleted = True
    await db.commit()

    conv = await db.get(Conversation, msg.conversation_id)
    if conv:
        member_ids = await _conv_member_ids(db, conv, user.venue_id)
        await manager.broadcast(member_ids, {
            "type": "delete",
            "msg_id": msg_id,
            "conv_id": msg.conversation_id,
        })

    return JSONResponse({"ok": True})


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket(ws: WebSocket, token: str = ""):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = int(payload["sub"])
    except Exception:
        await ws.close(code=4001)
        return

    await manager.connect(ws, user_id)

    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if not user:
            await ws.close(code=4002)
            return
        venue_id = user.venue_id
        user.last_seen = None
        await db.commit()
        vr = await db.execute(select(User.id).where(User.venue_id == venue_id, User.id != user_id))
        venue_ids = [r[0] for r in vr.all()]

    await manager.broadcast(venue_ids, {"type": "online", "user_id": user_id, "online": True})

    try:
        while True:
            data = await ws.receive_json()
            t = data.get("type")

            if t == "message":
                await _ws_send_message(user_id, venue_id, data)

            elif t == "typing":
                conv_id = data.get("conv_id")
                if conv_id:
                    async with AsyncSessionLocal() as db:
                        u = await db.get(User, user_id)
                        conv = await db.get(Conversation, conv_id)
                        if conv:
                            ids = await _conv_member_ids(db, conv, venue_id)
                    await manager.broadcast(
                        [i for i in ids if i != user_id],
                        {"type": "typing", "conv_id": conv_id, "user_id": user_id, "user_name": u.name if u else "?"},
                    )

            elif t == "stop_typing":
                conv_id = data.get("conv_id")
                if conv_id:
                    async with AsyncSessionLocal() as db:
                        conv = await db.get(Conversation, conv_id)
                        if conv:
                            ids = await _conv_member_ids(db, conv, venue_id)
                    await manager.broadcast(
                        [i for i in ids if i != user_id],
                        {"type": "stop_typing", "conv_id": conv_id, "user_id": user_id},
                    )

            elif t == "read":
                conv_id = data.get("conv_id")
                if conv_id:
                    async with AsyncSessionLocal() as db:
                        member = await _ensure_member(db, conv_id, user_id)
                        member.last_read_at = datetime.utcnow()
                        await db.commit()
                        conv = await db.get(Conversation, conv_id)
                        if conv:
                            ids = await _conv_member_ids(db, conv, venue_id)
                    await manager.broadcast(
                        [i for i in ids if i != user_id],
                        {"type": "read", "conv_id": conv_id, "user_id": user_id},
                    )

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        manager.disconnect(ws, user_id)
        last_seen_iso = None
        if not manager.is_online(user_id):
            async with AsyncSessionLocal() as db:
                u = await db.get(User, user_id)
                if u:
                    u.last_seen = datetime.utcnow()
                    last_seen_iso = u.last_seen.isoformat()
                    await db.commit()
            await manager.broadcast(venue_ids, {
                "type": "online", "user_id": user_id, "online": False, "last_seen": last_seen_iso,
            })


async def _ws_send_message(user_id: int, venue_id: int, data: dict):
    conv_id = data.get("conv_id")
    text = (data.get("text") or "").strip()
    reply_to_id = data.get("reply_to_id")
    if not (text and conv_id):
        return

    async with AsyncSessionLocal() as db:
        u = await db.execute(select(User).where(User.id == user_id))
        user = u.scalar_one_or_none()
        if not user:
            return

        msg = Message(
            conversation_id=conv_id,
            sender_id=user_id,
            text=text,
            reply_to_id=reply_to_id,
            created_at=datetime.utcnow(),
        )
        db.add(msg)
        await db.flush()

        reply = None
        if reply_to_id:
            rr = await db.execute(
                select(Message).options(selectinload(Message.sender)).where(Message.id == reply_to_id)
            )
            reply = rr.scalar_one_or_none()

        await db.commit()

        # Re-load with sender eagerly
        mr = await db.execute(
            select(Message).options(selectinload(Message.sender)).where(Message.id == msg.id)
        )
        msg = mr.scalar_one()

        conv = await db.get(Conversation, conv_id)
        if not conv:
            return
        member_ids = await _conv_member_ids(db, conv, venue_id)

    payload = _msg_payload(msg, reply)
    for uid in member_ids:
        personalized = {**payload, "is_mine": uid == user_id, "read_by_others": False}
        await manager.send(uid, personalized)
