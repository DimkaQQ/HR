from datetime import datetime, date
from sqlalchemy import String, Integer, DateTime, Date, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.database import Base


class UserRole(str, enum.Enum):
    manager = "manager"
    staff = "staff"


class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    users: Mapped[list["User"]] = relationship("User", back_populates="venue")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.staff)
    venue_id: Mapped[int] = mapped_column(Integer, ForeignKey("venues.id"))
    avatar_color: Mapped[str] = mapped_column(String(7), default="#C8A84B")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    streak_days: Mapped[int] = mapped_column(Integer, default=0)
    last_active: Mapped[date | None] = mapped_column(Date, nullable=True)

    venue: Mapped["Venue"] = relationship("Venue", back_populates="users")
    module_progresses: Mapped[list["ModuleProgress"]] = relationship("ModuleProgress", back_populates="user")
    quiz_attempts: Mapped[list["QuizAttempt"]] = relationship("QuizAttempt", back_populates="user")
    sent_messages: Mapped[list["Message"]] = relationship("Message", back_populates="sender")
    conversation_memberships: Mapped[list["ConversationMember"]] = relationship("ConversationMember", back_populates="user")
    item_completions: Mapped[list["ItemCompletion"]] = relationship("ItemCompletion", back_populates="user")

    @property
    def initials(self) -> str:
        parts = self.name.split()
        if len(parts) >= 2:
            return f"{parts[0][0]}{parts[1][0]}".upper()
        return self.name[:2].upper()
