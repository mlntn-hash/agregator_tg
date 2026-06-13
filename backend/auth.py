import hashlib
import hmac
import os
import time
from typing import Annotated

import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import get_db
from backend.models import User

SECRET_KEY = os.environ["SECRET_KEY"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
ENCRYPTION_KEY = os.environ["ENCRYPTION_KEY"].encode()

_fernet = Fernet(ENCRYPTION_KEY)
_bearer = HTTPBearer()


def verify_telegram_login(data: dict) -> bool:
    data = dict(data)
    hash_val = data.pop("hash", None)
    if not hash_val:
        return False

    auth_date = int(data.get("auth_date", 0))
    if time.time() - auth_date > 86400:
        return False

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    computed = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, hash_val)


def create_jwt(user_id: int) -> str:
    payload = {"sub": str(user_id), "iat": int(time.time())}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def decode_jwt(token: str) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return int(payload["sub"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def encrypt_session(session_str: str) -> str:
    return _fernet.encrypt(session_str.encode()).decode()


def decrypt_session(encrypted: str) -> str:
    return _fernet.decrypt(encrypted.encode()).decode()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    user_id = decode_jwt(credentials.credentials)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user
