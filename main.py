from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.session import get_db
from database.models import Departments  # Импортируем модель Departments
from typing import List
from pydantic import BaseModel

# Импортируем роуты
from endpoints.operators import router as operators_router
from endpoints.calls import router as calls_router
from endpoints.departments import router as departments_router

app = FastAPI(title="Aigor API Service", version="1.0.0", openapi_url="/openapi.json", docs_url="/docs", redoc_url="/redoc", openapi_tags=[
	{
		"name": "Operators",
		"description": "Получение информации о менеджерах"
	},
	{
		"name": "Calls",
		"description": "Получение данных с информацией по звонкам (транскрипция, аналитика и др.)"
	},
  {
		"name": "Departments",
		"description": "Получение информации об отделах"
	}
])

# Подключаем роуты
app.include_router(operators_router, tags=["Operators"])
app.include_router(calls_router, tags=["Calls"])
app.include_router(departments_router, tags=["Departments"])

class DepartmentResponse(BaseModel):
    id: int
    name: str

@app.get("/", response_model=List[DepartmentResponse])
async def get_departments(db: AsyncSession = Depends(get_db)):
    # Запрос на id и name из таблицы Departments
    query = select(Departments.id, Departments.name)
    result = await db.execute(query)
    departments = result.fetchall()
    # Преобразуем в список словарей для ответа
    return [{"id": dep.id, "name": dep.name} for dep in departments]

# Добавляем запуск Uvicorn
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8006, reload=True)