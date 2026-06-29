from datetime import datetime, date
from sqlalchemy import String, Integer, DateTime, Date, ForeignKey, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ChecklistTemplate(Base):
    __tablename__ = "checklist_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    venue_id: Mapped[int] = mapped_column(Integer, ForeignKey("venues.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    items: Mapped[list["ChecklistItem"]] = relationship("ChecklistItem", back_populates="template", order_by="ChecklistItem.order")
    daily_checklists: Mapped[list["DailyChecklist"]] = relationship("DailyChecklist", back_populates="template")


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(Integer, ForeignKey("checklist_templates.id"))
    text: Mapped[str] = mapped_column(String(500))
    order: Mapped[int] = mapped_column(Integer, default=0)

    template: Mapped["ChecklistTemplate"] = relationship("ChecklistTemplate", back_populates="items")
    completions: Mapped[list["ItemCompletion"]] = relationship("ItemCompletion", back_populates="item")


class DailyChecklist(Base):
    __tablename__ = "daily_checklists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(Integer, ForeignKey("checklist_templates.id"))
    date: Mapped[date] = mapped_column(Date)
    venue_id: Mapped[int] = mapped_column(Integer, ForeignKey("venues.id"))

    template: Mapped["ChecklistTemplate"] = relationship("ChecklistTemplate", back_populates="daily_checklists")
    completions: Mapped[list["ItemCompletion"]] = relationship("ItemCompletion", back_populates="daily_checklist")


class ItemCompletion(Base):
    __tablename__ = "item_completions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    daily_checklist_id: Mapped[int] = mapped_column(Integer, ForeignKey("daily_checklists.id"))
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("checklist_items.id"))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    daily_checklist: Mapped["DailyChecklist"] = relationship("DailyChecklist", back_populates="completions")
    item: Mapped["ChecklistItem"] = relationship("ChecklistItem", back_populates="completions")
    user: Mapped["User"] = relationship("User", back_populates="item_completions")
