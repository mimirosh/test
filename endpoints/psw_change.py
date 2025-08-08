from pydantic import BaseModel
from fastapi import HTTPException, status
from .auth import get_current_operator, hash_password, verify_password  # если у тебя в том же модуле

class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str

@router.post("/change-password", status_code=204, summary="Сменить пароль (self-service)")
async def change_password(
    body: ChangePasswordIn,
    op = Depends(get_current_operator),
    db: AsyncSession = Depends(get_db),
):
    # если у старого нет password_hash — запрещаем (или разрешаем без проверки — реши сам)
    if not getattr(op, "password_hash", None):
        raise HTTPException(status_code=400, detail="Password is not set; contact admin")

    from sqlalchemy import update
    from passlib.context import CryptContext
    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

    if not pwd.verify(body.old_password, op.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect old password")

    new_hash = pwd.hash(body.new_password)
    await db.execute(update(Operators).where(Operators.id == op.id).values(password_hash=new_hash))
    await db.commit()
