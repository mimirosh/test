from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware

from endpoints.auth import router as auth_router
from endpoints.operators import router as operators_router
from endpoints.calls import router as calls_router
from endpoints.call_logs import router as call_logs_router
from endpoints.call_stats import router as call_stats_router
from endpoints.departments import router as departments_router
from endpoints.plan_targets import router as plan_targets_router
from endpoints.call_metrics import router as call_metrics_router
from endpoints.llm_agent import router as llm_agent_router
from endpoints.analysis_insights import router as analysis_insights_router

#from sqlalchemy import create_engine
#from sqladmin import Admin

# from admin_views import (
#     OperatorsAdmin,
#     DepartmentsAdmin,
#     PlanTargetsAdmin,
#     CallsAdmin,
#     CallLogsAdmin,
#     CallStatsAdmin,
# )

#import os

APP_TITLE = "Aigor API Service"
APP_VERSION = "1.0.0"

app = FastAPI(
    title=APP_TITLE,
    version=APP_VERSION,
    # Делаем документацию тоже под /api/v1
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_tags=[
        {"name": "Auth", "description": "JWT: токен и профиль"},
        {"name": "Operators", "description": "Информация о менеджерах"},
        {"name": "Calls", "description": "Звонки: транскрипция, аналитика и т.д."},
        {"name": "CallLogs", "description": "Сырые логи звонков"},
        {"name": "CallStats", "description": "Агрегированная статистика звонков"},
        {"name": "CallMetrics", "description": "Метрики звонков"},
        {"name": "Departments", "description": "Информация об отделах"},
        {"name": "Health", "description": "Проверка состояния сервиса"},
        {"name": "PlanTargets", "description": "Плановые цели"},
        {"name": "LLMAgent", "description": "LLM-агент"},
        {"name": "AnalysisInsights", "description": "Инсайты"},
    ],
)

# sync_url = os.getenv("DATABASE_URL")  # replace with your DB URL, change asyncpg to psycopg2
# sync_engine = create_engine(sync_url)
# app.state.admin_engine = sync_engine

# admin = Admin(app, sync_engine)

# admin.add_view(OperatorsAdmin)
# admin.add_view(DepartmentsAdmin)
# admin.add_view(PlanTargetsAdmin)
# admin.add_view(CallsAdmin)
# admin.add_view(CallLogsAdmin)
# admin.add_view(CallStatsAdmin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # сузить в проде
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Один общий роутер с префиксом версии
api_v1 = APIRouter(prefix="/api/v1")

# Все твои модули уже имеют свои внутренние prefix ("/auth", "/operators", "/calls", "/departments")
api_v1.include_router(auth_router)
api_v1.include_router(operators_router)
api_v1.include_router(calls_router)
api_v1.include_router(call_logs_router)
api_v1.include_router(call_stats_router)
api_v1.include_router(call_metrics_router)
api_v1.include_router(departments_router)
app.include_router(plan_targets_router)
app.include_router(llm_agent_router)
app.include_router(analysis_insights_router)


# Health под версией
@api_v1.get("/", tags=["Health"], summary="Health-check")
async def health() -> dict:
    return {"status": "ok", "service": APP_TITLE, "version": APP_VERSION}

# Подключаем версионированный роутер к приложению
app.include_router(api_v1)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8006, reload=True)
