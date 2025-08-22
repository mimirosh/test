"""Call stats endpoints: list daily/operator aggregates; get by id."""

from __future__ import annotations
import datetime as dt
from typing import List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from database.models import CallStats, t_operator_departments
from endpoints.auth import get_current_user
from pydantic import BaseModel

router = APIRouter(prefix="/call-stats", tags=["CallStats"])


# ===== Pydantic =====
class CallStatOut(BaseModel):
    """DTO агрегатов по звонкам на дату/оператора."""
    id: int
    call_date: dt.date
    operator_id: Optional[int]
    total_calls: Optional[int]
    successful_calls: Optional[int]
    incoming_calls: Optional[int]
    outgoing_calls: Optional[int]
    total_duration: Optional[int]
    missed_calls: Optional[int]
    average_duration: Optional[float]

    class Config:
        orm_mode = True


class CallStatListResponse(BaseModel):
    items: List[CallStatOut]
    total: int


# ===== Handlers =====
@router.get(
    "/",
    response_model=CallStatListResponse,
    summary="Список агрегатов по звонкам",
    description="Постраничный список статистики по операторам/датам. Формат даты `YYYY-MM-DD`",
)
async def list_call_stats(
    skip: int = 0,
    limit: int = 10,
    operator_id: Optional[int] = None,
    date_from: Optional[dt.date] = None,
    date_to: Optional[dt.date] = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """
    Query:
        skip, limit — пагинация  
        operator_id — фильтр по оператору  
        date_from / date_to — диапазон дат (включительно)
    """
    filters = []
    if operator_id is not None:
        filters.append(CallStats.operator_id == operator_id)
    if date_from:
        filters.append(CallStats.call_date >= date_from)
    if date_to:
        filters.append(CallStats.call_date <= date_to)

    stmt = (
        select(func.count().over().label("total"), *CallStats.__table__.columns)
        .where(*filters)
        .order_by(CallStats.call_date.desc(), CallStats.id.desc())
        .offset(skip)
        .limit(limit)
    )
    res = await db.execute(stmt)
    rows = res.all()
    if not rows:
        return {"items": [], "total": 0}

    total = rows[0].total
    cols = [c.name for c in CallStats.__table__.columns]
    items = [CallStatOut(**{c: getattr(r, c) for c in cols}) for r in rows]
    return {"items": items, "total": total}

Metric = Literal[
    "total_calls",
    "successful_calls",
    "incoming_calls",
    "outgoing_calls",
    "total_duration",
    "missed_calls",
    "average_duration",
]

Mode = Literal["dod", "wow", "mom", "yoy"]


# ---------- helpers ----------

def _month_bounds(any_date: dt.date) -> tuple[dt.date, dt.date]:
    start = any_date.replace(day=1)
    # «следующий месяц, 1-е» → минус день
    next_month = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    end = next_month - dt.timedelta(days=1)
    return start, end


def _week_bounds(any_date: dt.date) -> tuple[dt.date, dt.date]:
    # ISO: monday=0..sunday=6
    monday = any_date - dt.timedelta(days=any_date.weekday())
    sunday = monday + dt.timedelta(days=6)
    return monday, sunday


def _periods(mode: Mode, at: dt.date) -> tuple[tuple[dt.date, dt.date], tuple[dt.date, dt.date]]:
    """Вернёт (period1, period2) как (start,end) с учётом режима."""
    if mode == "dod":
        p1 = (at, at)
        p2 = (at - dt.timedelta(days=1), at - dt.timedelta(days=1))
    elif mode == "wow":
        s1, e1 = _week_bounds(at)
        s2, e2 = _week_bounds(s1 - dt.timedelta(days=1))
        p1, p2 = (s1, e1), (s2, e2)
    elif mode == "mom":
        s1, e1 = _month_bounds(at)
        s2, e2 = _month_bounds(s1 - dt.timedelta(days=1))
        p1, p2 = (s1, e1), (s2, e2)
    else:  # "yoy"
        year1 = at.year
        year2 = year1 - 1
        p1 = (dt.date(year1, 1, 1), dt.date(year1, 12, 31))
        p2 = (dt.date(year2, 1, 1), dt.date(year2, 12, 31))
    return p1, p2


async def _agg_value(
    db: AsyncSession,
    *,
    metric: Metric,
    operator_id: int | None,
    department_id: int | None,
    start: dt.date,
    end: dt.date,
) -> float:
    """
    Считает агрегат по call_stats за [start..end].
    Для department_id — суммирует по всем операторам отдела (M2M).
    Для average_duration — взвешенное среднее: sum(total_duration) / nullif(sum(total_calls),0)
    Помимо этого NULL обнуляем до 0.
    """
    date_cond = and_(CallStats.call_date >= start, CallStats.call_date <= end)

    if metric == "average_duration":
        expr = func.sum(func.coalesce(CallStats.total_duration, 0)) / func.nullif(
            func.sum(func.coalesce(CallStats.total_calls, 0)), 0
        )
    else:
        column = getattr(CallStats, metric)
        expr = func.sum(func.coalesce(column, 0))

    if operator_id is not None:
        stmt = select(expr).where(CallStats.operator_id == operator_id, date_cond)
    else:
        # department: join операторов из operator_departments
        stmt = (
            select(expr)
            .select_from(
                CallStats.__table__.join(
                    t_operator_departments,
                    CallStats.operator_id == t_operator_departments.c.operator_id,
                )
            )
            .where(t_operator_departments.c.department_id == department_id, date_cond)
        )

    val = (await db.execute(stmt)).scalar()
    # для average_duration expr может дать None при нулевом делителе
    return float(val) if val is not None else 0.0


# ---------- schemas ----------

class PeriodValue(BaseModel):
    start: dt.date
    end: dt.date
    value: float


class CompareResponse(BaseModel):
    scope: dict
    metric: Metric
    mode: Mode
    at: dt.date
    period1: PeriodValue
    period2: PeriodValue
    delta: float
    pct_change: Optional[float]


# ---------- endpoint ----------

@router.get(
    "/compare",
    response_model=CompareResponse,
    summary="Сравнение агрегатов call_stats между периодами",
    description=(
        "Этот эндпоинт суммирует выбранную метрику из таблицы `call_stats` (статистика звонков) "
        "и сравнивает значения между двумя периодами для одного субъекта — либо конкретного оператора "
        "(по `operator_id`), либо отдела (по `department_id`). "
        "Сравнение проводится в одном из режимов: день к предыдущему дню, неделя к предыдущей неделе и т.д. "
        "Метрика агрегируется (суммируется) за каждый период. "
        "Для метрики `average_duration` используется специальный расчёт: `sum(total_duration) / sum(total_calls)` "
        "(если звонков нет, значение будет 0).\n\n"
        
        "### Режимы сравнения (`mode`):\n"
        "- **dod**: День к предыдущему дню (день на основе `at` vs. день до него).\n"
        "- **wow**: Неделя к предыдущей неделе (ISO-неделя: понедельник–воскресенье, на основе даты `at`).\n"
        "- **mom**: Месяц к предыдущему месяцу (полный месяц на основе `at`).\n"
        "- **yoy**: Год к предыдущему году (полный год на основе `at`).\n\n"
        
        "### Параметры запроса:\n"
        "- **metric** (обязательный): Метрика из `call_stats`. Возможные значения: "
        "`total_calls`, `successful_calls`, `incoming_calls`, `outgoing_calls`, `total_duration`, "
        "`missed_calls`, `average_duration`.\n"
        "- **mode** (обязательный): Режим сравнения — `dod`, `wow`, `mom` или `yoy`.\n"
        "- **at** (обязательный): Дата-якорь в формате `YYYY-MM-DD`. Определяет текущий период "
        "(например, для `dod` — это сам день, для `wow` — любой день недели).\n"
        "- **operator_id** (опциональный): ID оператора. Укажите ровно один из `operator_id` или `department_id`.\n"
        "- **department_id** (опциональный): ID отдела. Укажите ровно один из `operator_id` или `department_id`.\n\n"
        
        "### Валидация:\n"
        "- Должен быть указан **ровно один** субъект: либо `operator_id`, либо `department_id`. Иначе — ошибка 400.\n\n"
        
        "### Ответ (JSON):\n"
        "- **scope**: Объект с субъектом сравнения (либо `{\"operator_id\": <ID>}`, либо `{\"department_id\": <ID>}`).\n"
        "- **metric**: Выбранная метрика.\n"
        "- **mode**: Выбранный режим.\n"
        "- **at**: Дата-якорь.\n"
        "- **period1**: Текущий период — объект с `start` (начало, `YYYY-MM-DD`), `end` (конец, `YYYY-MM-DD`) и `value` (значение метрики).\n"
        "- **period2**: Предыдущий период — аналогично `period1`.\n"
        "- **delta**: Разница: `period1.value - period2.value`.\n"
        "- **pct_change**: Процент изменения: `delta / period2.value` (null, если `period2.value` = 0).\n\n"
        
        "### Пример ответа:\n"
        "```json\n"
        "{\n"
        "  \"scope\": {\"operator_id\": 12},\n"
        "  \"metric\": \"total_calls\",\n"
        "  \"mode\": \"mom\",\n"
        "  \"at\": \"2025-08-12\",\n"
        "  \"period1\": {\"start\": \"2025-08-01\", \"end\": \"2025-08-31\", \"value\": 1234},\n"
        "  \"period2\": {\"start\": \"2025-07-01\", \"end\": \"2025-07-31\", \"value\": 1100},\n"
        "  \"delta\": 134,\n"
        "  \"pct_change\": 0.1218\n"
        "}\n"
        "```\n\n"
        
        "Если в периодах нет данных, значения будут 0. Для метрик типа длительности — в секундах."
    ),
)
async def compare_call_stats(
    metric: Metric = Query(..., description="Метрика из call_stats"),
    mode: Mode = Query(..., description="Режим сравнения: dod|wow|mom|yoy"),
    at: dt.date = Query(..., description="Дата-якорь (см. описание)"),
    operator_id: Optional[int] = Query(None, description="ID оператора (если сравниваем оператора)"),
    department_id: Optional[int] = Query(None, description="ID отдела (если сравниваем отдел)"),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    # валидация субъекта
    if (operator_id is None and department_id is None) or (
        operator_id is not None and department_id is not None
    ):
        raise HTTPException(status_code=400, detail="Укажи ровно один из: operator_id или department_id")

    (p1s, p1e), (p2s, p2e) = _periods(mode, at)

    v1 = await _agg_value(
        db, metric=metric, operator_id=operator_id, department_id=department_id, start=p1s, end=p1e
    )
    v2 = await _agg_value(
        db, metric=metric, operator_id=operator_id, department_id=department_id, start=p2s, end=p2e
    )

    delta = v1 - v2
    pct_change = (delta / v2) if v2 not in (0, 0.0) else None

    scope = {"operator_id": operator_id} if operator_id is not None else {"department_id": department_id}
    return CompareResponse(
        scope=scope,
        metric=metric,
        mode=mode,
        at=at,
        period1=PeriodValue(start=p1s, end=p1e, value=v1),
        period2=PeriodValue(start=p2s, end=p2e, value=v2),
        delta=delta,
        pct_change=pct_change,
    )

@router.get(
    "/{stat_id}",
    response_model=CallStatOut,
    summary="Статистика по id",
    description="Возвращает одну запись call_stats по её идентификатору.",
)
async def get_call_stat(
    stat_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    res = await db.execute(select(CallStats).where(CallStats.id == stat_id))
    row = res.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Call stat not found")
    return CallStatOut.model_validate(row, from_attributes=True)