# endpoints/call_metrics.py
"""
CallMetrics (per-call): сравнение и временные ряды по полям calls:
- indicators_done (больше — лучше)
- stages_done (больше — лучше)
- penalty_sum (меньше — лучше)

Эндпоинты:
- GET /call-metrics/compare — сравнить два периода (DoD/WoW/MoM/YoY)
- GET /call-metrics/series  — временной ряд (hour/day) для графиков
"""

from __future__ import annotations
import datetime as dt
from typing import Optional, Literal, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_, cast, literal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import INTERVAL

from database.session import get_db
from database.models import Calls, t_operator_departments
from endpoints.auth import get_current_user

router = APIRouter(prefix="/call-metrics", tags=["CallMetrics"])

Metric = Literal["indicators_done", "stages_done", "penalty_sum"]
Mode = Literal["dod", "wow", "mom", "yoy"]
Grain = Literal["hour", "day"]


# ---------- helpers ----------

def _week_bounds(any_date: dt.date) -> tuple[dt.date, dt.date]:
    monday = any_date - dt.timedelta(days=any_date.weekday())
    sunday = monday + dt.timedelta(days=6)
    return monday, sunday

def _month_bounds(any_date: dt.date) -> tuple[dt.date, dt.date]:
    start = any_date.replace(day=1)
    next_month = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    end = next_month - dt.timedelta(days=1)
    return start, end

def _periods(mode: Mode, at: dt.date) -> tuple[tuple[dt.date, dt.date], tuple[dt.date, dt.date]]:
    if mode == "dod":
        return (at, at), (at - dt.timedelta(days=1), at - dt.timedelta(days=1))
    if mode == "wow":
        s1, e1 = _week_bounds(at)
        s2, e2 = _week_bounds(s1 - dt.timedelta(days=1))
        return (s1, e1), (s2, e2)
    if mode == "mom":
        s1, e1 = _month_bounds(at)
        s2, e2 = _month_bounds(s1 - dt.timedelta(days=1))
        return (s1, e1), (s2, e2)
    # yoy
    y1, y2 = at.year, at.year - 1
    return (dt.date(y1, 1, 1), dt.date(y1, 12, 31)), (dt.date(y2, 1, 1), dt.date(y2, 12, 31))


async def _sum_calls_metric(
    db: AsyncSession,
    *,
    metric: Metric,
    start: dt.datetime,
    end: dt.datetime,
    operator_id: int | None,
    department_id: int | None,
) -> int:
    """
    Суммирует per-call метрику из calls за период [start..end] включительно.
    Для отдела делаем join на operator_departments и фильтруем по department_id.
    """
    column = getattr(Calls, metric)
    expr = func.coalesce(func.sum(column), 0)

    base_cond = and_(
        Calls.call_start_date >= start,
        Calls.call_start_date <= end,
        Calls.deleted_at.is_(None),
    )

    if operator_id is not None:
        stmt = select(expr).where(base_cond, Calls.operator_id == operator_id)
    else:
        # фильтр по отделу
        stmt = (
            select(expr)
            .select_from(
                Calls.__table__.join(
                    t_operator_departments,
                    Calls.operator_id == t_operator_departments.c.operator_id,
                )
            )
            .where(base_cond, t_operator_departments.c.department_id == department_id)
        )

    val = (await db.execute(stmt)).scalar()
    return int(val or 0)


# ---------- Schemas ----------

class PeriodValue(BaseModel):
    start: dt.date
    end: dt.date
    value: int

class CompareResponse(BaseModel):
    scope: dict
    metric: Metric
    mode: Mode
    at: dt.date
    period1: PeriodValue
    period2: PeriodValue
    delta: int
    pct_change: Optional[float] = Field(None, description="delta/period2.value (None если деление на ноль)")

class SeriesPoint(BaseModel):
    bucket: dt.datetime
    value: int

class SeriesResponse(BaseModel):
    scope: dict
    metric: Metric
    grain: Grain
    tz: str
    date_from: dt.datetime
    date_to: dt.datetime
    points: List[SeriesPoint]


# ---------- Endpoints ----------

@router.get(
    "/compare",
    response_model=CompareResponse,
    summary="Сравнить суммы per-call метрик между периодами (DoD/WoW/MoM/YoY)",
    description=(
        "Суммирует выбранную метрику из `calls` и сравнивает два периода. Формат даты `YYYY-MM-DD`.\n\n"
        "Укажи **ровно один** из параметров `operator_id` или `department_id`.\n\n"
        "Режимы: `dod` (день к дню), `wow` (неделя к неделе), `mom` (месяц к месяцу), `yoy` (год к году)."
    ),
)
async def compare_call_metrics(
    metric: Metric = Query(...),
    mode: Mode = Query(...),
    at: dt.date = Query(..., description="Дата-якорь"),
    operator_id: Optional[int] = Query(None),
    department_id: Optional[int] = Query(None),
    tz: str = Query("UTC", description="Часовой пояс для границ периода (например, 'Europe/Moscow')"),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    # валидация субъекта
    if (operator_id is None and department_id is None) or (operator_id is not None and department_id is not None):
        raise HTTPException(status_code=400, detail="Укажи ровно один из: operator_id или department_id")

    # границы периодов как локальные полные интервалы (включительно)
    (p1s_d, p1e_d), (p2s_d, p2e_d) = _periods(mode, at)
    # превращаем в таймстемпы начала/конца суток в указанном TZ на стороне БД:
    # удобнее расширить до datetime на 00:00:00 и 23:59:59
    p1s = dt.datetime.combine(p1s_d, dt.time.min)
    p1e = dt.datetime.combine(p1e_d, dt.time.max)
    p2s = dt.datetime.combine(p2s_d, dt.time.min)
    p2e = dt.datetime.combine(p2e_d, dt.time.max)

    v1 = await _sum_calls_metric(db, metric=metric, start=p1s, end=p1e,
                                 operator_id=operator_id, department_id=department_id)
    v2 = await _sum_calls_metric(db, metric=metric, start=p2s, end=p2e,
                                 operator_id=operator_id, department_id=department_id)

    delta = v1 - v2
    pct = (delta / v2) if v2 else None
    scope = {"operator_id": operator_id} if operator_id is not None else {"department_id": department_id}

    return CompareResponse(
        scope=scope, metric=metric, mode=mode, at=at,
        period1=PeriodValue(start=p1s_d, end=p1e_d, value=v1),
        period2=PeriodValue(start=p2s_d, end=p2e_d, value=v2),
        delta=delta, pct_change=pct,
    )


@router.get(
    "/series",
    response_model=SeriesResponse,
    summary="Временной ряд по per-call метрикам (hour/day) для графиков",
    description=(
        "Возвращает точки временного ряда, агрегированные по `hour` или `day` "
        "за указанный интервал. Формат даты `YYYY-MM-DD`.\n\n"
        "**Внимание**: Укажи **ровно один** из `operator_id` или `department_id`.\n\n"
        "Параметр `tz` задаёт локализацию времени для бакетизации (по умолчанию UTC)."
    ),
)
async def call_metrics_series(
    metric: Metric = Query(...),
    grain: Grain = Query(..., description="Размер корзины: hour | day"),
    date_from: dt.datetime = Query(..., description="Начало интервала (ISO, будет приведено к TZ)"),
    date_to: dt.datetime = Query(..., description="Конец интервала (ISO, включительно)"),
    operator_id: Optional[int] = Query(None),
    department_id: Optional[int] = Query(None),
    tz: str = Query("UTC", description="Напр. 'Europe/Moscow'"),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    if date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from > date_to")
    if (operator_id is None and department_id is None) or (operator_id is not None and department_id is not None):
        raise HTTPException(status_code=400, detail="Укажи ровно один из: operator_id или department_id")

    step = "1 hour" if grain == "hour" else "1 day"
    step_expr = cast(literal(step), INTERVAL)   # <-- фикс

    gs = select(
        func.generate_series(date_from, date_to, step_expr).label("bucket")
    ).subquery("gs")
    bucket = gs.c.bucket

    bucket_expr = func.date_trunc(grain, func.timezone(tz, Calls.call_start_date))
    column = getattr(Calls, metric)
    value_expr = func.coalesce(func.sum(column), 0)

    base_join_cond = and_(
        bucket_expr == bucket,
        Calls.deleted_at.is_(None),
        Calls.call_start_date >= date_from,
        Calls.call_start_date <= date_to,
    )

    if operator_id is not None:
        from_clause = gs.outerjoin(Calls, and_(base_join_cond, Calls.operator_id == operator_id))
        stmt = select(bucket.label("bucket"), value_expr.label("value")).select_from(from_clause).group_by(bucket).order_by(bucket)
    else:
        from_clause = gs.outerjoin(
            Calls.__table__.join(
                t_operator_departments,
                Calls.operator_id == t_operator_departments.c.operator_id,
            ),
            and_(base_join_cond, t_operator_departments.c.department_id == department_id),
        )
        stmt = select(bucket.label("bucket"), value_expr.label("value")).select_from(from_clause).group_by(bucket).order_by(bucket)

    rows = (await db.execute(stmt)).all()
    points = [{"bucket": r.bucket, "value": int(r.value or 0)} for r in rows]
    scope = {"operator_id": operator_id} if operator_id is not None else {"department_id": department_id}
    return {
        "scope": scope, "metric": metric, "grain": grain, "tz": tz,
        "date_from": date_from, "date_to": date_to, "points": points
    }