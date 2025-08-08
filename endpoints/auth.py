"""Auth endpoints: JWT выдача токена и профиль текущего пользователя.

Режимы:
- AUTH_MODE=env — единая пара ADMIN_USERNAME / ADMIN_PASSWORD (старт/стейдж).
- AUTH_MODE=operators — логин по e-mail из таблицы operators.
    - Если есть столбец password_hash — сверка bcrypt.
    - Иначе можно временно задать OPERATORS_GLOBAL_PASSWORD в .env.
"""

from __future__ import annotations

import os
import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from database.models import Operators

# ВАЖНО: единый тег "Auth", чтобы не плодить "Auth"/"auth" в Swagger
router = APIRouter(prefix="/auth", tags=["Auth"])

# === конфиг ===
SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE_ME_IN_PROD")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
AUTH_MODE = os.getenv("AUTH_MODE", "env")  # env | operators

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

# для operators-режима без поля password_hash
OPERATORS_GLOBAL_PASSWORD = os.getenv("OPERATORS_GLOBAL_PASSWORD")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


# === схемы ===
class Token(BaseModel):
    """Ответ с JWT-токеном."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenData(BaseModel):
    """Декодированная полезная нагрузка токена."""
    sub: str
    user_id: Optional[int] = None
    email: Optional[str] = None


class UserOut(BaseModel):
    """Профиль пользователя для /auth/me."""
    id: int
    name: Optional[str]
    last_name: Optional[str]
    email: Optional[str]
    active: Optional[bool]


class ChangePasswordIn(BaseModel):
    """Тело запроса для смены пароля самим пользователем."""
    old_password: str
    new_password: str

class RegisterIn(BaseModel):
    email: str
    password: str

# === утилиты ===
def verify_password(plain: str, hashed: str) -> bool:
    """Проверяет соответствие пароля bcrypt-хэшу."""
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False


def hash_password(plain: str) -> str:
    """Возвращает bcrypt-хэш пароля."""
    return pwd_context.hash(plain)


def create_access_token(data: dict, expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES) -> str:
    """Создаёт подписанный JWT с полем exp."""
    to_encode = data.copy()
    expire = dt.datetime.utcnow() + dt.timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def validate_password_strength(pw: str) -> None:
    """Простейшая проверка сложности (можешь усилить по желанию)."""
    if len(pw) < 12:
        raise HTTPException(status_code=400, detail="Password too short (min 12)")
    # при желании: добавить проверки на цифры/символы/регистр


# === repo/helpers ===
async def get_operator_by_email(db: AsyncSession, email: str) -> Optional[Operators]:
    """Возвращает оператора по email (case-insensitive)."""
    email_norm = (email or "").strip()
    res = await db.execute(
        select(Operators).where(func.lower(Operators.email) == func.lower(email_norm))
    )
    return res.scalar_one_or_none()


async def auth_env(username: str, password: str) -> dict | None:
    """Аутентификация по ENV-паре (ADMIN_USERNAME/ADMIN_PASSWORD)."""
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        return {"sub": username, "user_id": 0, "email": username}
    return None


async def auth_operator(db: AsyncSession, username: str, password: str) -> dict | None:
    """Аутентификация по operators: e-mail + password (bcrypt или общий пароль из ENV)."""
    op = await get_operator_by_email(db, username)
    if not op:
        return None

    password_hash = getattr(op, "password_hash", None)
    if password_hash:
        if not verify_password(password, password_hash):
            return None
    else:
        if not OPERATORS_GLOBAL_PASSWORD or password != OPERATORS_GLOBAL_PASSWORD:
            return None

    return {"sub": op.email or str(op.id), "user_id": op.id, "email": op.email}


# === dependencies ===
async def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenData:
    """Декодирует JWT и возвращает структуру TokenData. 401 — если токен некорректный/просрочен."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub: str = payload.get("sub")
        user_id = payload.get("user_id")
        email = payload.get("email")
        if sub is None:
            raise credentials_exception
        return TokenData(sub=sub, user_id=user_id, email=email)
    except JWTError:
        raise credentials_exception


async def get_current_operator(
    data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Operators:
    """Возвращает объект оператора по user_id из токена (для эндпоинтов, где требуется реальный оператор)."""
    if not data.user_id:
        raise HTTPException(status_code=401, detail="Operator context required")
    res = await db.execute(select(Operators).where(Operators.id == data.user_id))
    op = res.scalar_one_or_none()
    if not op:
        raise HTTPException(status_code=401, detail="Operator not found")
    return op


# === endpoints ===
@router.post("/token", response_model=Token, summary="Получить JWT токен")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Возвращает JWT-токен по учетным данным.

    Тело запроса (form-data):
        - username: str
        - password: str

    Поведение:
        - AUTH_MODE=env — сверка с ADMIN_USERNAME/ADMIN_PASSWORD.
        - AUTH_MODE=operators — поиск оператора по email и проверка пароля.

    Ответ:
        Token(access_token, token_type='bearer', expires_in)
    """
    if AUTH_MODE == "operators":
        claims = await auth_operator(db, form_data.username, form_data.password)
    else:
        claims = await auth_env(form_data.username, form_data.password)

    if not claims:
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    token = create_access_token(
        data={"sub": claims["sub"], "user_id": claims.get("user_id"), "email": claims.get("email")}
    )
    return Token(access_token=token, expires_in=ACCESS_TOKEN_EXPIRE_MINUTES)


@router.get("/me", response_model=UserOut, summary="Профиль текущего пользователя")
async def me(
    data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Возвращает профиль по токену.

    В режиме env возвращает виртуального пользователя (id=0).
    В режиме operators — запись из таблицы operators.
    """
    if data.user_id and AUTH_MODE == "operators":
        # сперва пробуем по email, затем по user_id
        op = None
        if data.email:
            op = await get_operator_by_email(db, data.email)
        if not op:
            res = await db.execute(select(Operators).where(Operators.id == data.user_id))
            op = res.scalar_one_or_none()
        if not op:
            raise HTTPException(status_code=404, detail="User not found")
        return UserOut(
            id=op.id, name=op.name, last_name=op.last_name, email=op.email, active=getattr(op, "active", None)
        )
    # env mode
    return UserOut(id=0, name="Admin", last_name=None, email=data.email, active=True)

@router.post("/register", response_model=Token, status_code=201, summary="Регистрация (первая установка пароля)")
async def register(
    body: RegisterIn,
    db: AsyncSession = Depends(get_db),
):
    """
    Регистрирует пользователя по email, если:
      - оператор существует,
      - active = true,
      - пароль ещё не установлен (password_hash IS NULL).

    После успешной установки пароля сразу возвращает JWT.
    """
    email_norm = body.email.strip()
    if not email_norm:
        raise HTTPException(status_code=400, detail="Email is required")

    validate_password_strength(body.password)

    # 1) находим оператора по email (CI)
    op = await get_operator_by_email(db, email_norm)
    if not op:
        raise HTTPException(status_code=404, detail="Email not found")

    # 2) проверяем активность
    if getattr(op, "active", None) is not True:
        raise HTTPException(status_code=400, detail="Operator is not active")

    # 3) не должен иметь уже установленного пароля
    if getattr(op, "password_hash", None):
        raise HTTPException(status_code=409, detail="Password already set")

    # 4) атомарно устанавливаем пароль (защита от гонки):
    #    апдейтим только если password_hash ещё NULL и active = true
    new_hash = hash_password(body.password)
    result = await db.execute(
        update(Operators)
        .where(
            Operators.id == op.id,
            Operators.password_hash.is_(None),
            Operators.active.is_(True),
        )
        .values(password_hash=new_hash)
        .returning(Operators.id)
    )
    row = result.first()
    if not row:
        # кто-то успел поставить пароль параллельно или оператор деактивирован
        raise HTTPException(status_code=409, detail="Password already set or operator inactive")
    await db.commit()

    # 5) выдаём токен сразу после регистрации
    token = create_access_token(data={"sub": op.email or str(op.id), "user_id": op.id, "email": op.email})
    return Token(access_token=token, expires_in=ACCESS_TOKEN_EXPIRE_MINUTES)

@router.post("/change-password", status_code=204, summary="Сменить пароль (self-service)")
async def change_password(
    body: ChangePasswordIn,
    op: Operators = Depends(get_current_operator),
    db: AsyncSession = Depends(get_db),
):
    """Смена пароля самим пользователем.

    Требуется валидный Bearer JWT. Проверяем старый пароль, валидируем новый,
    сохраняем bcrypt-хэш в поле operators.password_hash.
    """
    if not getattr(op, "password_hash", None):
        # Пароль ещё не задан — пусть сначала админ установит первый пароль.
        raise HTTPException(status_code=400, detail="Password is not set; contact admin")

    # проверяем старый пароль
    if not verify_password(body.old_password, op.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect old password")

    # простая валидация сложности
    validate_password_strength(body.new_password)

    # хешируем и сохраняем
    new_hash = hash_password(body.new_password)
    await db.execute(update(Operators).where(Operators.id == op.id).values(password_hash=new_hash))
    await db.commit()
