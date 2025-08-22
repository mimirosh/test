# endpoints/llm_agent.py
from __future__ import annotations
import os, json, datetime as dt
from typing import Optional, Dict, Any

import httpx
import google.generativeai as genai
from httpx import ASGITransport
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from endpoints.auth import create_access_token, get_current_user

router = APIRouter(prefix="/llm", tags=["LLM"])

# --- Gemini setup ---
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")

# ---- tools exposed to Gemini ----
# 1) resolve_subject — по ФИО/названию возвращает {operator_id|department_id}
# 2) fetch_* — прокси к твоим эндпоинтам (GET)
function_declarations = [
    {
        "name": "resolve_subject",
        "description": "Разрешить субъекта по свободному тексту (Фамилия Имя, e-mail, либо название отдела) к ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "operator_full_name": {"type": "string", "description":"Напр.: 'Иванов Иван' или 'Иван Иванов'"},
                "operator_email": {"type": "string"},
                "department_name": {"type": "string"}
            },
            "required": []
        }
    },

    # Operators
    {
        "name": "fetch_operators",
        "description": "Прокси GET /api/v1/operators/ с пагинацией и поиском по подстроке.",
        "parameters": {
            "type":"object",
            "properties":{
                "skip":{"type":"integer"},
                "limit":{"type":"integer"},
                "q":{"type":"string","description":"поиск по имени/фамилии/e-mail если ручка поддерживает; иначе фильтрация в агенте"}
            },
            "required":[]
        }
    },
    {
        "name": "fetch_operator_by_id",
        "description": "Прокси GET /api/v1/operators/{operator_id}",
        "parameters": {"type":"object","properties":{"operator_id":{"type":"integer"}},"required":["operator_id"]}
    },

    # Calls
    {
        "name": "fetch_calls",
        "description": "Прокси GET /api/v1/calls/ с фильтрами/сортировкой.",
        "parameters": {
            "type":"object",
            "properties":{
                "skip":{"type":"integer"},
                "limit":{"type":"integer"},
                "operator_id":{"type":"integer"},
                "transcription_status":{"type":"string"},
                "analysis_status":{"type":"string"},
                "date_from":{"type":"string","format":"date"},
                "date_to":{"type":"string","format":"date"},
                "phone_like":{"type":"string"},
                "include_data":{"type":"boolean"},
                "deleted":{"type":"boolean"},
                "sort_by":{"type":"string","enum":["call_start_date","call_duration","indicators_done","indicators_total","penalty_sum","stages_done","stages_total"]},
                "sort_dir":{"type":"string","enum":["asc","desc"]}
            },
            "required":[]
        }
    },
    {
        "name": "fetch_call_by_id",
        "description": "Прокси GET /api/v1/calls/{call_id}",
        "parameters": {"type":"object","properties":{"call_id":{"type":"integer"}},"required":["call_id"]}
    },

    # Call-logs
    {
        "name": "fetch_call_logs",
        "description": "Прокси GET /api/v1/call-logs/",
        "parameters": {
            "type":"object",
            "properties":{
                "skip":{"type":"integer"},
                "limit":{"type":"integer"},
                "operator_id":{"type":"integer"},
                "date_from":{"type":"string","format":"date"},
                "date_to":{"type":"string","format":"date"},
                "call_type":{"type":"integer"}
            },
            "required":[]
        }
    },
    {
        "name": "fetch_call_log_by_id",
        "description": "Прокси GET /api/v1/call-logs/{log_id}",
        "parameters": {"type":"object","properties":{"log_id":{"type":"integer"}},"required":["log_id"]}
    },

    # Call-stats
    {
        "name": "fetch_call_stats",
        "description": "Прокси GET /api/v1/call-stats/",
        "parameters": {
            "type":"object",
            "properties":{
                "skip":{"type":"integer"},
                "limit":{"type":"integer"},
                "operator_id":{"type":"integer"},
                "date_from":{"type":"string","format":"date"},
                "date_to":{"type":"string","format":"date"}
            },
            "required":[]
        }
    },
    {
        "name": "compare_call_stats",
        "description": "Прокси GET /api/v1/call-stats/compare",
        "parameters": {
            "type":"object",
            "properties":{
                "metric":{"type":"string","enum":["total_calls","successful_calls","incoming_calls","outgoing_calls","total_duration","missed_calls","average_duration"]},
                "mode":{"type":"string","enum":["dod","wow","mom","yoy"]},
                "at":{"type":"string","format":"date"},
                "operator_id":{"type":"integer"},
                "department_id":{"type":"integer"}
            },
            "required":["metric","mode","at"]
        }
    },
    {
        "name": "fetch_call_stat_by_id",
        "description": "Прокси GET /api/v1/call-stats/{stat_id}",
        "parameters": {"type":"object","properties":{"stat_id":{"type":"integer"}},"required":["stat_id"]}
    },

    # Call-metrics (из calls.*)
    {
        "name": "compare_call_metrics",
        "description": "Прокси GET /api/v1/call-metrics/compare",
        "parameters": {
            "type":"object",
            "properties":{
                "metric":{"type":"string","enum":["indicators_done","penalty_sum","stages_done","stages_total","indicators_total"]},
                "mode":{"type":"string","enum":["dod","wow","mom","yoy"]},
                "at":{"type":"string","format":"date"},
                "operator_id":{"type":"integer"},
                "department_id":{"type":"integer"}
            },
            "required":["metric","mode","at"]
        }
    },
    {
        "name": "series_call_metrics",
        "description": "Прокси GET /api/v1/call-metrics/series",
        "parameters": {
            "type":"object",
            "properties":{
                "metric":{"type":"string","enum":["indicators_done","penalty_sum","stages_done","stages_total","indicators_total"]},
                "grain":{"type":"string","enum":["hour","day"]},
                "date_from":{"type":"string","format":"date-time"},
                "date_to":{"type":"string","format":"date-time"},
                "operator_id":{"type":"integer"},
                "department_id":{"type":"integer"}
            },
            "required":["metric","grain","date_from","date_to"]
        }
    },

    # Departments
    {
        "name": "fetch_departments",
        "description": "Прокси GET /api/v1/departments/",
        "parameters": {
            "type":"object",
            "properties":{
                "skip":{"type":"integer"},
                "limit":{"type":"integer"}
            },
            "required":[]
        }
    },

    # Health
    {
        "name": "health_check",
        "description": "Прокси GET /api/v1/health-check",
        "parameters": {"type":"object","properties":{},"required":[]}
    },

    # Plan targets evaluate
    {
        "name": "evaluate_daily_target",
        "description": "Прокси GET /plan-targets/evaluate/daily (или /api/v1/plan-targets/effective/daily — fallback).",
        "parameters": {
            "type":"object",
            "properties":{
                "operator_id":{"type":"integer"},
                "department_id":{"type":"integer"},
                "day":{"type":"string","format":"date"},
                "metric":{"type":"string","enum":["calls_total","calls_success","clients_total","clients_success","avg_duration","total_talk_time"]}
            },
            "required":["metric","day"]
        }
    },
    {
        "name": "evaluate_monthly_target",
        "description": "Прокси GET /plan-targets/evaluate/monthly (или /api/v1/plan-targets/by-subject — если у тебя так).",
        "parameters": {
            "type":"object",
            "properties":{
                "month":{"type":"string","format":"date"},
                "operator_id":{"type":"integer"},
                "department_id":{"type":"integer"},
                "metric":{"type":"string","enum":["calls_total","calls_success","clients_total","clients_success","avg_duration","total_talk_time"]}
            },
            "required":["month"]
        }
    },
]

# --- Gemini tool schema sanitizer: оставляем только поддерживаемые ключи ---
SUPPORTED_SCHEMA_KEYS = {"type", "properties", "required", "description", "enum", "items"}

def _items(payload):
    """Return list of items from either [{...}, ...] or {"items":[...], ...}."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return payload["items"]
    return []

def _extract_text(resp) -> Optional[str]:
    # Пытаемся через удобный аксессор
    try:
        if getattr(resp, "text", None):
            return resp.text
    except Exception:
        pass

    # Пытаемся собрать текст из parts
    try:
        for cand in getattr(resp, "candidates", []) or []:
            parts = getattr(cand.content, "parts", []) or []
            pieces = []
            for p in parts:
                t = getattr(p, "text", None)
                if t:
                    pieces.append(t)
            if pieces:
                return "\n".join(pieces)
    except Exception:
        pass
    return None


def sanitize_schema(x):
    # Рекурсивно чистим dict от неподдерживаемых ключей
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if k not in SUPPORTED_SCHEMA_KEYS:
                # игнорируем minimum/maximum/default/format/anything-else
                continue
            if k == "properties" and isinstance(v, dict):
                out["properties"] = {pk: sanitize_schema(pv) for pk, pv in v.items()}
            elif k == "items":
                out["items"] = sanitize_schema(v)
            else:
                out[k] = v
        # normalize type: список типов → берём первый
        t = out.get("type")
        if isinstance(t, list) and t:
            out["type"] = t[0]
        return out
    elif isinstance(x, list):
        return [sanitize_schema(i) for i in x]
    else:
        return x

def sanitize_function_declarations(fds: list[dict]) -> list[dict]:
    cleaned = []
    for fd in fds:
        fd2 = dict(fd)
        if "parameters" in fd2 and isinstance(fd2["parameters"], dict):
            fd2["parameters"] = sanitize_schema(fd2["parameters"])
        cleaned.append(fd2)
    return cleaned


model = genai.GenerativeModel(
    model_name=GEMINI_MODEL,
    tools=[{"function_declarations": sanitize_function_declarations(function_declarations)}],
    system_instruction=(
        "Ты — аналитический помощник Aigor. Всегда используй функции (tools) для данных. "
        "Если не указан субъект — сначала вызови resolve_subject. Не выдумывай числа."
    ),
)

# ---- payload ----
class AskIn(BaseModel):
    question: str = Field(..., description="Естественный вопрос руководителя")
    operator_full_name: Optional[str] = None
    operator_email: Optional[str] = None
    department_name: Optional[str] = None


# ---- internal client (ASGI, no network) ----
def _internal_client(request: Request) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=request.app), base_url="http://internal", timeout=30.0)

# ---- small helpers ----
def _svc_token(minutes: int = 2) -> str:
    return create_access_token({"sub":"llmservice","user_id":0,"email":"llm@internal"}, expires_minutes=minutes)

async def _get_json(client: httpx.AsyncClient, path: str, headers: dict, params: dict | None = None) -> Any:
    r = await client.get(path, params=params, headers=headers)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()

# ---- name → id resolution (внутри агента, поверх существующих ручек) ----
async def _resolve_subject(request: Request, args: Dict[str, Any], headers: dict) -> Dict[str, Any]:
    op_id = None
    dep_id = None
    async with _internal_client(request) as c:
        # departments by name (supports both list and {"items": [...]})
        if args.get("department_name"):
            deps_raw = await _get_json(c, "/api/v1/departments/", headers, params={"limit": 1000})
            deps = _items(deps_raw)
            name_q = args["department_name"].strip().lower()
            for d in deps:
                name = (d.get("name") or "").lower()
                if name_q == name or name_q in name:
                    dep_id = d["id"]
                    break

        # operators by email or FIO (supports both list and {"items": [...]})
        if args.get("operator_email") or args.get("operator_full_name"):
            ops_raw = await _get_json(c, "/api/v1/operators/", headers, params={"limit": 1000})
            ops = _items(ops_raw)

            email_q = (args.get("operator_email") or "").strip().lower()
            fio_q = (args.get("operator_full_name") or "").strip().lower()

            # try email exact match first
            if email_q:
                for o in ops:
                    if (o.get("email") or "").strip().lower() == email_q:
                        op_id = o["id"]
                        break

            # then FIO — supports "Иванов Иван" / "Иван Иванов" / partial contains
            if op_id is None and fio_q:
                for o in ops:
                    fn = (o.get("name") or "").strip().lower()
                    ln = (o.get("last_name") or "").strip().lower()
                    variants = [f"{ln} {fn}".strip(), f"{fn} {ln}".strip(), ln, fn]
                    if any(fio_q == v or (fio_q and v and fio_q in v) for v in variants):
                        op_id = o["id"]
                        break

    return {"operator_id": op_id, "department_id": dep_id}


# ---- tool dispatcher ----
async def _tool_call(request: Request, name: str, args: Dict[str, Any], headers: dict) -> Dict[str, Any]:
    async with _internal_client(request) as c:
        if name == "resolve_subject":
            return await _resolve_subject(request, args, headers)

        # map simple GET proxies
        if name == "fetch_operators":
            return await _get_json(c, "/api/v1/operators/", headers, params=args)
        if name == "fetch_operator_by_id":
            return await _get_json(c, f"/api/v1/operators/{args['operator_id']}", headers)

        if name == "fetch_calls":
            return await _get_json(c, "/api/v1/calls/", headers, params=args)
        if name == "fetch_call_by_id":
            return await _get_json(c, f"/api/v1/calls/{args['call_id']}", headers)

        if name == "fetch_call_logs":
            return await _get_json(c, "/api/v1/call-logs/", headers, params=args)
        if name == "fetch_call_log_by_id":
            return await _get_json(c, f"/api/v1/call-logs/{args['log_id']}", headers)

        if name == "fetch_call_stats":
            return await _get_json(c, "/api/v1/call-stats/", headers, params=args)
        if name == "fetch_call_stat_by_id":
            return await _get_json(c, f"/api/v1/call-stats/{args['stat_id']}", headers)
        if name == "compare_call_stats":
            return await _get_json(c, "/api/v1/call-stats/compare", headers, params=args)

        if name == "compare_call_metrics":
            return await _get_json(c, "/api/v1/call-metrics/compare", headers, params=args)
        if name == "series_call_metrics":
            return await _get_json(c, "/api/v1/call-metrics/series", headers, params=args)

        if name == "fetch_departments":
            return await _get_json(c, "/api/v1/departments/", headers, params=args)

        if name == "health_check":
            return await _get_json(c, "/api/v1/health-check", headers)

        if name == "evaluate_daily_target":
            # сначала пробуем путь без api/v1 как у тебя в примере, если 404 — fallback
            try:
                return await _get_json(c, "/plan-targets/evaluate/daily", headers, params=args)
            except HTTPException as e:
                if e.status_code == 404:
                    return await _get_json(c, "/api/v1/plan-targets/effective/daily", headers, params=args)
                raise

        if name == "evaluate_monthly_target":
            try:
                return await _get_json(c, "/plan-targets/evaluate/monthly", headers, params=args)
            except HTTPException as e:
                if e.status_code == 404:
                    # возможно у тебя list_by_subject под /api/v1/plan-targets/by-subject
                    return await _get_json(c, "/api/v1/plan-targets/by-subject", headers, params=args)
                raise

        return {"error": f"Unknown tool {name}"}

# ---- main endpoint ----
class AskIn(BaseModel):
    question: str = Field(..., description="Естественный вопрос")
    operator_full_name: Optional[str] = None
    operator_email: Optional[str] = None
    department_name: Optional[str] = None

@router.post("/ask")
async def ask_llm(
    body: AskIn = Body(...),
    request: Request = None,
    _=Depends(get_current_user),  # при желании можно убрать защиту
):
    """
    LLM-агент для руководителя:
    - Gemini анализирует запрос и вызывает tools,
    - мы проксируем tools во внутренние эндпоинты (ASGITransport),
    - имя/почта/название отдела можно передать в теле запроса — модель сможет
      позвать resolve_subject и получить нужные ID.
    """
    svc_headers = {"Authorization": f"Bearer {_svc_token(2)}"}

    # model = genai.GenerativeModel(
    #     model_name=GEMINI_MODEL,
    #     tools=[{"function_declarations": function_declarations}],
    #     system_instruction=(
    #         "Ты — аналитический помощник Aigor. Для данных используй только функции (tools). "
    #         "Если неизвестен ID — сначала вызови resolve_subject. Не выдумывай данные."
    #     ),
    # )

    chat = model.start_chat()

    # Подсказываем контекст в первом сообщении (чтобы модель могла сразу дернуть resolve_subject)
    hints = []
    if body.operator_full_name: hints.append(f"Operator full name: {body.operator_full_name}")
    if body.operator_email:     hints.append(f"Operator email: {body.operator_email}")
    if body.department_name:    hints.append(f"Department name: {body.department_name}")

    resp = await chat.send_message_async("\n".join(hints + [body.question]))

    # до 4 итераций tool-calling
    for _ in range(4):
        parts = resp.candidates[0].content.parts if resp.candidates else []
        calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
        if not calls:
            break

        tool_outputs = []
        for call in calls:
            name = call.name
            args = json.loads(call.args) if isinstance(call.args, str) else dict(call.args)

            # если имя/почта/отдел не переданы в args — подставим из тела (модели удобно)
            if name == "resolve_subject":
                if "operator_full_name" not in args and body.operator_full_name:
                    args["operator_full_name"] = body.operator_full_name
                if "operator_email" not in args and body.operator_email:
                    args["operator_email"] = body.operator_email
                if "department_name" not in args and body.department_name:
                    args["department_name"] = body.department_name

            data = await _tool_call(request, name, args, svc_headers)

            tool_outputs.append({
                "function_response": {
                    "name": name,
                    "response": data
                }
            })

        resp = await chat.send_message_async(tool_outputs)

    final_text = _extract_text(resp)
    if not final_text:
				# Последний шаг: попросим модель оформить краткий ответ по данным из функций
        resp = await chat.send_message_async(
						"Сформулируй краткий ответ по данным из вызванных функций. "
						"Отвечай по-русски, без домыслов."
				)
        final_text = _extract_text(resp)

    return {"answer": final_text or "Не удалось сформировать ответ."}

