"""Calls endpoints: list calls with filters/pagination; get by id."""

import datetime as dt
from datetime import datetime, time, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from database.models import Calls
from endpoints.auth import get_current_user
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/calls", tags=["Calls"])


# ===== Pydantic =====
class CallResponse(BaseModel):
    """DTO звонка; в списке можно отключать тяжёлые JSONB."""
    id: int
    bitrix_call_id: str
    phone_number: str
    call_start_date: dt.datetime
    call_duration: int
    record_url: Optional[str]
    file_key: Optional[str]
    operator_id: Optional[int]
    crm_entity_type: Optional[str]
    crm_entity_id: Optional[str]
    transcription: Optional[dict]
    transcription_status: Optional[str]
    analysis_status: Optional[str]
    transcription_retries: Optional[int]
    analysis_retries: Optional[int]
    created_at: Optional[dt.datetime]
    updated_at: Optional[dt.datetime]
    deleted_at: Optional[dt.datetime]
    analysis: Optional[dict]

    # новые поля
    indicators_done: int = 0
    indicators_total: int = 0
    penalty_sum: int = 0
    stages_done: int = 0
    stages_total: int = 0

    model_config = ConfigDict(from_attributes=True)


class CallListResponse(BaseModel):
    """Коллекция звонков с total (для пагинации)."""
    items: List[CallResponse]
    total: int


# ===== Handlers =====
@router.get(
    "/",
    response_model=CallListResponse,
    summary="Все звонки",
    description="Список звонков с пагинацией и фильтрами; total считается в одном запросе. Формат даты `YYYY-MM-DD`",
)
async def get_calls(
    skip: int = 0,
    limit: int = 10,
    operator_id: Optional[int] = None,
    transcription_status: Optional[str] = None,
    analysis_status: Optional[str] = None,
    date_from: Optional[dt.date] = None,
    date_to: Optional[dt.date] = None,
    phone_like: Optional[str] = None,
    include_data: bool = False,
    deleted: bool = False,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """
    Возвращает страницу звонков, применяя фильтры и сортировку.

    Query:
        skip (int): смещение; по умолчанию 0.
        limit (int): размер страницы; по умолчанию 10.
        operator_id (int, optional): фильтр по оператору.
        transcription_status (str, optional): фильтр по статусу транскрипции.
        analysis_status (str, optional): фильтр по статусу анализа.
        date_from (date, optional): с даты включительно (по call_start_date).
        date_to (date, optional): по дату включительно.
        phone_like (str, optional): подстрочный поиск по номеру телефона (ILIKE).
        include_data (bool): включать ли JSONB-поля (transcription, analysis) в списке; по умолчанию False.
        deleted (bool): показывать ли мягко удалённые (`deleted_at IS NOT NULL`); по умолчанию False.

    Поведение:
        - Результаты отсортированы по `call_start_date DESC`.
        - `total` вычисляется через `count() over()` в том же запросе.
    """
    filters = []
    if operator_id is not None:
        filters.append(Calls.operator_id == operator_id)
    if transcription_status is not None:
        filters.append(Calls.transcription_status == transcription_status)
    if analysis_status is not None:
        filters.append(Calls.analysis_status == analysis_status)
    if date_from:
        filters.append(Calls.call_start_date >= dt.datetime.combine(date_from, time.min))
    if date_to:
        filters.append(Calls.call_start_date <  dt.datetime.combine(date_to + timedelta(days=1), time.min))
    if phone_like:
        filters.append(Calls.phone_number.ilike(f"%{phone_like}%"))
    if not deleted:
        filters.append(Calls.deleted_at.is_(None))

    stmt = (
        select(func.count().over().label("total"), *Calls.__table__.columns)
        .where(*filters)
        .order_by(Calls.call_start_date.desc())
        .offset(skip)
        .limit(limit)
    )
    res = await db.execute(stmt)
    rows = res.all()
    if not rows:
        return {"items": [], "total": 0}
    
    total = rows[0].total
    cols = list(Calls.__table__.columns.keys())

    items_dicts = []
    for r in rows:
        d = {c: getattr(r, c) for c in cols}

        # если просили «лёгкий» список — глушим тяжёлые JSONB
        if not include_data:
            d["transcription"] = None
            d["analysis"] = None

        # защитимся от возможных NULL в новых числовых полях
        for k in ("indicators_done", "indicators_total", "penalty_sum", "stages_done", "stages_total"):
            if d.get(k) is None:
                d[k] = 0

        items_dicts.append(d)

    items = [CallResponse(**d) for d in items_dicts]
    return {"items": items, "total": total}


@router.get(
    "/{call_id}",
    response_model=CallResponse,
    summary="Звонок по id",
    description="Возвращает один звонок по его идентификатору.",
)
async def get_call(
    call_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """
    Возвращает объект звонка по `call_id`.
    """
    res = await db.execute(select(Calls).where(Calls.id == call_id))
    call = res.scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    # если в БД вдруг есть NULL, отдаём 0 — чтобы не падать на сериализации
    for k in ("indicators_done", "indicators_total", "penalty_sum", "stages_done", "stages_total"):
        if getattr(call, k, None) is None:
            setattr(call, k, 0)

    return CallResponse.model_validate(call, from_attributes=True)
