from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Boolean, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.database import Base


class ConversationType(str, enum.Enum):
    general = "general"
    direct = "direct"


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[ConversationType] = mapped_column(SAEnum(ConversationType), default=ConversationType.general)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    venue_id: Mapped[int] = mapped_column(Integer, ForeignKey("venues.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    messages: Mapped[list["Message"]] = relationship("Message", back_populates="conversation", order_by="Message.created_at")
    members: Mapped[list["ConversationMember"]] = relationship("ConversationMember", back_populates="conversation")


class ConversationMember(Base):
    __tablename__ = "conversation_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("conversations.id"))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    last_read_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="conversation_memberships")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("conversations.id"))
    sender_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    reply_to_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("messages.id"), nullable=True)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")
    sender: Mapped["User"] = relationship("User", back_populates="sent_messages")
