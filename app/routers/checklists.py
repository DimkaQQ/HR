from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth import get_current_user
from app.models.user import User, UserRole
from app.models.checklist import ChecklistTemplate, ChecklistItem, DailyChecklist, ItemCompletion

router = APIRouter(prefix="/checklists", tags=["checklists"])
templates = Jinja2Templates(directory="app/templates")


async def _get_or_create_daily(db: AsyncSession, template_id: int, venue_id: int, for_date: date) -> DailyChecklist:
    result = await db.execute(
        select(DailyChecklist).where(
            DailyChecklist.template_id == template_id,
            DailyChecklist.venue_id == venue_id,
            DailyChecklist.date == for_date,
        )
    )
    daily = result.scalar_one_or_none()
    if not daily:
        daily = DailyChecklist(template_id=template_id, venue_id=venue_id, date=for_date)
        db.add(daily)
        await db.flush()

        tpl_result = await db.execute(
            select(ChecklistTemplate).options(selectinload(ChecklistTemplate.items))
            .where(ChecklistTemplate.id == template_id)
        )
        tpl = tpl_result.scalar_one_or_none()
        if tpl:
            for item in tpl.items:
                db.add(ItemCompletion(
                    daily_checklist_id=daily.id,
                    item_id=item.id,
                    user_id=1,
                    completed=False,
                ))
        await db.commit()
        await db.refresh(daily)
    return daily


@router.get("", response_class=HTMLResponse)
async def checklists_index(request: Request, date_str: str = "", db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    try:
        selected_date = date.fromisoformat(date_str) if date_str else date.today()
    except ValueError:
        selected_date = date.today()

    tpl_result = await db.execute(
        select(ChecklistTemplate)
        .options(selectinload(ChecklistTemplate.items))
        .where(ChecklistTemplate.venue_id == user.venue_id)
    )
    templates_list = tpl_result.scalars().all()

    checklist_data = []
    for tpl in templates_list:
        daily = await _get_or_create_daily(db, tpl.id, user.venue_id, selected_date)

        compl_result = await db.execute(
            select(ItemCompletion)
            .options(selectinload(ItemCompletion.item), selectinload(ItemCompletion.user))
            .where(ItemCompletion.daily_checklist_id == daily.id)
        )
        completions = compl_result.scalars().all()

        items_data = []
        for item in tpl.items:
            comp = next((c for c in completions if c.item_id == item.id), None)
            items_data.append({"item": item, "completion": comp})

        done = sum(1 for d in items_data if d["completion"] and d["completion"].completed)
        checklist_data.append({
            "template": tpl,
            "daily": daily,
            "items_data": items_data,
            "done": done,
            "total": len(items_data),
        })

    dates = [date.today() - timedelta(days=i) for i in range(7)]

    return templates.TemplateResponse("checklists/index.html", {
        "request": request,
        "user": user,
        "checklist_data": checklist_data,
        "selected_date": selected_date,
        "today": date.today(),
        "dates": dates,
    })


@router.post("/toggle/{daily_id}/{item_id}")
async def toggle_item(daily_id: int, item_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    result = await db.execute(
        select(ItemCompletion).where(
            ItemCompletion.daily_checklist_id == daily_id,
            ItemCompletion.item_id == item_id,
        )
    )
    comp = result.scalar_one_or_none()
    if not comp:
        comp = ItemCompletion(daily_checklist_id=daily_id, item_id=item_id, user_id=user.id, completed=True, completed_at=datetime.utcnow())
        db.add(comp)
    else:
        comp.completed = not comp.completed
        comp.user_id = user.id
        comp.completed_at = datetime.utcnow() if comp.completed else None

    await db.commit()
    return JSONResponse({"completed": comp.completed, "user_name": user.name})


@router.get("/history", response_class=HTMLResponse)
async def history(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    dates = [date.today() - timedelta(days=i) for i in range(14)]
    history_data = []

    for d in dates:
        daily_result = await db.execute(
            select(DailyChecklist)
            .options(
                selectinload(DailyChecklist.template),
                selectinload(DailyChecklist.completions).selectinload(ItemCompletion.user),
                selectinload(DailyChecklist.completions).selectinload(ItemCompletion.item),
            )
            .join(ChecklistTemplate)
            .where(DailyChecklist.date == d, ChecklistTemplate.venue_id == user.venue_id)
        )
        dailies = daily_result.scalars().all()
        history_data.append({"date": d, "dailies": dailies})

    return templates.TemplateResponse("checklists/history.html", {
        "request": request,
        "user": user,
        "history_data": history_data,
    })
