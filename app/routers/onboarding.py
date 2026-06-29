from datetime import datetime
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth import get_current_user
from app.models.user import User, UserRole
from app.models.onboarding import (
    Module, ModuleStep, ModuleProgress, Quiz, QuizQuestion, QuizOption, QuizAttempt
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])
templates = Jinja2Templates(directory="app/templates")


async def _get_user_progress(db: AsyncSession, user_id: int, module_id: int) -> ModuleProgress | None:
    result = await db.execute(
        select(ModuleProgress).where(
            ModuleProgress.user_id == user_id,
            ModuleProgress.module_id == module_id,
        )
    )
    return result.scalar_one_or_none()


@router.get("", response_class=HTMLResponse)
async def onboarding_index(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    await db.refresh(user, ["module_progresses"])

    result = await db.execute(
        select(Module).options(selectinload(Module.steps), selectinload(Module.quiz)).order_by(Module.order)
    )
    modules = result.scalars().all()

    progress_map = {p.module_id: p for p in user.module_progresses}

    module_data = []
    for m in modules:
        prog = progress_map.get(m.id)
        steps_count = len(m.steps)
        current_step = prog.current_step if prog else 0
        pct = int(current_step / steps_count * 100) if steps_count else 0
        module_data.append({
            "module": m,
            "progress": prog,
            "steps_count": steps_count,
            "current_step": current_step,
            "percent": pct,
        })

    total = len(modules)
    completed = sum(1 for d in module_data if d["progress"] and d["progress"].completed)
    overall_pct = int(completed / total * 100) if total else 0

    if user.role == UserRole.manager:
        staff_result = await db.execute(
            select(User).where(User.venue_id == user.venue_id, User.role == UserRole.staff)
        )
        staff_list = staff_result.scalars().all()
        staff_data = []
        for s in staff_list:
            s_prog_result = await db.execute(
                select(ModuleProgress).where(ModuleProgress.user_id == s.id)
            )
            s_progs = s_prog_result.scalars().all()
            s_completed = sum(1 for p in s_progs if p.completed)
            staff_data.append({"user": s, "completed": s_completed, "total": total})
    else:
        staff_data = None

    return templates.TemplateResponse("onboarding/index.html", {
        "request": request,
        "user": user,
        "module_data": module_data,
        "overall_pct": overall_pct,
        "completed": completed,
        "total": total,
        "staff_data": staff_data,
    })


@router.get("/{module_id}/step/{step_num}", response_class=HTMLResponse)
async def module_step(module_id: int, step_num: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    result = await db.execute(
        select(Module).options(selectinload(Module.steps)).where(Module.id == module_id)
    )
    module = result.scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404)

    steps = sorted(module.steps, key=lambda s: s.order)
    if step_num < 1 or step_num > len(steps):
        raise HTTPException(status_code=404)

    step = steps[step_num - 1]

    prog = await _get_user_progress(db, user.id, module_id)
    if not prog:
        prog = ModuleProgress(user_id=user.id, module_id=module_id, current_step=step_num)
        db.add(prog)
        await db.commit()
    elif step_num > prog.current_step:
        prog.current_step = step_num
        await db.commit()

    return templates.TemplateResponse("onboarding/step.html", {
        "request": request,
        "user": user,
        "module": module,
        "step": step,
        "step_num": step_num,
        "total_steps": len(steps),
        "progress": prog,
    })


@router.get("/{module_id}/quiz", response_class=HTMLResponse)
async def module_quiz(module_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    result = await db.execute(
        select(Module).options(selectinload(Module.steps)).where(Module.id == module_id)
    )
    module = result.scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404)

    quiz_result = await db.execute(
        select(Quiz).options(
            selectinload(Quiz.questions).selectinload(QuizQuestion.options)
        ).where(Quiz.module_id == module_id)
    )
    quiz = quiz_result.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404)

    attempt_result = await db.execute(
        select(QuizAttempt)
        .where(QuizAttempt.user_id == user.id, QuizAttempt.quiz_id == quiz.id)
        .order_by(QuizAttempt.attempted_at.desc())
    )
    last_attempt = attempt_result.scalars().first()

    return templates.TemplateResponse("onboarding/quiz.html", {
        "request": request,
        "user": user,
        "module": module,
        "quiz": quiz,
        "last_attempt": last_attempt,
    })


@router.post("/{module_id}/quiz/submit")
async def submit_quiz(module_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    quiz_result = await db.execute(
        select(Quiz).options(
            selectinload(Quiz.questions).selectinload(QuizQuestion.options)
        ).where(Quiz.module_id == module_id)
    )
    quiz = quiz_result.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404)

    form = await request.form()
    correct = 0
    total = len(quiz.questions)

    for question in quiz.questions:
        selected = form.get(f"question_{question.id}")
        if selected:
            correct_option = next((o for o in question.options if o.is_correct), None)
            if correct_option and str(correct_option.id) == selected:
                correct += 1

    score = correct / total if total else 0
    passed = score >= quiz.pass_score

    attempt = QuizAttempt(user_id=user.id, quiz_id=quiz.id, score=score, passed=passed)
    db.add(attempt)

    if passed:
        prog = await _get_user_progress(db, user.id, module_id)
        if prog:
            prog.completed = True
            prog.completed_at = datetime.utcnow()

    await db.commit()
    return RedirectResponse(url=f"/onboarding/{module_id}/quiz?result=1", status_code=302)


@router.get("/{module_id}/certificate", response_class=HTMLResponse)
async def certificate(module_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    result = await db.execute(select(Module).where(Module.id == module_id))
    module = result.scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404)

    prog = await _get_user_progress(db, user.id, module_id)
    if not prog or not prog.completed:
        return RedirectResponse(url=f"/onboarding", status_code=302)

    return templates.TemplateResponse("onboarding/certificate.html", {
        "request": request,
        "user": user,
        "module": module,
        "progress": prog,
    })
