import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.session import get_db
from database.models import Operators  # Импортируем вашу модель
from pydantic import BaseModel
from typing import List, Optional
from database.models import Departments

router = APIRouter(prefix="/departments", tags=["Departments"])
class DepartmentResponse(BaseModel):
    id: int
    name: str
    uf_head: Optional[int]

@router.get("/", response_model=List[DepartmentResponse], summary='Все отделы', description='Получение информации по всем отделам и id руководителей', response_description='Список отделов и руководителей')
async def get_departments(db: AsyncSession = Depends(get_db)):
    query = select(Departments.id, Departments.name, Departments.uf_head)
    result = await db.execute(query)
    departments = result.fetchall()
    # Преобразуем в список словарей для ответа
    return [{"id": dep.id, "name": dep.name, "uf_head": dep.uf_head} for dep in departments]