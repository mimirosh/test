# admin_views.py
from __future__ import annotations

import csv
import io
from typing import Iterable, List

from sqladmin_async import ModelView, action
from sqladmin.filters import BooleanFilter, AllUniqueStringValuesFilter, ForeignKeyFilter
from starlette.responses import StreamingResponse, PlainTextResponse

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Operators,
    Departments,
    Calls,
    CallLogs,
    CallStats,
    PlanTargets,
)

# ===== helpers ===============================================================

def _session(request) -> AsyncSession:
    """Берём async-engine, который ты положишь в app.state.admin_engine (см. main.py)."""
    engine = getattr(request.app.state, "admin_engine", None)
    if engine is None:
        raise RuntimeError("admin_engine is not configured on app.state.admin_engine")
    return AsyncSession(bind=engine)

def _csv_response(filename: str, headers: list[str], rows: Iterable[Iterable]):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow(r)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

# ===== Operators =============================================================

class OperatorsAdmin(ModelView, model=Operators):
    name = "Operator"
    name_plural = "Operators"
    icon = "fa-solid fa-user"
    column_list = [
        Operators.id,
        Operators.last_name,
        Operators.name,
        Operators.email,
        Operators.active,
        Operators.uf_department,
        Operators.date_register,
        Operators.update_at,
    ]
    column_searchable_list = [Operators.name, Operators.last_name, Operators.email]
    column_filters = [BooleanFilter(Operators.active)]
    form_excluded_columns = [
        "calls",
        "call_logs",
        "call_stats",
        "departments",
        "headed_departments",
        # "password_hash",  # оставь скрытым, если оно есть в модели
    ]
    page_size = 25

    @action(
        name="activate",
        label="Activate",
        confirmation_message="Активировать выбранных операторов?",
    )
    async def activate(self, request, pks: List[str]):
        ids = [int(x) for x in pks]
        async with _session(request) as s:
            await s.execute(
                update(Operators)
                .where(Operators.id.in_(ids))
                .values(active=True, update_at=func.now())
            )
            await s.commit()
        return PlainTextResponse("Done")

    @action(
        name="deactivate",
        label="Deactivate",
        confirmation_message="Деактивировать выбранных операторов?",
    )
    async def deactivate(self, request, pks: List[str]):
        ids = [int(x) for x in pks]
        async with _session(request) as s:
            await s.execute(
                update(Operators)
                .where(Operators.id.in_(ids))
                .values(active=False, update_at=func.now())
            )
            await s.commit()
        return PlainTextResponse("Done")

    @action(
        name="export_csv",
        label="Export CSV",
        confirmation_message="Экспортировать выбранных операторов в CSV?",
    )
    async def export_csv(self, request, pks: List[str]):
        ids = [int(x) for x in pks]
        async with _session(request) as s:
            rows = (
                await s.execute(
                    select(
                        Operators.id,
                        Operators.last_name,
                        Operators.name,
                        Operators.email,
                        Operators.active,
                        Operators.uf_department,
                        Operators.date_register,
                        Operators.update_at,
                    ).where(Operators.id.in_(ids))
                )
            ).all()
        headers = [
            "id",
            "last_name",
            "name",
            "email",
            "active",
            "uf_department",
            "date_register",
            "update_at",
        ]
        return _csv_response("operators.csv", headers, rows)

# ===== Departments ===========================================================

class DepartmentsAdmin(ModelView, model=Departments):
    name = "Department"
    name_plural = "Departments"
    icon = "fa-solid fa-building"
    column_list = [Departments.id, Departments.name, Departments.uf_head]
    column_searchable_list = [Departments.name]
    page_size = 25

# ===== PlanTargets ===========================================================

class PlanTargetsAdmin(ModelView, model=PlanTargets):
    name = "Plan target"
    name_plural = "Plan targets"
    icon = "fa-solid fa-bullseye"
    column_list = [
        PlanTargets.id,
        PlanTargets.period_type,
        PlanTargets.target_mode,
        PlanTargets.metric,
        PlanTargets.period_date,
        PlanTargets.target_value,
        PlanTargets.department_id,
        PlanTargets.operator_id,
        PlanTargets.created_by,
        PlanTargets.created_at,
        PlanTargets.updated_at,
    ]
    column_filters = [
        AllUniqueStringValuesFilter(PlanTargets.period_type),
        AllUniqueStringValuesFilter(PlanTargets.target_mode),
        AllUniqueStringValuesFilter(PlanTargets.metric),
        ForeignKeyFilter(PlanTargets.department_id, Departments.name),
        ForeignKeyFilter(PlanTargets.operator_id, Operators.name),
    ]
    form_excluded_columns = []
    page_size = 50

    @action(
        name="export_csv",
        label="Export CSV",
        confirmation_message="Экспортировать выбранные таргеты в CSV?",
    )
    async def export_csv(self, request, pks: List[str]):
        ids = [int(x) for x in pks]
        async with _session(request) as s:
            rows = (await s.execute(
                select(
                    PlanTargets.id,
                    PlanTargets.period_type,
                    PlanTargets.target_mode,
                    PlanTargets.metric,
                    PlanTargets.period_date,
                    PlanTargets.target_value,
                    PlanTargets.department_id,
                    PlanTargets.operator_id,
                    PlanTargets.created_by,
                    PlanTargets.created_at,
                    PlanTargets.updated_at,
                ).where(PlanTargets.id.in_(ids))
            )).all()
        headers = [
            "id",
            "period_type",
            "target_mode",
            "metric",
            "period_date",
            "target_value",
            "department_id",
            "operator_id",
            "created_by",
            "created_at",
            "updated_at",
        ]
        return _csv_response("plan_targets.csv", headers, rows)

# ===== Calls =================================================================

class CallsAdmin(ModelView, model=Calls):
    name = "Call"
    name_plural = "Calls"
    icon = "fa-solid fa-phone"
    column_list = [
        Calls.id,
        Calls.call_start_date,
        Calls.phone_number,
        Calls.operator_id,
        Calls.call_duration,
        Calls.transcription_status,
        Calls.analysis_status,
        Calls.indicators_done,
        Calls.indicators_total,
        Calls.penalty_sum,
        Calls.stages_done,
        Calls.stages_total,
        Calls.deleted_at,
        Calls.updated_at,
    ]
    column_searchable_list = [Calls.phone_number]
    column_filters = [
        ForeignKeyFilter(Calls.operator_id, Operators.name),
        AllUniqueStringValuesFilter(Calls.transcription_status),
        AllUniqueStringValuesFilter(Calls.analysis_status),
    ]
    form_excluded_columns = [
        "transcription",  # тяжёлые JSONB
        "analysis",
    ]
    page_size = 50

    @action(
        name="restart_transcription",
        label="Restart transcription",
        confirmation_message="Поставить выбранные звонки в транскрипцию (pending)?",
    )
    async def restart_transcription(self, request, pks: List[str]):
        ids = [int(x) for x in pks]
        async with _session(request) as s:
            await s.execute(
                update(Calls)
                .where(Calls.id.in_(ids))
                .values(
                    transcription_status="pending",
                    transcription_retries=func.coalesce(Calls.transcription_retries, 0) + 1,
                    updated_at=func.now(),
                )
            )
            await s.commit()
        return PlainTextResponse("Queued for transcription")

    @action(
        name="restart_analysis",
        label="Restart analysis",
        confirmation_message="Поставить выбранные звонки в анализ (pending)?",
    )
    async def restart_analysis(self, request, pks: List[str]):
        ids = [int(x) for x in pks]
        async with _session(request) as s:
            await s.execute(
                update(Calls)
                .where(Calls.id.in_(ids))
                .values(
                    analysis_status="pending",
                    analysis_retries=func.coalesce(Calls.analysis_retries, 0) + 1,
                    updated_at=func.now(),
                )
            )
            await s.commit()
        return PlainTextResponse("Queued for analysis")

    @action(
        name="soft_delete",
        label="Soft delete",
        confirmation_message="Пометить выбранные звонки как удалённые (deleted_at=now())?",
    )
    async def soft_delete(self, request, pks: List[str]):
        ids = [int(x) for x in pks]
        async with _session(request) as s:
            await s.execute(
                update(Calls)
                .where(Calls.id.in_(ids))
                .values(deleted_at=func.now(), updated_at=func.now())
            )
            await s.commit()
        return PlainTextResponse("Soft-deleted")

    @action(
        name="export_csv",
        label="Export CSV",
        confirmation_message="Экспортировать выбранные звонки в CSV?",
    )
    async def export_csv(self, request, pks: List[str]):
        ids = [int(x) for x in pks]
        async with _session(request) as s:
            rows = (await s.execute(
                select(
                    Calls.id,
                    Calls.call_start_date,
                    Calls.phone_number,
                    Calls.operator_id,
                    Calls.call_duration,
                    Calls.transcription_status,
                    Calls.analysis_status,
                    Calls.indicators_done,
                    Calls.indicators_total,
                    Calls.penalty_sum,
                    Calls.stages_done,
                    Calls.stages_total,
                ).where(Calls.id.in_(ids))
            )).all()
        headers = [
            "id",
            "call_start_date",
            "phone_number",
            "operator_id",
            "call_duration",
            "transcription_status",
            "analysis_status",
            "indicators_done",
            "indicators_total",
            "penalty_sum",
            "stages_done",
            "stages_total",
        ]
        return _csv_response("calls.csv", headers, rows)

# ===== CallLogs ===============================================================

class CallLogsAdmin(ModelView, model=CallLogs):
    name = "Call log"
    name_plural = "Call logs"
    icon = "fa-regular fa-rectangle-list"
    column_list = [
        CallLogs.id,
        CallLogs.call_start,
        CallLogs.operator_id,
        CallLogs.call_type,
        CallLogs.duration,
        CallLogs.phone_number,
        CallLogs.crm_entity_type,
        CallLogs.crm_entity_id,
    ]
    column_searchable_list = [CallLogs.phone_number, CallLogs.crm_entity_id]
    column_filters = [ForeignKeyFilter(CallLogs.operator_id, Operators.name), AllUniqueStringValuesFilter(CallLogs.call_type)]
    page_size = 50

    @action(
        name="export_csv",
        label="Export CSV",
        confirmation_message="Экспортировать выбранные логи в CSV?",
    )
    async def export_csv(self, request, pks: List[str]):
        ids = [int(x) for x in pks]
        async with _session(request) as s:
            rows = (await s.execute(
                select(
                    CallLogs.id,
                    CallLogs.call_start,
                    CallLogs.operator_id,
                    CallLogs.call_type,
                    CallLogs.duration,
                    CallLogs.phone_number,
                    CallLogs.crm_entity_type,
                    CallLogs.crm_entity_id,
                ).where(CallLogs.id.in_(ids))
            )).all()
        headers = [
            "id",
            "call_start",
            "operator_id",
            "call_type",
            "duration",
            "phone_number",
            "crm_entity_type",
            "crm_entity_id",
        ]
        return _csv_response("call_logs.csv", headers, rows)

# ===== CallStats ==============================================================

class CallStatsAdmin(ModelView, model=CallStats):
    name = "Daily stat"
    name_plural = "Daily stats"
    icon = "fa-solid fa-chart-column"
    column_list = [
        CallStats.id,
        CallStats.call_date,
        CallStats.operator_id,
        CallStats.total_calls,
        CallStats.successful_calls,
        CallStats.incoming_calls,
        CallStats.outgoing_calls,
        CallStats.total_duration,
        CallStats.missed_calls,
        CallStats.average_duration,
    ]
    column_filters = [ForeignKeyFilter(CallStats.operator_id, Operators.name)]
    page_size = 50

    @action(
        name="export_csv",
        label="Export CSV",
        confirmation_message="Экспортировать выбранные записи в CSV?",
    )
    async def export_csv(self, request, pks: List[str]):
        ids = [int(x) for x in pks]
        async with _session(request) as s:
            rows = (await s.execute(
                select(
                    CallStats.id,
                    CallStats.call_date,
                    CallStats.operator_id,
                    CallStats.total_calls,
                    CallStats.successful_calls,
                    CallStats.incoming_calls,
                    CallStats.outgoing_calls,
                    CallStats.total_duration,
                    CallStats.missed_calls,
                    CallStats.average_duration,
                ).where(CallStats.id.in_(ids))
            )).all()
        headers = [
            "id",
            "call_date",
            "operator_id",
            "total_calls",
            "successful_calls",
            "incoming_calls",
            "outgoing_calls",
            "total_duration",
            "missed_calls",
            "average_duration",
        ]
        return _csv_response("call_stats.csv", headers, rows)