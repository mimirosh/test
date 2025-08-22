"""Operators endpoints: list/search operators with departments; get by id."""

import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.session import get_db
from database.models import Operators, Departments
from endpoints.auth import get_current_user
from pydantic import BaseModel

router = APIRouter(prefix="/operators", tags=["Operators"])


# ===== Pydantic =====
class DepartmentBrief(BaseModel):
    """Короткая информация об отделе (для встраивания в оператора)."""
    id: int
    name: str
    class Config:
        orm_mode = True


class OperatorOut(BaseModel):
    """DTO оператора для ответов API."""
    id: int
    name: Optional[str]
    last_name: Optional[str]
    email: Optional[str]
    active: Optional[bool]
    photo: Optional[str]
    departments: List[DepartmentBrief] = []
    headed_departments: List[DepartmentBrief] = []
    class Config:
        orm_mode = True


class OperatorListResponse(BaseModel):
    """Коллекция операторов с total (для пагинации)."""
    items: List[OperatorOut]
    total: int


# ===== Handlers =====
@router.get("/", response_model=OperatorListResponse, summary="Все менеджеры")
async def get_operators(
    skip: int = 0,
    limit: int = 10,
    active: Optional[bool] = None,
    department_id: Optional[int] = None,
    q: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """
    Возвращает список операторов с пагинацией и фильтрами.

    Query:
        skip (int): смещение, по умолчанию 0.
        limit (int): размер страницы, по умолчанию 10.
        active (bool, optional): фильтр по активности.
        department_id (int, optional): фильтр по принадлежности к отделу (many-to-many).
        q (str, optional): поиск по имени/фамилии/email (ILIKE).

    Notes:
        - total считается через оконную функцию `count() over()`.
        - связи (departments, headed_departments) подгружаются через `selectinload`.

    Security:
        Требуется Bearer JWT.

    Returns:
        OperatorListResponse: элементы и общее количество.

    Example:
        curl -H "Authorization: Bearer <TOKEN>" \\
             "http://localhost:8006/operators/?limit=20&q=anna"
    """
    filters = []
    if active is not None:
        filters.append(Operators.active == active)
    if department_id is not None:
        filters.append(Operators.departments.any(Departments.id == department_id))
    if q:
        # Разделяем q на токены по пробелам для поиска с AND между токенами
        tokens = q.strip().split()
        for token in tokens:
            ilike = f"%{token}%"
            subfilter = (
                (Operators.name.ilike(ilike))
                | (Operators.last_name.ilike(ilike))
                | (Operators.email.ilike(ilike))
            )
            filters.append(subfilter)

    id_rows = await db.execute(
        select(func.count().over().label("total"), Operators.id)
        .where(*filters)
        .order_by(Operators.id.desc())
        .offset(skip)
        .limit(limit)
    )
    id_rows = id_rows.all()
    if not id_rows:
        return {"items": [], "total": 0}

    total = id_rows[0].total
    ids = [r.id for r in id_rows]

    obj_rows = await db.execute(
        select(Operators)
        .options(
            selectinload(Operators.departments),
            selectinload(Operators.headed_departments),
        )
        .where(Operators.id.in_(ids))
        .order_by(Operators.id.desc())
    )
    ops = obj_rows.scalars().all()

    items = [
        OperatorOut(
            id=o.id,
            name=o.name,
            last_name=o.last_name,
            email=o.email,
            active=o.active,
            photo=o.photo,
            departments=[DepartmentBrief(id=d.id, name=d.name) for d in o.departments],
            headed_departments=[DepartmentBrief(id=d.id, name=d.name) for d in o.headed_departments],
        )
        for o in ops
    ]
    return {"items": items, "total": total}


@router.get("/{operator_id}", response_model=OperatorOut, summary="Менеджер по id")
async def get_operator(
    operator_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """
    Возвращает одного оператора по `operator_id` с отделами и управляемыми отделами.

    Path:
        operator_id (int): идентификатор оператора.

    Security:
        Требуется Bearer JWT.

    Returns:
        OperatorOut: оператор с отделами.

    Errors:
        404 — если оператор не найден.

    Example:
        curl -H "Authorization: Bearer <TOKEN>" \\
             http://localhost:8006/operators/123
    """
    res = await db.execute(
        select(Operators)
        .options(
            selectinload(Operators.departments),
            selectinload(Operators.headed_departments),
        )
        .where(Operators.id == operator_id)
    )
    op = res.scalar_one_or_none()
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found")

    return OperatorOut(
        id=op.id,
        name=op.name,
        last_name=op.last_name,
        email=op.email,
        active=op.active,
        photo=op.photo,
        departments=[DepartmentBrief(id=d.id, name=d.name) for d in op.departments],
        headed_departments=[DepartmentBrief(id=d.id, name=d.name) for d in op.headed_departments],
    )
