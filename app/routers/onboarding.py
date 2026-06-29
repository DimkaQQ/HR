from datetime import datetime, date
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
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

XP_PER_STEP = 10
XP_PER_QUIZ_PASS = 50


async def _get_progress(db: AsyncSession, user_id: int, module_id: int) -> ModuleProgress | None:
    result = await db.execute(
        select(ModuleProgress).where(
            ModuleProgress.user_id == user_id,
            ModuleProgress.module_id == module_id,
        )
    )
    return result.scalar_one_or_none()


async def _update_streak(user: User) -> None:
    today = date.today()
    if user.last_active is None:
        user.streak_days = 1
    elif user.last_active == today:
        return
    elif (today - user.last_active).days == 1:
        user.streak_days = (user.streak_days or 0) + 1
    else:
        user.streak_days = 1
    user.last_active = today


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
    prev_completed = True
    for i, m in enumerate(modules):
        prog = progress_map.get(m.id)
        steps_count = len(m.steps)
        current_step = prog.current_step if prog else 0
        pct = int(current_step / steps_count * 100) if steps_count else 0
        is_completed = bool(prog and prog.completed)
        is_locked = not prev_completed and not is_completed
        module_data.append({
            "module": m,
            "progress": prog,
            "steps_count": steps_count,
            "current_step": current_step,
            "percent": pct,
            "is_completed": is_completed,
            "is_locked": is_locked,
        })
        prev_completed = is_completed if not is_locked else False

    total = len(modules)
    completed = sum(1 for d in module_data if d["is_completed"])

    staff_data = None
    if user.role == UserRole.manager:
        staff_result = await db.execute(
            select(User).where(User.venue_id == user.venue_id, User.role == UserRole.staff)
        )
        staff_list = staff_result.scalars().all()
        staff_data = []
        for s in staff_list:
            s_progs = await db.execute(select(ModuleProgress).where(ModuleProgress.user_id == s.id))
            s_completed = sum(1 for p in s_progs.scalars().all() if p.completed)
            staff_data.append({"user": s, "completed": s_completed, "total": total})

    return templates.TemplateResponse("onboarding/index.html", {
        "request": request,
        "user": user,
        "module_data": module_data,
        "total": total,
        "completed": completed,
        "staff_data": staff_data,
    })


@router.get("/{module_id}/step/{step_num}", response_class=HTMLResponse)
async def module_step(module_id: int, step_num: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    result = await db.execute(
        select(Module).options(selectinload(Module.steps), selectinload(Module.quiz)).where(Module.id == module_id)
    )
    module = result.scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404)

    steps = sorted(module.steps, key=lambda s: s.order)
    if step_num < 1 or step_num > len(steps):
        raise HTTPException(status_code=404)

    step = steps[step_num - 1]
    prog = await _get_progress(db, user.id, module_id)
    if not prog:
        prog = ModuleProgress(user_id=user.id, module_id=module_id, current_step=step_num)
        db.add(prog)
        await db.commit()

    return templates.TemplateResponse("onboarding/step.html", {
        "request": request,
        "user": user,
        "module": module,
        "step": step,
        "step_num": step_num,
        "total_steps": len(steps),
        "progress": prog,
        "has_quiz": module.quiz is not None,
    })


@router.post("/{module_id}/step/{step_num}/complete")
async def complete_step(module_id: int, step_num: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    result = await db.execute(
        select(Module).options(selectinload(Module.steps), selectinload(Module.quiz)).where(Module.id == module_id)
    )
    module = result.scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404)

    steps = sorted(module.steps, key=lambda s: s.order)
    total_steps = len(steps)

    prog = await _get_progress(db, user.id, module_id)
    xp_earned = 0

    if not prog:
        prog = ModuleProgress(user_id=user.id, module_id=module_id, current_step=step_num)
        db.add(prog)
        xp_earned = XP_PER_STEP
    elif step_num > prog.current_step:
        prog.current_step = step_num
        xp_earned = XP_PER_STEP

    if xp_earned:
        user.xp = (user.xp or 0) + xp_earned
        await _update_streak(user)

    await db.commit()

    is_last = step_num >= total_steps
    if is_last and module.quiz:
        next_url = f"/onboarding/{module_id}/quiz"
    elif not is_last:
        next_url = f"/onboarding/{module_id}/step/{step_num + 1}"
    else:
        next_url = "/onboarding"

    return JSONResponse({
        "xp_earned": xp_earned,
        "total_xp": user.xp or 0,
        "streak": user.streak_days or 0,
        "next_url": next_url,
        "is_last_step": is_last,
    })


@router.get("/{module_id}/quiz-data")
async def quiz_data(module_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    quiz_result = await db.execute(
        select(Quiz).options(
            selectinload(Quiz.questions).selectinload(QuizQuestion.options)
        ).where(Quiz.module_id == module_id)
    )
    quiz = quiz_result.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404)

    questions = []
    for q in quiz.questions:
        correct_opt = next((o for o in q.options if o.is_correct), None)
        questions.append({
            "id": q.id,
            "text": q.text,
            "correct_id": correct_opt.id if correct_opt else None,
            "options": [{"id": o.id, "text": o.text} for o in q.options],
        })

    return JSONResponse({
        "quiz_id": quiz.id,
        "pass_score": quiz.pass_score,
        "questions": questions,
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

    quiz_result = await db.execute(select(Quiz).where(Quiz.module_id == module_id))
    quiz = quiz_result.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404)

    passed_result = await db.execute(
        select(QuizAttempt)
        .where(QuizAttempt.user_id == user.id, QuizAttempt.quiz_id == quiz.id, QuizAttempt.passed == True)
        .order_by(QuizAttempt.attempted_at.desc())
    )
    already_passed = passed_result.scalars().first() is not None

    prog = await _get_progress(db, user.id, module_id)

    return templates.TemplateResponse("onboarding/quiz.html", {
        "request": request,
        "user": user,
        "module": module,
        "quiz": quiz,
        "already_passed": already_passed,
        "progress": prog,
    })


@router.post("/{module_id}/quiz/submit-json")
async def submit_quiz_json(module_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    quiz_result = await db.execute(
        select(Quiz).options(
            selectinload(Quiz.questions).selectinload(QuizQuestion.options)
        ).where(Quiz.module_id == module_id)
    )
    quiz = quiz_result.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404)

    body = await request.json()
    answers = body.get("answers", {})

    correct_count = 0
    total = len(quiz.questions)
    results = []

    for q in quiz.questions:
        correct_opt = next((o for o in q.options if o.is_correct), None)
        selected_id = answers.get(str(q.id))
        is_correct = bool(selected_id and correct_opt and str(correct_opt.id) == str(selected_id))
        if is_correct:
            correct_count += 1
        results.append({
            "question_id": q.id,
            "selected_id": selected_id,
            "correct_id": correct_opt.id if correct_opt else None,
            "is_correct": is_correct,
        })

    score = correct_count / total if total else 0
    passed = score >= quiz.pass_score

    attempt = QuizAttempt(user_id=user.id, quiz_id=quiz.id, score=score, passed=passed)
    db.add(attempt)

    xp_earned = 0
    if passed:
        prog = await _get_progress(db, user.id, module_id)
        if prog and not prog.completed:
            prog.completed = True
            prog.completed_at = datetime.utcnow()
            xp_earned = XP_PER_QUIZ_PASS
            user.xp = (user.xp or 0) + xp_earned
            await _update_streak(user)

    await db.commit()

    return JSONResponse({
        "passed": passed,
        "score": round(score * 100),
        "correct": correct_count,
        "total": total,
        "xp_earned": xp_earned,
        "total_xp": user.xp or 0,
        "streak": user.streak_days or 0,
        "results": results,
        "certificate_url": f"/onboarding/{module_id}/certificate" if passed else None,
    })


@router.get("/{module_id}/certificate", response_class=HTMLResponse)
async def certificate(module_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)

    result = await db.execute(select(Module).where(Module.id == module_id))
    module = result.scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404)

    prog = await _get_progress(db, user.id, module_id)
    if not prog or not prog.completed:
        return RedirectResponse(url="/onboarding", status_code=302)

    return templates.TemplateResponse("onboarding/certificate.html", {
        "request": request,
        "user": user,
        "module": module,
        "progress": prog,
    })
