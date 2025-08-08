from __future__ import annotations

from typing import List, Optional
import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Date, DateTime,
    ForeignKeyConstraint, Index, Integer, PrimaryKeyConstraint,
    String, Table, Text, UniqueConstraint, text
)
from sqlalchemy.dialects.postgresql import JSONB, DOUBLE_PRECISION
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


# -----------------------------
# ETL state
# -----------------------------
class EtlState(Base):
    __tablename__ = "etl_state"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="etl_state_pkey"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # timestamptz
    last_processed_call_start: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))


# -----------------------------
# Operators
# -----------------------------
class Operators(Base):
    __tablename__ = "operators"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="operators_pkey"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    last_name: Mapped[Optional[str]] = mapped_column(String(255))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    # timestamp without time zone
    date_register: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    active: Mapped[Optional[bool]] = mapped_column(Boolean)
    # timestamp without time zone
    update_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    uf_department: Mapped[Optional[str]] = mapped_column(Text)
    photo: Mapped[Optional[str]] = mapped_column(Text)

    # one-to-many
    call_logs: Mapped[List["CallLogs"]] = relationship("CallLogs", back_populates="operator", lazy="selectin")
    call_stats: Mapped[List["CallStats"]] = relationship("CallStats", back_populates="operator", lazy="selectin")
    calls: Mapped[List["Calls"]] = relationship("Calls", back_populates="operator", lazy="selectin")

    # many-to-many (основная связь с отделами)
    departments: Mapped[List["Departments"]] = relationship(
        "Departments",
        secondary="operator_departments",
        back_populates="operators",
        lazy="selectin",
    )

    # отделы, где оператор является руководителем (departments.uf_head)
    headed_departments: Mapped[List["Departments"]] = relationship(
        "Departments",
        back_populates="head",
        foreign_keys=lambda: [Departments.uf_head],
        lazy="selectin",
    )


# -----------------------------
# Call logs (сырые логи)
# -----------------------------
class CallLogs(Base):
    __tablename__ = "call_logs"
    __table_args__ = (
        ForeignKeyConstraint(["operator_id"], ["operators.id"], ondelete="CASCADE", name="call_logs_operator_id_fkey"),
        PrimaryKeyConstraint("id", name="call_logs_pkey"),
        UniqueConstraint("call_id", name="call_logs_call_id_key"),
        Index("idx_call_logs_filters", "operator_id", "call_start", "call_type", "crm_entity_type"),
        Index("idx_call_logs_keyset", "call_start", "id"),
        Index("idx_operator_call_start", "operator_id", "call_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[str] = mapped_column(String(255))
    # timestamp without time zone
    call_start: Mapped[datetime.datetime] = mapped_column(DateTime)
    call_type: Mapped[int] = mapped_column(Integer)
    operator_id: Mapped[Optional[int]] = mapped_column(Integer)
    duration: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("0"))
    phone_number: Mapped[Optional[str]] = mapped_column(String(255))
    crm_entity_id: Mapped[Optional[str]] = mapped_column(String(255))
    crm_entity_type: Mapped[Optional[str]] = mapped_column(String(255))

    operator: Mapped[Optional["Operators"]] = relationship("Operators", back_populates="call_logs", lazy="selectin")


# -----------------------------
# Aggregated call stats
# -----------------------------
class CallStats(Base):
    __tablename__ = "call_stats"
    __table_args__ = (
        ForeignKeyConstraint(["operator_id"], ["operators.id"], ondelete="CASCADE", name="call_stats_operator_id_fkey"),
        PrimaryKeyConstraint("id", name="call_stats_pkey"),
        UniqueConstraint("operator_id", "call_date", name="call_stats_operator_id_call_date_key"),
        Index("idx_call_stats_filters", "operator_id", "call_date"),
        Index("idx_call_stats_keyset", "call_date", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_date: Mapped[datetime.date] = mapped_column(Date)
    operator_id: Mapped[Optional[int]] = mapped_column(Integer)
    total_calls: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("0"))
    successful_calls: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("0"))
    incoming_calls: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("0"))
    outgoing_calls: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("0"))
    total_duration: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("0"))
    missed_calls: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("0"))
    average_duration: Mapped[Optional[float]] = mapped_column(DOUBLE_PRECISION, server_default=text("0"))

    operator: Mapped[Optional["Operators"]] = relationship("Operators", back_populates="call_stats", lazy="selectin")


# -----------------------------
# Calls (нормализованные звонки)
# -----------------------------
class Calls(Base):
    __tablename__ = "calls"
    __table_args__ = (
        ForeignKeyConstraint(["operator_id"], ["operators.id"], ondelete="CASCADE", name="fk_operator"),
        PrimaryKeyConstraint("id", name="calls_pkey"),
        UniqueConstraint("bitrix_call_id", name="calls_bitrix_call_id_key"),
        # Оставляю как у тебя: уникальность номера + времени старта (если нужна — ок)
        UniqueConstraint("phone_number", "call_start_date", name="calls_phone_number_call_start_date_key"),
        Index("idx_calls_anal_pending", "analysis_status"),
        Index("idx_calls_trans_pending", "transcription_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bitrix_call_id: Mapped[str] = mapped_column(String(120))
    phone_number: Mapped[str] = mapped_column(String(20))
    # timestamptz
    call_start_date: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    call_duration: Mapped[int] = mapped_column(Integer)
    record_url: Mapped[Optional[str]] = mapped_column(Text)
    file_key: Mapped[Optional[str]] = mapped_column(Text)
    operator_id: Mapped[Optional[int]] = mapped_column(Integer)
    crm_entity_type: Mapped[Optional[str]] = mapped_column(String(30))
    crm_entity_id: Mapped[Optional[str]] = mapped_column(String(30))
    transcription: Mapped[Optional[dict]] = mapped_column(JSONB)
    transcription_status: Mapped[Optional[str]] = mapped_column(String(20), server_default=text("'pending'::character varying"))
    analysis_status: Mapped[Optional[str]] = mapped_column(String(20), server_default=text("'pending'::character varying"))
    transcription_retries: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("0"))
    analysis_retries: Mapped[Optional[int]] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    deleted_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True))
    analysis: Mapped[Optional[dict]] = mapped_column(JSONB)

    operator: Mapped[Optional["Operators"]] = relationship("Operators", back_populates="calls", lazy="selectin")


# -----------------------------
# Departments
# -----------------------------
class Departments(Base):
    __tablename__ = "departments"
    __table_args__ = (
        ForeignKeyConstraint(["uf_head"], ["operators.id"], ondelete="SET NULL", name="departments_uf_head_fkey"),
        PrimaryKeyConstraint("id", name="departments_pkey"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    uf_head: Mapped[Optional[int]] = mapped_column(Integer)

    # many-to-many обратная связь
    operators: Mapped[List["Operators"]] = relationship(
        "Operators",
        secondary="operator_departments",
        back_populates="departments",
        lazy="selectin",
    )

    # руководитель отдела
    head: Mapped[Optional["Operators"]] = relationship(
        "Operators",
        foreign_keys=lambda: [Departments.uf_head],
        back_populates="headed_departments",
        lazy="selectin",
    )

    # планы
    call_plans: Mapped[List["CallPlans"]] = relationship("CallPlans", back_populates="department", lazy="selectin")


# -----------------------------
# Call plans
# -----------------------------
class CallPlans(Base):
    __tablename__ = "call_plans"
    __table_args__ = (
        CheckConstraint(
            "plan_type::text = ANY (ARRAY['day'::character varying, 'month'::character varying]::text[])",
            name="call_plans_plan_type_check",
        ),
        ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="CASCADE", name="call_plans_department_id_fkey"),
        PrimaryKeyConstraint("id", name="call_plans_pkey"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="Уникальный идентификатор записи плана")
    plan_type: Mapped[str] = mapped_column(String(10), comment="Тип плана: 'day' или 'month'")
    plan_date: Mapped[datetime.date] = mapped_column(Date, comment="Дата плана")
    plan_value: Mapped[int] = mapped_column(Integer, comment="Целевое количество звонков")
    department_id: Mapped[Optional[int]] = mapped_column(Integer, comment="FK на departments.id")

    department: Mapped[Optional["Departments"]] = relationship("Departments", back_populates="call_plans", lazy="selectin")


# -----------------------------
# M2M junction
# -----------------------------
t_operator_departments = Table(
    "operator_departments",
    Base.metadata,
    Column("operator_id", Integer, primary_key=True, nullable=False),
    Column("department_id", Integer, primary_key=True, nullable=False),
    ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="CASCADE", name="operator_departments_department_id_fkey"),
    ForeignKeyConstraint(["operator_id"], ["operators.id"], ondelete="CASCADE", name="operator_departments_operator_id_fkey"),
    PrimaryKeyConstraint("operator_id", "department_id", name="operator_departments_pkey"),
)
