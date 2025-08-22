from __future__ import annotations
import datetime as dt
from typing import Literal, Optional, List
from pydantic import BaseModel, Field, field_validator, model_validator

# Разрешённые метрики (должны 1-в-1 совпадать с ENUM plan_metric в БД)
PlanMetric = Literal[
    "calls_total",
    "calls_success",
    "clients_total",
    "clients_success",
    "avg_duration",
    "total_talk_time",
    # если ты расширил ENUM в БД — добавь новые ниже:
    "indicators_done",
    "penalty_sum",
    "stages_done",
]

class SetMonthIn(BaseModel):
    """
    Установка месячных целей на одну метрику для отдела ИЛИ оператора.
    Можно задать дневную норму (per_day) и/или месячный итог (total).
    """
    month: dt.date = Field(..., description="Любая дата внутри месяца; нормализуется к 1-му числу")
    metric: PlanMetric
    department_id: Optional[int] = Field(None, description="ID отдела (если не указан operator_id)")
    operator_id: Optional[int]   = Field(None, description="ID оператора (если не указан department_id)")
    per_day: Optional[int] = Field(None, ge=0, description="Дневная норма на месяц")
    total:   Optional[int] = Field(None, ge=0, description="Итог за месяц")

    @field_validator("month")
    @classmethod
    def normalize_month(cls, v: dt.date) -> dt.date:
        return v.replace(day=1)

    @model_validator(mode="after")
    def check_subject_and_targets(self):
        dep = self.department_id
        op  = self.operator_id
        if (dep is None and op is None) or (dep is not None and op is not None):
            raise ValueError("Укажи ровно один из: department_id или operator_id.")
        if self.per_day is None and self.total is None:
            raise ValueError("Нужно указать хотя бы одно из: per_day или total.")
        return self


class SetDayIn(BaseModel):
    """
    Установка точечного дневного таргета (day/total) на дату по метрике.
    """
    day: dt.date
    metric: PlanMetric
    department_id: Optional[int] = Field(None, description="ID отдела (если не указан operator_id)")
    operator_id: Optional[int]   = Field(None, description="ID оператора (если не указан department_id)")
    value: int = Field(..., ge=0, description="Значение дневной цели")

    @model_validator(mode="after")
    def check_subject(self):
        dep = self.department_id
        op  = self.operator_id
        if (dep is None and op is None) or (dep is not None and op is not None):
            raise ValueError("Укажи ровно один из: department_id или operator_id.")
        return self


class PlanTargetOut(BaseModel):
    """DTO строки plan_targets."""
    id: int
    period_type: Literal["day", "month"]
    target_mode: Literal["per_day", "total"]
    metric: PlanMetric
    period_date: dt.date
    target_value: int
    department_id: Optional[int]
    operator_id: Optional[int]
    created_by: Optional[int]
    created_at: Optional[dt.datetime]
    updated_at: Optional[dt.datetime]

    model_config = {"from_attributes": True}

class ListOut(BaseModel):
    """Список с total — удобно для UI пагинации."""
    items: List[PlanTargetOut]
    total: int

class EvaluateDailyOut(BaseModel):
    """Оценка выполнения за день."""
    operator_id: int
    date: dt.date
    metric: Literal["indicators_done", "penalty_sum", "stages_done"]
    actual: int
    target: Optional[int]
    source: Optional[str]
    status: Literal["good", "average", "bad", "no_target"]
    ratio: Optional[float] = None

class EvaluatePeriodOut(BaseModel):
    """Оценка выполнения за период (несколько дней)."""
    operator_id: int
    date_from: dt.date
    date_to: dt.date
    metric: Literal["indicators_done", "penalty_sum", "stages_done"]
    actual: int
    target: Optional[int]
    status: Literal["good", "average", "bad", "no_target"]
    ratio: Optional[float] = None
    days: int
    daily_breakdown: List[EvaluateDailyOut]

class EvaluateMonthlyOut(BaseModel):
    """Оценка выполнения за месяц."""
    operator_id: int
    month: dt.date  # 1 число
    metric: Literal["indicators_done", "penalty_sum", "stages_done"]
    actual: int
    target: Optional[int]
    source: Optional[str]
    status: Literal["good", "average", "bad", "no_target"]
    ratio: Optional[float] = None
    days_in_month: int
