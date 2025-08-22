"""Routes: чтение планов.

- GET /plan-targets/by-subject     — получить планы субъекта за месяц
- GET /plan-targets/effective/daily — эффективная дневная цель (оператор на дату)
"""

from __future__ import annotations
import datetime as dt
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from endpoints.auth import get_current_user
from database.models import PlanTargets
from .schemas import PlanMetric, ListOut, PlanTargetOut
from .repo import effective_daily_value

router = APIRouter()

@router.get(
    "/by-subject",
    summary="Получить планы субъекта (отдел/оператор) за месяц",
    response_model=ListOut,
)
async def list_by_subject(
    month: dt.date = Query(..., description="Любая дата месяца; нормализуется к 1 числу."),
    department_id: Optional[int] = Query(None, description="ID отдела, если не указан operator_id"),
    operator_id: Optional[int] = Query(None, description="ID оператора, если не указан department_id"),
    metric: Optional[PlanMetric] = Query(None, description="Опционально ограничить одной метрикой"),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Вернуть все записи `plan_targets` для субъекта на конкретный месяц.

    # Параметры
    - **month**: *date* — любая дата внутри нужного месяца.
    - **department_id | operator_id**: ровно один.
    - **metric**: *PlanMetric*, необязательно.

    # Возвращает
    - `items` — список подходящих строк `plan_targets`.
    - `total` — общее количество (удобно фронту для пагинации, хотя обычно записей немного).

    # Ошибки
    - **400** — переданы оба субъекта или ни одного.
    """
    if (department_id is None and operator_id is None) or (department_id is not None and operator_id is not None):
        raise HTTPException(status_code=400, detail="Укажи либо department_id, либо operator_id")

    month1 = month.replace(day=1)
    conds = [PlanTargets.period_date == month1, PlanTargets.period_type == "month"]
    if metric:
        conds.append(PlanTargets.metric == metric)
    if operator_id is not None:
        conds += [PlanTargets.operator_id == operator_id, PlanTargets.department_id.is_(None)]
    else:
        conds += [PlanTargets.department_id == department_id, PlanTargets.operator_id.is_(None)]

    stmt = select(func.count().over().label("total"), PlanTargets).where(and_(*conds)).order_by(
        PlanTargets.metric.asc(), PlanTargets.target_mode.asc()
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return {"items": [], "total": 0}

    total = rows[0][0]
    items = [PlanTargetOut.model_validate(r[1], from_attributes=True) for r in rows]
    return {"items": items, "total": total}


@router.get(
    "/effective/daily",
    summary="Эффективная дневная цель (оператор на дату)",
)
async def effective_daily_target(
    operator_id: int = Query(..., description="ID оператора"),
    day: dt.date = Query(..., description="Дата YYYY-MM-DD"),
    metric: PlanMetric = Query(..., description="Метрика"),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Вернуть «эффективную» дневную цель с указанием источника.

    # Приоритет источников
    1) operator + day/total  
    2) operator + month/per_day  
    3) department + day/total  
    4) department + month/per_day

    # Возвращает
    ```
    {
      "operator_id": 42,
      "date": "2025-08-12",
      "metric": "indicators_done",
      "daily_target": 30,         # или null
      "source": "operator/day"    # или другой источник/NULL
    }
    ```
    """
    value, source = await effective_daily_value(db, operator_id=operator_id, day=day, metric=metric)
    return {"operator_id": operator_id, "date": day, "metric": metric, "daily_target": value, "source": source}
