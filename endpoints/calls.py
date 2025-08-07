import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func  # Добавляем func для count
from database.session import get_db
from database.models import Calls  # Импортируем модель Calls
from pydantic import BaseModel

router = APIRouter(prefix="/calls", tags=["Calls"])

class CallResponse(BaseModel):
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

# Новая модель для ответа с total
class CallListResponse(BaseModel):
    items: List[CallResponse]
    total: int

@router.get("/", response_model=CallListResponse, summary='Все звонки', description='Получение информации по всем звонкам', response_description='Список звонков')
async def get_calls(skip: int = 0, limit: int = 10, operator_id: Optional[int] = None, transcription_status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    # Базовый запрос для count и select
    base_query = select(Calls)
    if operator_id is not None:
        base_query = base_query.where(Calls.operator_id == operator_id)
    if transcription_status is not None:
        base_query = base_query.where(Calls.transcription_status == transcription_status)
    
    # Получаем total (count с теми же фильтрами)
    count_query = select(func.count()).select_from(base_query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar()  # Общее количество
    
    # Получаем список items с пагинацией
    items_query = base_query.offset(skip).limit(limit)
    items_result = await db.execute(items_query)
    items = items_result.scalars().all()
    
    return {"items": items, "total": total}

@router.get("/{call_id}", response_model=CallResponse, summary='Звонок по id', description='Получение информации по конкретному звонку', response_description='Звонок')
async def get_call(call_id: int, db: AsyncSession = Depends(get_db)):
    query = select(Calls).where(Calls.id == call_id)
    result = await db.execute(query)
    call = result.scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=404, detail="Call not found")
    return call