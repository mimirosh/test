"""Aigor API Service: FastAPI-приложение с JWT-авторизацией и модулями calls/operators/departments."""

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

# Auth router и зависимость
from endpoints.auth import router as auth_router, get_current_user

# Бизнес-роутеры
from endpoints.operators import router as operators_router
from endpoints.calls import router as calls_router
from endpoints.departments import router as departments_router

APP_TITLE = "Aigor API Service"
APP_VERSION = "1.0.0"

app = FastAPI(
    title=APP_TITLE,
    version=APP_VERSION,
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "Auth", "description": "JWT: получение токена и профиль"},
        {"name": "Operators", "description": "Информация о менеджерах"},
        {"name": "Calls", "description": "Звонки: транскрипция, аналитика и т.д."},
        {"name": "Departments", "description": "Информация об отделах"},
        {"name": "Health", "description": "Проверка состояния сервиса"},
    ],
)

# CORS — настрой при необходимости
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # в проде сузить
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Публичный: авторизация (получение токена и /auth/me)
app.include_router(auth_router)  # НЕ передаём tags — они уже заданы в самом роутере (единственный тег "Auth")

# Защищённые роутеры (весь роутер под токеном)
app.include_router(
    operators_router,
    tags=["Operators"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    calls_router,
    tags=["Calls"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    departments_router,
    tags=["Departments"],
    dependencies=[Depends(get_current_user)],
)


@app.get("/", tags=["Health"], summary="Health-check")
async def health() -> dict:
    """Проверка работоспособности сервиса.

    Returns:
        dict: {"status": "ok", "service": <name>, "version": <semver>}
    """
    return {"status": "ok", "service": APP_TITLE, "version": APP_VERSION}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8006, reload=True)
