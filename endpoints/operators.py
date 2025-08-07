import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.session import get_db
from database.models import Operators  # Импортируем вашу модель
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(prefix="/operators", tags=["Operators"])

class OperatorResponse(BaseModel):
    id: int
    name: Optional[str]
    last_name: Optional[str]
    email: Optional[str]
    date_register: Optional[datetime.datetime]
    active: Optional[bool]
    update_at: Optional[datetime.datetime]
    uf_department: Optional[str]
    photo: Optional[str]

@router.get("/", response_model=List[OperatorResponse], summary='Все менеджеры', description='Получение информации по всем менеджерам', response_description='Список менеджеров')
async def get_operators(skip: int = 0, limit: int = 10, active: Optional[bool] = None, db: AsyncSession = Depends(get_db)):
    query = select(Operators).offset(skip).limit(limit)
    if active is not None:
        query = query.where(Operators.active == active)  # Фильтр по active
    result = await db.execute(query)
    return result.scalars().all()

@router.get("/{operator_id}", response_model=OperatorResponse, summary='Менеджер по id', description='Получение информации по конкретному менеджеру', response_description='Менеджер')
async def get_operator(operator_id: int, db: AsyncSession = Depends(get_db)):
    query = select(Operators).where(Operators.id == operator_id)
    result = await db.execute(query)
    operator = result.scalar_one_or_none()
    if operator is None:
        raise HTTPException(status_code=404, detail="Operator not found")
    return operator