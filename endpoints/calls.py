"""Calls endpoints: list calls with filters/pagination; get by id."""

import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from database.models import Calls
from endpoints.auth import get_current_user
from pydantic import BaseModel

router = APIRouter(prefix="/calls", tags=["Calls"])


# ===== Pydantic =====
class CallResponse(BaseModel):
    """DTO звонка; в списке можно отключать тяжёлые JSONB."""
    id: int
    bitrix_call_id: str
    phone_number: str
    call_start_date: datetime.datetime
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
    created_at: Optional[datetime.datetime]
    updated_at: Optional[datetime.datetime]
    deleted_at: Optional[datetime.datetime]
    analysis: Optional[dict]

    class Config:
        orm_mode = True


class CallListResponse(BaseModel):
    """Коллекция звонков с total (для пагинации)."""
    items: List[CallResponse]
    total: int


# ===== Handlers =====
@router.get(
    "/",
    response_model=CallListResponse,
    summary="Все звонки",
    description="Список звонков с пагинацией и фильтрами; total считается в одном запросе.",
)
async def get_calls(
    skip: int = 0,
    limit: int = 10,
    operator_id: Optional[int] = None,
    transcription_status: Optional[str] = None,
    analysis_status: Optional[str] = None,
    date_from: Optional[datetime.date] = None,
    date_to: Optional[datetime.date] = None,
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

    Security:
        Требуется Bearer JWT.

    Returns:
        CallListResponse: элементы и общее количество.

    Example:
        curl -H "Authorization: Bearer <TOKEN>" \\
             "http://localhost:8006/calls/?date_from=2025-08-01&operator_id=10&limit=50"
    """
    filters = []
    if operator_id is not None:
        filters.append(Calls.operator_id == operator_id)
    if transcription_status is not None:
        filters.append(Calls.transcription_status == transcription_status)
    if analysis_status is not None:
        filters.append(Calls.analysis_status == analysis_status)
    if date_from:
        filters.append(Calls.call_start_date >= date_from)
    if date_to:
        filters.append(Calls.call_start_date <= date_to)
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
        if not include_data:
            d["transcription"] = None
            d["analysis"] = None
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

    Path:
        call_id (int): идентификатор звонка.

    Security:
        Требуется Bearer JWT.

    Returns:
        CallResponse: объект звонка.

    Errors:
        404 — звонок не найден.

    Example:
        curl -H "Authorization: Bearer <TOKEN>" \\
             http://localhost:8006/calls/100500
    """
    res = await db.execute(select(Calls).where(Calls.id == call_id))
    call = res.scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    return CallResponse.model_validate(call, from_attributes=True)
