from __future__ import annotations
import datetime as dt
from typing import Optional, Literal, Tuple

from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Operators, Departments, PlanTargets

async def assert_subject_exists(
    db: AsyncSession, *, operator_id: Optional[int], department_id: Optional[int]
) -> Tuple[bool, str | None]:
    if operator_id is not None:
        r = await db.execute(select(Operators.id).where(Operators.id == operator_id))
        if not r.scalar_one_or_none():
            return False, "Operator not found"
    else:
        r = await db.execute(select(Departments.id).where(Departments.id == department_id))
        if not r.scalar_one_or_none():
            return False, "Department not found"
    return True, None


async def upsert_month_target(
    db: AsyncSession,
    *,
    metric: str,
    month1: dt.date | str,
    value: int,
    created_by: Optional[int],
    department_id: Optional[int] = None,
    operator_id: Optional[int] = None,
    target_mode: Literal["per_day", "total"],
) -> int:
    """UPDATE … RETURNING → INSERT (если не нашлось) для month/per_day|total."""
    # страховка: если вдруг пришла строка — приведём к date
    if isinstance(month1, str):
        month1 = dt.date.fromisoformat(month1).replace(day=1)

    conds = [
        PlanTargets.period_type == "month",
        PlanTargets.target_mode == target_mode,
        PlanTargets.metric == metric,
        PlanTargets.period_date == month1,  # ВАЖНО: сравниваем date с date
    ]
    if operator_id is not None:
        conds += [PlanTargets.operator_id == operator_id, PlanTargets.department_id.is_(None)]
    else:
        conds += [PlanTargets.department_id == department_id, PlanTargets.operator_id.is_(None)]

    res = await db.execute(
        update(PlanTargets)
        .where(and_(*conds))
        .values(target_value=value)
        .returning(PlanTargets.id)
    )
    row = res.first()
    if row:
        return row[0]

    obj = PlanTargets(
        period_type="month",
        target_mode=target_mode,
        metric=metric,
        period_date=month1,
        target_value=value,
        department_id=department_id,
        operator_id=operator_id,
        created_by=created_by,
    )
    db.add(obj)
    await db.flush()
    return obj.id


async def upsert_day_target(
    db: AsyncSession,
    *,
    metric: str,
    day: dt.date | str,
    value: int,
    created_by: Optional[int],
    department_id: Optional[int] = None,
    operator_id: Optional[int] = None,
) -> int:
    """UPDATE … RETURNING → INSERT для day/total (только target_mode='total')."""
    if isinstance(day, str):
        day = dt.date.fromisoformat(day)

    conds = [
        PlanTargets.period_type == "day",
        PlanTargets.target_mode == "total",
        PlanTargets.metric == metric,
        PlanTargets.period_date == day,
    ]
    if operator_id is not None:
        conds += [PlanTargets.operator_id == operator_id, PlanTargets.department_id.is_(None)]
    else:
        conds += [PlanTargets.department_id == department_id, PlanTargets.operator_id.is_(None)]

    res = await db.execute(
        update(PlanTargets)
        .where(and_(*conds))
        .values(target_value=value)
        .returning(PlanTargets.id)
    )
    row = res.first()
    if row:
        return row[0]

    obj = PlanTargets(
        period_type="day",
        target_mode="total",
        metric=metric,
        period_date=day,
        target_value=value,
        department_id=department_id,
        operator_id=operator_id,
        created_by=created_by,
    )
    db.add(obj)
    await db.flush()
    return obj.id


async def effective_daily_value(db: AsyncSession, *, operator_id: int, day: dt.date, metric: str) -> Tuple[Optional[int], Optional[str]]:
    month1 = day.replace(day=1)
    # 1) operator/day
    q1 = await db.execute(select(PlanTargets.target_value).where(
        PlanTargets.operator_id == operator_id, PlanTargets.department_id.is_(None),
        PlanTargets.period_type == "day", PlanTargets.target_mode == "total",
        PlanTargets.metric == metric, PlanTargets.period_date == day,
    ).limit(1))
    v = q1.scalar_one_or_none()
    if v is not None: return v, "operator/day"
    # 2) operator/month per_day
    q2 = await db.execute(select(PlanTargets.target_value).where(
        PlanTargets.operator_id == operator_id, PlanTargets.department_id.is_(None),
        PlanTargets.period_type == "month", PlanTargets.target_mode == "per_day",
        PlanTargets.metric == metric, PlanTargets.period_date == month1,
    ).limit(1))
    v = q2.scalar_one_or_none()
    if v is not None: return v, "operator/month_per_day"
    # 3) dept/day (последний по created_at)
    q3 = await db.execute(
        select(PlanTargets.target_value)
        .select_from(
            t_operator_departments.join(
                PlanTargets,
                and_(
                    PlanTargets.department_id == t_operator_departments.c.department_id,
                    PlanTargets.operator_id.is_(None),
                    PlanTargets.period_type == "day",
                    PlanTargets.target_mode == "total",
                    PlanTargets.metric == metric,
                    PlanTargets.period_date == day,
                )
            )
        )
        .where(t_operator_departments.c.operator_id == operator_id)
        .order_by(PlanTargets.created_at.desc())
        .limit(1)
    )
    v = q3.scalar_one_or_none()
    if v is not None: return v, "dept/day"
    # 4) dept/month per_day
    q4 = await db.execute(
        select(PlanTargets.target_value)
        .select_from(
            t_operator_departments.join(
                PlanTargets,
                and_(
                    PlanTargets.department_id == t_operator_departments.c.department_id,
                    PlanTargets.operator_id.is_(None),
                    PlanTargets.period_type == "month",
                    PlanTargets.target_mode == "per_day",
                    PlanTargets.metric == metric,
                    PlanTargets.period_date == month1,
                )
            )
        )
        .where(t_operator_departments.c.operator_id == operator_id)
        .order_by(PlanTargets.created_at.desc())
        .limit(1)
    )
    v = q4.scalar_one_or_none()
    if v is not None: return v, "dept/month_per_day"
    return None, None

async def actual_for_range(db: AsyncSession, *, operator_id: int, date_from: dt.date, date_to: dt.date, metric: str) -> int:
    if metric == "indicators_done":
        agg = func.sum(func.coalesce(Calls.indicators_done, 0))
    elif metric == "penalty_sum":
        agg = func.sum(func.coalesce(Calls.penalty_sum, 0))
    else:  # stages_done
        agg = func.sum(func.coalesce(Calls.stages_done, 0))
    val = (await db.execute(select(agg).where(
        Calls.operator_id == operator_id,
        func.date(Calls.call_start_date) >= date_from,
        func.date(Calls.call_start_date) <= date_to,
        Calls.deleted_at.is_(None),
    ))).scalar() or 0
    return int(val)
