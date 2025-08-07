# AIGOR API Service

## Описание
Это FastAPI-сервис для работы с базой данных PostgreSQL. Сервис предоставляет эндпоинты для получения данных из таблиц, таких как операторы (Operators), звонки (Calls) и отделы (Departments). Проект использует SQLAlchemy для асинхронного взаимодействия с БД, Pydantic для валидации данных и Uvicorn как сервер.

Ключевые фичи:
- Получение списка отделов по корневому маршруту (`/`).
- Эндпоинты для получения операторов (`/operators`) с пагинацией и фильтрами.
- Эндпоинты для получения звонков (`/calls`) с пагинацией и фильтрами.
- Конфигурация через .env для безопасности (строка подключения к БД).
- Автоматическая документация через Swagger UI (`/docs`).

## Требования
- Python 3.12+
- PostgreSQL (существующая БД с таблицами, описанными в моделях)
- Установленные зависимости (см. ниже)

## Установка
1. Клонируйте репозиторий:
   ```
   git clone https://github.com/mimirosh/test
   cd aigor/api_service
   ```

2. Создайте виртуальное окружение:
   ```
   python -m venv venv
   source venv/bin/activate  # Для macOS/Linux
   # Или для Windows: venv\Scripts\activate
   ```

3. Установите зависимости из `requirements.txt`:
   ```
   pip install -r requirements.txt
   ```
   (Пример содержимого requirements.txt: fastapi, uvicorn, sqlalchemy[asyncio], asyncpg, pydantic, python-dotenv)

4. Создайте файл `.env` в корне проекта с параметрами подключения к БД:
   ```
   DB_HOST=127.0.0.1
   DB_PORT=5432
   DB_NAME=your_db_name
   DB_USER=your_user
   DB_PASSWORD=your_password  # Экранируйте спецсимволы, если нужно (например, @ → %40)
   ```

## Запуск
Запустите сервер:
```
uvicorn main:app --reload
```
- Сервер доступен по `http://127.0.0.1:8000`.
- Документация: `http://127.0.0.1:8000/docs` (Swagger UI).
- Redoc: `http://127.0.0.1:8000/redoc`.

## Структура проекта
```
aigor/api_service/
├── main.py                # Основной файл приложения FastAPI
├── endpoints/             # Эндпоинты (роутеры)
│   ├── operators.py       # Получение операторов
│   └── calls.py           # Получение звонков
├── database/              # Модули для работы с БД
│   ├── __init__.py
│   ├── base.py            # Базовый класс для моделей
│   ├── models.py          # SQLAlchemy модели таблиц
│   └── session.py         # Настройка сессии и подключения к БД
├── .env                   # Конфигурация (не коммитьте в git!)
├── requirements.txt       # Зависимости
└── README.md              # Этот файл
```

## Эндпоинты
- **GET /**: Возвращает список ID и имён отделов (Departments).
- **GET /operators/**: Получение списка операторов с пагинацией (skip, limit) и фильтром по active.
  - Параметры: skip (int, default=0), limit (int, default=10), active (bool, optional).
- **GET /operators/{operator_id}**: Получение одного оператора по ID.
- **GET /calls/**: Получение списка звонков с пагинацией и фильтрами (operator_id, transcription_status).
  - Параметры: skip (int, default=0), limit (int, default=10), operator_id (int, optional), transcription_status (str, optional).
- **GET /calls/{call_id}**: Получение одного звонка по ID.

## Разработка и отладка
- Для теста используйте Swagger (`/docs`).
- Логи SQL: В session.py `echo=True` в create_async_engine (для dev).
- Добавление эндпоинтов: Создайте новый файл в endpoints/, импортируйте в main.py и подключите через app.include_router.
- Миграции: Рекомендуется Alembic для изменений в БД (установите `pip install alembic` и настройте).

## Вклад и улучшения
- Добавьте авторизацию (JWT) для защиты эндпоинтов.
- Расширьте модели и эндпоинты для других таблиц (CallLogs, CallStats и т.д.).
- Для вопросов или PR: [your-email or issue tracker].

Лицензия: MIT (или укажите свою).