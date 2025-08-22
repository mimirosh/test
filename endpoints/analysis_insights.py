# endpoints/analysis_insights.py
"""
Insights по анализам звонков (calls.analysis).

Эндпоинт собирает из JSON-поля calls.analysis -> summary.strengths / summary.areas_for_improvement
фразы по выбранному периоду и субъекту (отдел или оператор), агрегирует частоты и
просит Gemini вернуть:
  - strengths_top   — топ-10 сильных сторон
  - improvements_top — топ-10 зон роста
  - summary_insights — общий вывод и рекомендацию для менеджера (единая строка)

Фильтры:
- date_from, date_to (YYYY-MM-DD) — по дате звонка, границы включительно;
- operator_id ИЛИ department_id — укажи ровно один (если оба None, считается по всем);
- include_deleted=false — по умолчанию исключаем мягко удалённые.

Заметки:
- Для среза по отделу выполняется join с operator_departments.
- Чтобы уменьшить токены, в LLM отправляем уникальные фразы с их частотами (а не сырой список).
"""

from __future__ import annotations
import os
import json
import datetime as dt
from collections import Counter
from typing import Optional, List, Dict, Any

import google.generativeai as genai
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from database.models import Calls, t_operator_departments
from endpoints.auth import get_current_user

router = APIRouter(prefix="/llm", tags=["LLM"])

# --- Gemini setup ---
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")


# ===== схемы ответа =====
class RankedItem(BaseModel):
    text: str
    count: int = Field(0, description="Сколько раз встретилось во входных данных (наша агрегация)")
    reason: Optional[str] = Field(None, description="Короткое объяснение от модели, почему это в топе")


class InsightsOut(BaseModel):
    meta: Dict[str, Any]
    strengths_top: List[RankedItem]
    improvements_top: List[RankedItem]
    summary_insights: str


# ===== хелперы =====
def _norm_phrase(s: str) -> str:
    return (s or "").strip()

def _extract_summary_items(analysis: dict) -> tuple[list[str], list[str]]:
    """Достаём из analysis.summary списки strengths и areas_for_improvement."""
    if not isinstance(analysis, dict):
        return [], []
    summary = analysis.get("summary") or {}
    if not isinstance(summary, dict):
        return [], []
    strengths = summary.get("strengths") or []
    areas = summary.get("areas_for_improvement") or []
    strengths = [str(x) for x in strengths if isinstance(x, (str,))]
    areas = [str(x) for x in areas if isinstance(x, (str,))]
    return strengths, areas


async def _fetch_analyses(
    db: AsyncSession,
    *,
    date_from: dt.date,
    date_to: dt.date,
    operator_id: int | None,
    department_id: int | None,
    include_deleted: bool,
    max_rows: int,
) -> list[dict]:
    """
    Возвращает список JSON (calls.analysis) по фильтрам.
    По дате фильтруем по ::date (PostgreSQL), чтобы границы были включительно.
    """
    date_cond = and_(
        func.date(Calls.call_start_date) >= date_from,
        func.date(Calls.call_start_date) <= date_to,
    )
    base_filters = [Calls.analysis.is_not(None), date_cond]
    if not include_deleted:
        base_filters.append(Calls.deleted_at.is_(None))

    if operator_id is not None and department_id is not None:
        raise HTTPException(status_code=400, detail="Укажи ровно один из: operator_id или department_id")

    if operator_id is not None:
        stmt = (
            select(Calls.analysis)
            .where(and_(*base_filters, Calls.operator_id == operator_id))
            .order_by(Calls.call_start_date.desc())
            .limit(max_rows)
        )
    elif department_id is not None:
        stmt = (
            select(Calls.analysis)
            .select_from(
                Calls.__table__.join(
                    t_operator_departments,
                    Calls.operator_id == t_operator_departments.c.operator_id,
                )
            )
            .where(and_(*base_filters, t_operator_departments.c.department_id == department_id))
            .order_by(Calls.call_start_date.desc())
            .limit(max_rows)
        )
    else:
        stmt = (
            select(Calls.analysis)
            .where(and_(*base_filters))
            .order_by(Calls.call_start_date.desc())
            .limit(max_rows)
        )

    rows = (await db.execute(stmt)).scalars().all()
    out: list[dict] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r)
        elif isinstance(r, str):
            try:
                out.append(json.loads(r))
            except Exception:
                continue
    return out


def _prepare_payload_for_llm(
    strengths_counter: Counter,
    areas_counter: Counter,
    meta: dict,
    max_items_each: int = 1000,
) -> dict:
    """Отправляем в LLM уникальные фразы с частотами (экономим токены)."""
    strengths = [{"text": t, "count": c} for t, c in strengths_counter.most_common(max_items_each)]
    areas = [{"text": t, "count": c} for t, c in areas_counter.most_common(max_items_each)]
    return {
        "meta": meta,
        "strengths": strengths,
        "areas_for_improvement": areas,
    }


def _ask_gemini(payload: dict) -> dict:
    """
    Просим модель вернуть строго JSON:
      {
        "strengths_top": [...],
        "improvements_top": [...],
        "summary_insights": "общий вывод и рекомендация (1–2 абзаца)"
      }
    """
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0.2,
        },
        system_instruction=(
            "Ты аналитик по звонкам. Тебе передают две группы фраз с частотами: "
            "'strengths' - сильные стороны менеджера и 'areas_for_improvement' - зоны роста. "
            "Семантически сгруппируй похожие пункты, оцени важность по частоте и смыслу и верни ТОП-10 "
            "(или меньше) по каждой группе. Затем сформулируй краткий общий вывод и практическую "
            "рекомендацию для менеджера (одной строкой или 1–2 короткими предложениями). "
            "Ответ верни строго как JSON со схемой:\n"
            "{"
            "  'strengths_top': [{'text': str, 'count': int, 'reason': str?}, ...],"
            "  'improvements_top': [{'text': str, 'count': int, 'reason': str?}, ...],"
            "  'summary_insights': str"
            "}"
        ),
    )

    prompt = (
        "Входные данные ниже. Сформируй ответ по схеме.\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    resp = model.generate_content(prompt)

    txt = getattr(resp, "text", None)
    if not txt:
        try:
            for cand in resp.candidates or []:
                parts = getattr(cand.content, "parts", []) or []
                for p in parts:
                    if getattr(p, "text", None):
                        txt = p.text
                        break
                if txt:
                    break
        except Exception:
            pass
    if not txt:
        raise HTTPException(status_code=502, detail="LLM не вернул текстовый ответ")

    try:
        data = json.loads(txt)
    except Exception:
        start = txt.find("{"); end = txt.rfind("}")
        if start != -1 and end != -1 and end > start:
            data = json.loads(txt[start:end+1])
        else:
            raise HTTPException(status_code=502, detail="Не удалось распарсить ответ LLM как JSON")

    # нормализация
    def _norm_list(key: str) -> list[dict]:
        arr = data.get(key) or []
        out = []
        for it in arr:
            if not isinstance(it, dict):
                continue
            text = _norm_phrase(it.get("text", ""))
            if not text:
                continue
            # безопасный парс count
            try:
                count = int(it.get("count", 0))
            except Exception:
                count = 0
            reason = it.get("reason")
            out.append({"text": text, "count": count, "reason": reason})
        return out[:10]

    strengths_top = _norm_list("strengths_top")
    improvements_top = _norm_list("improvements_top")
    summary_insights = data.get("summary_insights")
    if not isinstance(summary_insights, str) or not summary_insights.strip():
        # fallback: простая авто-выжимка, если LLM не выдал поле
        top_s = "; ".join([x["text"] for x in strengths_top[:3]]) or "данных о сильных сторонах мало"
        top_i = "; ".join([x["text"] for x in improvements_top[:3]]) or "данных о зонах роста мало"
        summary_insights = (
            f"Ключевые сильные стороны: {top_s}. "
            f"Главные зоны роста: {top_i}. Рекомендация: сфокусироваться на первых приоритетах зон роста и закреплять сильные стороны в скриптах."
        )

    return {
        "strengths_top": strengths_top,
        "improvements_top": improvements_top,
        "summary_insights": summary_insights.strip(),
    }


# ===== эндпоинт =====
@router.get(
    "/summary-insights",
    response_model=InsightsOut,
    summary="LLM-инсайты по strengths / areas_for_improvement из calls.analysis",
    description=(
        "Собирает пункты `summary.strengths` и `summary.areas_for_improvement` из `calls.analysis` "
        "по фильтрам и возвращает:\n"
        "- strengths_top (ТОП-10 сильных сторон),\n"
        "- improvements_top (ТОП-10 зон роста),\n"
        "- summary_insights (общий вывод и рекомендация для менеджера).\n\n"
        "Границы дат включительно. Для отдела используется связь operator_departments."
    ),
)
async def summary_insights(
    date_from: dt.date = Query(..., description="Начало периода (включительно), YYYY-MM-DD"),
    date_to: dt.date = Query(..., description="Конец периода (включительно), YYYY-MM-DD"),
    operator_id: Optional[int] = Query(None, description="ID оператора (ровно один из operator_id/department_id)"),
    department_id: Optional[int] = Query(None, description="ID отдела (ровно один из operator_id/department_id)"),
    include_deleted: bool = Query(False, description="Включать ли записи с deleted_at != NULL"),
    max_calls: int = Query(5000, ge=1, le=20000, description="Максимум обработанных звонков"),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    if date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must be <= date_to")

    analyses = await _fetch_analyses(
        db,
        date_from=date_from,
        date_to=date_to,
        operator_id=operator_id,
        department_id=department_id,
        include_deleted=include_deleted,
        max_rows=max_calls,
    )
    if not analyses:
        return InsightsOut(
            meta={
                "calls_count": 0,
                "date_from": str(date_from),
                "date_to": str(date_to),
                "operator_id": operator_id,
                "department_id": department_id,
            },
            strengths_top=[],
            improvements_top=[],
            summary_insights="Данных за выбранный период не найдено.",
        )

    strengths_all: list[str] = []
    areas_all: list[str] = []
    for a in analyses:
        s_list, a_list = _extract_summary_items(a)
        strengths_all.extend([_norm_phrase(x) for x in s_list if _norm_phrase(x)])
        areas_all.extend([_norm_phrase(x) for x in a_list if _norm_phrase(x)])

    strengths_counter = Counter(strengths_all)
    areas_counter = Counter(areas_all)

    payload = _prepare_payload_for_llm(
        strengths_counter,
        areas_counter,
        meta={
            "calls_count": len(analyses),
            "unique_strengths": len(strengths_counter),
            "unique_areas": len(areas_counter),
            "date_from": str(date_from),
            "date_to": str(date_to),
            "operator_id": operator_id,
            "department_id": department_id,
        },
    )

    ranked = _ask_gemini(payload)

    return InsightsOut(
        meta=payload["meta"],
        strengths_top=[RankedItem(**it) for it in ranked["strengths_top"]],
        improvements_top=[RankedItem(**it) for it in ranked["improvements_top"]],
        summary_insights=ranked["summary_insights"],
    )
