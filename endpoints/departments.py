"""Departments endpoints: list departments with optional head (uf_head)."""

import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional

from database.session import get_db
from database.models import Departments
from pydantic import BaseModel

from endpoints.auth import get_current_user  # защита токеном

router = APIRouter(prefix="/departments", tags=["Departments"])


class DepartmentResponse(BaseModel):
    """DTO для отдела в списке."""
    id: int
    name: str
    uf_head: Optional[int]

    class Config:
        orm_mode = True


@router.get(
    "/",
    response_model=List[DepartmentResponse],
    summary="Все отделы",
    description="Список всех отделов с id и руководителями (uf_head).",
    response_description="Список отделов и id руководителей",
)
async def get_departments(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """
    Возвращает упорядоченный список отделов.

    Query:
        (нет)

    Security:
        Требуется Bearer JWT (см. `/auth/token`).

    Returns:
        List[DepartmentResponse]: список отделов.

    Example:
        curl -H "Authorization: Bearer <TOKEN>" http://localhost:8006/departments/
    """
    query = select(Departments.id, Departments.name, Departments.uf_head).order_by(Departments.name)
    result = await db.execute(query)
    return [
        DepartmentResponse(id=row.id, name=row.name, uf_head=row.uf_head)
        for row in result
    ]
