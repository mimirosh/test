"""Routes: оценка выполнения планов.

- GET /plan-targets/evaluate/daily   — оценка за день ИЛИ за произвольный период
- GET /plan-targets/evaluate/monthly — оценка за месяц
"""

from __future__ import annotations
import datetime as dt
from typing import Optional, Literal, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from database.session import get_db
from endpoints.auth import get_current_user
from .schemas import EvaluateDailyOut, EvaluatePeriodOut, EvaluateMonthlyOut
from .repo import actual_for_range, effective_daily_value
from .logic import classify
from database.models import PlanTargets, t_operator_departments

router = APIRouter()

@router.get(
    "/evaluate/daily",
    summary="Оценка выполнения: за один день ИЛИ за период (несколько дней)",
    response_model=EvaluatePeriodOut | EvaluateDailyOut,
)
async def evaluate_daily(
    operator_id: int = Query(..., description="ID оператора"),
    metric: Literal["indicators_done", "penalty_sum", "stages_done"] = Query(..., description="Оцениваемая метрика"),
    day: Optional[dt.date] = Query(None, description="Если указан — считаем ровно этот день"),
    date_from: Optional[dt.date] = Query(None, description="Начало периода (если считаем диапазон)"),
    date_to: Optional[dt.date] = Query(None, description="Конец периода (если считаем диапазон)"),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Вернуть факт/цель/статус.

    # Варианты вызова
    - **Один день**: передать только `day`.
    - **Период**: передать `date_from` и `date_to` (оба включительно). В ответе будет
      агрегированная оценка и помесячная/подневная (breakdown) разбивка.

    # Статусы
    - Для `indicators_done`/`stages_done` (больше — лучше):  
      `good` ≥ 100% цели; `average` 70–99%; `bad` < 70%.
    - Для `penalty_sum` (меньше — лучше):  
      `good` ≤ цель; `average` ≤ 130% цели; `bad` > 130%.
    """
    if day and (date_from or date_to):
        raise HTTPException(status_code=400, detail="Либо day, либо date_from+date_to.")

    # === День ===
    if day:
        actual = await actual_for_range(db, operator_id=operator_id, date_from=day, date_to=day, metric=metric)
        target, source = await effective_daily_value(db, operator_id=operator_id, day=day, metric=metric)
        status, ratio = classify(metric, actual, target)
        return EvaluateDailyOut(operator_id=operator_id, date=day, metric=metric,
                                actual=actual, target=target, source=source, status=status, ratio=ratio)

    # === Период ===
    if not (date_from and date_to):
        raise HTTPException(status_code=400, detail="Укажи day ИЛИ date_from+date_to.")
    if date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from > date_to.")

    days = (date_to - date_from).days + 1
    breakdown: List[EvaluateDailyOut] = []
    target_total = 0
    actual_total = 0

    for i in range(days):
        d = date_from + dt.timedelta(days=i)
        a = await actual_for_range(db, operator_id=operator_id, date_from=d, date_to=d, metric=metric)
        t, src = await effective_daily_value(db, operator_id=operator_id, day=d, metric=metric)
        actual_total += a
        if t is not None:
            target_total += t
        st, rr = classify(metric, a, t)
        breakdown.append(EvaluateDailyOut(operator_id=operator_id, date=d, metric=metric,
                                          actual=a, target=t, source=src, status=st, ratio=rr))

    target_agg = target_total if target_total > 0 else None
    status, ratio = classify(metric, actual_total, target_agg)
    return EvaluatePeriodOut(
        operator_id=operator_id, date_from=date_from, date_to=date_to, metric=metric,
        actual=actual_total, target=target_agg, status=status, ratio=ratio,
        days=days, daily_breakdown=breakdown
    )


@router.get(
    "/evaluate/monthly",
    summary="Оценка выполнения: за месяц",
    response_model=EvaluateMonthlyOut,
)
async def evaluate_monthly(
    operator_id: int = Query(..., description="ID оператора"),
    month: dt.date = Query(..., description="Любая дата месяца; нормализуется к 1 числу"),
    metric: Literal["indicators_done", "penalty_sum", "stages_done"] = Query(..., description="Метрика"),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Вернуть факт/цель/статус за месяц.

    # Приоритет определения цели
    1) operator **month/total**  
    2) department **month/total**  
    3) сумма эффективных **дневных** целей за все дни месяца (если пунктов 1–2 нет)
    """
    month1 = month.replace(day=1)
    next_m = (month1.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    last_day = next_m - dt.timedelta(days=1)

    # факт за месяц
    actual = await actual_for_range(db, operator_id=operator_id, date_from=month1, date_to=last_day, metric=metric)

    # цель: month/total → dept month/total → сумма дневных
    source = None
    target = (await db.execute(
        select(PlanTargets.target_value).where(
            PlanTargets.operator_id == operator_id, PlanTargets.department_id.is_(None),
            PlanTargets.period_type == "month", PlanTargets.target_mode == "total",
            PlanTargets.metric == metric, PlanTargets.period_date == month1,
        ).limit(1)
    )).scalar_one_or_none()
    if target is not None:
        source = "operator/month_total"
    else:
        q2 = await db.execute(
            select(PlanTargets.target_value)
            .select_from(
                t_operator_departments.join(
                    PlanTargets,
                    and_(
                        PlanTargets.department_id == t_operator_departments.c.department_id,
                        PlanTargets.operator_id.is_(None),
                        PlanTargets.period_type == "month",
                        PlanTargets.target_mode == "total",
                        PlanTargets.metric == metric,
                        PlanTargets.period_date == month1,
                    )
                )
            )
            .where(t_operator_departments.c.operator_id == operator_id)
            .order_by(PlanTargets.created_at.desc())
            .limit(1)
        )
        target = q2.scalar_one_or_none()
        if target is not None:
            source = "dept/month_total"

    if target is None:
        target_sum = 0
        days_in_month = (last_day - month1).days + 1
        for i in range(days_in_month):
            d = month1 + dt.timedelta(days=i)
            t, _ = await effective_daily_value(db, operator_id=operator_id, day=d, metric=metric)
            if t is not None:
                target_sum += t
        target = target_sum if target_sum > 0 else None

    status, ratio = classify(metric, actual, target)
    return EvaluateMonthlyOut(
        operator_id=operator_id, month=month1, metric=metric,
        actual=actual, target=target, source=source,
        status=status, ratio=ratio, days_in_month=(last_day - month1).days + 1,
    )
