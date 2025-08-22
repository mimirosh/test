"""Call logs endpoints: list logs with filters/pagination; get by id."""

import datetime as dt
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from database.models import CallLogs
from endpoints.auth import get_current_user
from pydantic import BaseModel

router = APIRouter(prefix="/call-logs", tags=["CallLogs"])


# ===== Pydantic =====
class CallLogOut(BaseModel):
    """DTO для строки call_logs."""
    id: int
    call_id: str
    call_start: dt.datetime
    call_type: int
    operator_id: Optional[int]
    duration: Optional[int]
    phone_number: Optional[str]
    crm_entity_id: Optional[str]
    crm_entity_type: Optional[str]

    class Config:
        orm_mode = True


class CallLogListResponse(BaseModel):
    """Коллекция логов с total (для пагинации)."""
    items: List[CallLogOut]
    total: int


# ===== Handlers =====
@router.get(
    "/",
    response_model=CallLogListResponse,
    summary="Список логов звонков",
    description="Возвращает логи с пагинацией/фильтрами; total считается в одном запросе. Формат даты `YYYY-MM-DD`",
)
async def list_call_logs(
    skip: int = 0,
    limit: int = 10,
    operator_id: Optional[int] = None,
    call_type: Optional[int] = None,
    crm_entity_type: Optional[str] = None,
    phone_like: Optional[str] = None,
    date_from: Optional[dt.date] = None,
    date_to: Optional[dt.date] = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """
    Query:
        skip, limit — пагинация  
        operator_id — фильтр по оператору  
        call_type — фильтр по типу звонка  
        crm_entity_type — тип CRM сущности  
        phone_like — подстрочный поиск номера  
        date_from / date_to — диапазон по call_start (включительно)
    """
    filters = []
    if operator_id is not None:
        filters.append(CallLogs.operator_id == operator_id)
    if call_type is not None:
        filters.append(CallLogs.call_type == call_type)
    if crm_entity_type:
        filters.append(CallLogs.crm_entity_type == crm_entity_type)
    if phone_like:
        filters.append(CallLogs.phone_number.ilike(f"%{phone_like}%"))
    if date_from:
        filters.append(CallLogs.call_start >= dt.datetime.combine(date_from, dt.time.min))
    if date_to:
        filters.append(CallLogs.call_start <= dt.datetime.combine(date_to, dt.time.max))

    stmt = (
        select(func.count().over().label("total"), *CallLogs.__table__.columns)
        .where(*filters)
        .order_by(CallLogs.call_start.desc(), CallLogs.id.desc())
        .offset(skip)
        .limit(limit)
    )
    res = await db.execute(stmt)
    rows = res.all()
    if not rows:
        return {"items": [], "total": 0}

    total = rows[0].total
    cols = [c.name for c in CallLogs.__table__.columns]
    items = [CallLogOut(**{c: getattr(r, c) for c in cols}) for r in rows]
    return {"items": items, "total": total}


@router.get(
    "/{log_id}",
    response_model=CallLogOut,
    summary="Лог по id",
    description="Возвращает одну запись call_logs по её идентификатору.",
)
async def get_call_log(
    log_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    res = await db.execute(select(CallLogs).where(CallLogs.id == log_id))
    row = res.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Call log not found")
    return CallLogOut.model_validate(row, from_attributes=True)
