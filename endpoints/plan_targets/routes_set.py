from __future__ import annotations
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from endpoints.auth import get_current_user
from database.models import PlanTargets
from .schemas import SetMonthIn, SetDayIn, PlanTargetOut
from .repo import assert_subject_exists, upsert_month_target, upsert_day_target

router = APIRouter()

@router.post(
    "/set-month",
    summary="Установить месячные цели (per_day и/или total) для отдела или оператора",
    response_model=List[PlanTargetOut],
)
async def set_month_targets(
    body: SetMonthIn = Body(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    ok, err = await assert_subject_exists(db, operator_id=body.operator_id, department_id=body.department_id)
    if not ok:
        raise HTTPException(status_code=404, detail=err)

    ids: list[int] = []
    if body.per_day is not None:
        ids.append(await upsert_month_target(
            db,
            metric=body.metric,
            month1=body.month,                 # уже dt.date
            value=body.per_day,
            created_by=getattr(user, "user_id", None),
            department_id=body.department_id,
            operator_id=body.operator_id,
            target_mode="per_day",
        ))
    if body.total is not None:
        ids.append(await upsert_month_target(
            db,
            metric=body.metric,
            month1=body.month,                 # уже dt.date
            value=body.total,
            created_by=getattr(user, "user_id", None),
            department_id=body.department_id,
            operator_id=body.operator_id,
            target_mode="total",
        ))
    await db.commit()

    rows = (await db.execute(select(PlanTargets).where(PlanTargets.id.in_(ids)))).scalars().all()
    return [PlanTargetOut.model_validate(r, from_attributes=True) for r in rows]


@router.post(
    "/set-day",
    summary="Поставить дневной таргет (day/total) отделу или оператору",
    response_model=List[PlanTargetOut],
)
async def set_day_target(
    body: SetDayIn = Body(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    ok, err = await assert_subject_exists(db, operator_id=body.operator_id, department_id=body.department_id)
    if not ok:
        raise HTTPException(status_code=404, detail=err)

    pid = await upsert_day_target(
        db,
        metric=body.metric,
        day=body.day,                           # уже dt.date
        value=body.value,
        created_by=getattr(user, "user_id", None),
        department_id=body.department_id,
        operator_id=body.operator_id,
    )
    await db.commit()

    row = (await db.execute(select(PlanTargets).where(PlanTargets.id == pid))).scalar_one()
    return [PlanTargetOut.model_validate(row, from_attributes=True)]
