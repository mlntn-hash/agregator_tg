import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import (
    create_jwt,
    decrypt_session,
    encrypt_session,
    get_current_user,
    verify_telegram_login,
)
from backend.database import AsyncSessionLocal, engine, get_db
from backend.models import Base, Destination, Keyword, KeywordType, Source, User
from backend.userbot_manager import userbot_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await userbot_manager.startup(AsyncSessionLocal)
    yield
    await userbot_manager.shutdown()


app = FastAPI(title="Telegram Aggregator", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class TelegramAuthData(BaseModel):
    id: int
    first_name: str
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


class PhoneRequest(BaseModel):
    phone: str


class CodeRequest(BaseModel):
    phone: str
    code: str
    phone_code_hash: str


class SourceRequest(BaseModel):
    identifier: str


class KeywordRequest(BaseModel):
    word: str
    type: str


class DestinationRequest(BaseModel):
    identifier: str


class QrStatusRequest(BaseModel):
    token: str


# ── Aliases ───────────────────────────────────────────────────────────────────

CurrentUser = Annotated[User, Depends(get_current_user)]
DB = Annotated[AsyncSession, Depends(get_db)]


# ── Auth endpoints ────────────────────────────────────────────────────────────

@app.post("/api/auth/telegram")
async def auth_telegram(data: TelegramAuthData, db: DB) -> dict:
    payload = data.model_dump()
    if not verify_telegram_login(payload):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram auth data")

    result = await db.execute(select(User).where(User.telegram_id == data.id))
    user = result.scalar_one_or_none()

    if user:
        user.username = data.username
        user.first_name = data.first_name
    else:
        user = User(
            telegram_id=data.id,
            username=data.username,
            first_name=data.first_name,
        )
        db.add(user)

    await db.commit()
    await db.refresh(user)
    return {"token": create_jwt(user.id), "first_name": user.first_name}


@app.post("/api/auth/phone")
async def auth_phone(req: PhoneRequest, current_user: CurrentUser) -> dict:
    try:
        phone_code_hash = await userbot_manager.send_code(current_user.id, req.phone)
        return {"phone_code_hash": phone_code_hash}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/auth/code")
async def auth_code(req: CodeRequest, current_user: CurrentUser, db: DB) -> dict:
    try:
        encrypted_session = await userbot_manager.sign_in(
            current_user.id, req.phone, req.code, req.phone_code_hash
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    current_user.session_string = encrypted_session
    await db.commit()
    return {"status": "authorized"}


@app.post("/api/auth/qr-session")
async def auth_qr_session(current_user: CurrentUser) -> dict:
    try:
        qr_image = await userbot_manager.start_qr_session(current_user.id)
        return {"qr_image": qr_image}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/auth/qr-status")
async def auth_qr_status(req: QrStatusRequest, current_user: CurrentUser, db: DB) -> dict:
    try:
        encrypted_session = await userbot_manager.check_qr_status(current_user.id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if encrypted_session is None:
        return {"status": "pending"}

    current_user.session_string = encrypted_session
    await db.commit()
    return {"status": "authorized"}


# ── Sources endpoints ─────────────────────────────────────────────────────────

@app.get("/api/sources")
async def list_sources(current_user: CurrentUser, db: DB) -> list[dict]:
    result = await db.execute(
        select(Source).where(Source.user_id == current_user.id).order_by(Source.created_at)
    )
    sources = result.scalars().all()
    return [
        {
            "id": s.id,
            "chat_id": s.chat_id,
            "chat_title": s.chat_title,
            "chat_username": s.chat_username,
            "is_active": s.is_active,
        }
        for s in sources
    ]


@app.post("/api/sources", status_code=status.HTTP_201_CREATED)
async def add_source(req: SourceRequest, current_user: CurrentUser, db: DB) -> dict:
    try:
        entity = await userbot_manager.get_entity(current_user.id, req.identifier)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cannot resolve chat: {exc}")

    chat_id: int = entity.id
    chat_title: str = getattr(entity, "title", getattr(entity, "first_name", str(chat_id)))
    chat_username: str | None = getattr(entity, "username", None)

    result = await db.execute(
        select(Source).where(Source.user_id == current_user.id, Source.chat_id == chat_id)
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Source already added")

    source = Source(
        user_id=current_user.id,
        chat_id=chat_id,
        chat_title=chat_title,
        chat_username=chat_username,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    await userbot_manager.reload_sources(current_user.id)

    return {
        "id": source.id,
        "chat_id": source.chat_id,
        "chat_title": source.chat_title,
        "chat_username": source.chat_username,
        "is_active": source.is_active,
    }


@app.delete("/api/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: int, current_user: CurrentUser, db: DB) -> None:
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == current_user.id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    await db.delete(source)
    await db.commit()
    await userbot_manager.reload_sources(current_user.id)


@app.post("/api/sources/{source_id}/toggle")
async def toggle_source(source_id: int, current_user: CurrentUser, db: DB) -> dict:
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == current_user.id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    source.is_active = not source.is_active
    await db.commit()
    await userbot_manager.reload_sources(current_user.id)
    return {"id": source.id, "is_active": source.is_active}


# ── Keywords endpoints ────────────────────────────────────────────────────────

@app.get("/api/keywords")
async def list_keywords(current_user: CurrentUser, db: DB) -> list[dict]:
    result = await db.execute(
        select(Keyword).where(Keyword.user_id == current_user.id).order_by(Keyword.created_at)
    )
    return [
        {"id": k.id, "word": k.word, "type": k.type.value}
        for k in result.scalars().all()
    ]


@app.post("/api/keywords", status_code=status.HTTP_201_CREATED)
async def add_keyword(req: KeywordRequest, current_user: CurrentUser, db: DB) -> dict:
    try:
        kw_type = KeywordType(req.type.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail="type must be PLUS or MINUS")

    word = req.word.strip()
    if not word:
        raise HTTPException(status_code=400, detail="word cannot be empty")

    keyword = Keyword(user_id=current_user.id, word=word, type=kw_type)
    db.add(keyword)
    await db.commit()
    await db.refresh(keyword)
    return {"id": keyword.id, "word": keyword.word, "type": keyword.type.value}


@app.delete("/api/keywords/{keyword_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_keyword(keyword_id: int, current_user: CurrentUser, db: DB) -> None:
    result = await db.execute(
        select(Keyword).where(Keyword.id == keyword_id, Keyword.user_id == current_user.id)
    )
    keyword = result.scalar_one_or_none()
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword not found")

    await db.delete(keyword)
    await db.commit()


# ── Destination endpoints ─────────────────────────────────────────────────────

@app.get("/api/destination")
async def get_destination(current_user: CurrentUser, db: DB) -> dict | None:
    result = await db.execute(
        select(Destination).where(Destination.user_id == current_user.id)
    )
    dest = result.scalar_one_or_none()
    if not dest:
        return None
    return {"id": dest.id, "chat_id": dest.chat_id, "chat_title": dest.chat_title}


@app.post("/api/destination")
async def set_destination(req: DestinationRequest, current_user: CurrentUser, db: DB) -> dict:
    try:
        entity = await userbot_manager.get_entity(current_user.id, req.identifier)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cannot resolve channel: {exc}")

    chat_id: int = entity.id
    chat_title: str = getattr(entity, "title", getattr(entity, "first_name", str(chat_id)))

    result = await db.execute(
        select(Destination).where(Destination.user_id == current_user.id)
    )
    dest = result.scalar_one_or_none()

    if dest:
        dest.chat_id = chat_id
        dest.chat_title = chat_title
    else:
        dest = Destination(user_id=current_user.id, chat_id=chat_id, chat_title=chat_title)
        db.add(dest)

    await db.commit()
    await db.refresh(dest)
    return {"id": dest.id, "chat_id": dest.chat_id, "chat_title": dest.chat_title}


# ── Status endpoint ───────────────────────────────────────────────────────────

@app.get("/api/status")
async def bot_status(current_user: CurrentUser) -> dict:
    return {
        "userbot_connected": userbot_manager.is_connected(current_user.id),
        "has_session": current_user.session_string is not None,
    }


# ── Static files (must be last) ───────────────────────────────────────────────
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
