import asyncio
import base64
import io
import logging
import os
from typing import Any, Optional

import qrcode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from backend.auth import decrypt_session, encrypt_session
from backend.message_handler import process_message
from backend.models import Source, User

logger = logging.getLogger(__name__)

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]


class UserbotManager:
    def __init__(self) -> None:
        self._clients: dict[int, TelegramClient] = {}
        self._pending: dict[int, tuple[TelegramClient, str]] = {}
        self._qr_pending: dict[int, dict[str, Any]] = {}
        self._session_factory: Optional[async_sessionmaker] = None

    async def startup(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory
        async with session_factory() as db:
            result = await db.execute(
                select(User).where(User.session_string.isnot(None))
            )
            users = result.scalars().all()

        for user in users:
            try:
                decrypted = decrypt_session(user.session_string)
                await self._start_client(user.id, decrypted)
            except Exception as exc:
                logger.exception("Failed to start client for user %s: %s", user.id, exc)

        logger.info("UserbotManager started %d client(s)", len(self._clients))

    async def shutdown(self) -> None:
        for client in self._clients.values():
            try:
                await client.disconnect()
            except Exception:
                pass
        self._clients.clear()

    async def _start_client(self, user_id: int, session_string: str) -> TelegramClient:
        if user_id in self._clients:
            try:
                await self._clients[user_id].disconnect()
            except Exception:
                pass

        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            raise RuntimeError(f"Client for user {user_id} is not authorized")

        self._clients[user_id] = client
        await self._register_handlers(user_id)
        return client

    async def _register_handlers(self, user_id: int) -> None:
        client = self._clients.get(user_id)
        if not client:
            return

        for callback, event in client.list_event_handlers():
            client.remove_event_handler(callback)

        async with self._session_factory() as db:
            result = await db.execute(
                select(Source).where(Source.user_id == user_id, Source.is_active == True)
            )
            sources = result.scalars().all()

        chat_ids = [s.chat_id for s in sources]
        if not chat_ids:
            logger.debug("No active sources for user %s, skipping handler registration", user_id)
            return

        sf = self._session_factory

        @client.on(events.NewMessage(chats=chat_ids))
        async def handler(event):
            await process_message(event, user_id, sf)

        logger.info("Registered handler for user %s on %d chat(s)", user_id, len(chat_ids))

    async def reload_sources(self, user_id: int) -> None:
        if user_id not in self._clients:
            return
        await self._register_handlers(user_id)

    async def send_code(self, user_id: int, phone: str) -> str:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        result = await client.send_code_request(phone)
        self._pending[user_id] = (client, phone)
        return result.phone_code_hash

    async def sign_in(
        self, user_id: int, phone: str, code: str, phone_code_hash: str
    ) -> str:
        if user_id not in self._pending:
            raise ValueError("No pending auth session. Call send_code first.")

        client, _ = self._pending.pop(user_id)
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except Exception:
            await client.disconnect()
            raise

        session_string = client.session.save()
        self._clients[user_id] = client
        await self._register_handlers(user_id)
        return encrypt_session(session_string)

    async def start_qr_session(self, user_id: int) -> str:
        # Cancel any previous QR session for this user
        prev = self._qr_pending.pop(user_id, None)
        if prev:
            if prev.get("task"):
                prev["task"].cancel()
            try:
                await prev["client"].disconnect()
            except Exception:
                pass

        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        qr_login = await client.qr_login()

        state: dict[str, Any] = {"client": client, "session": None, "error": None, "task": None}

        async def _wait():
            try:
                await qr_login.wait(timeout=120)
                state["session"] = client.session.save()
            except asyncio.TimeoutError:
                state["error"] = "QR code expired"
            except Exception as exc:
                state["error"] = str(exc)

        state["task"] = asyncio.create_task(_wait())
        self._qr_pending[user_id] = state

        img = qrcode.make(qr_login.url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    async def check_qr_status(self, user_id: int) -> Optional[str]:
        """Return encrypted session string if authorized, None if still pending, raises on error."""
        state = self._qr_pending.get(user_id)
        if not state:
            return None

        if state["error"]:
            self._qr_pending.pop(user_id, None)
            raise RuntimeError(state["error"])

        if state["session"] is not None:
            session_string = state["session"]
            client = state["client"]
            self._qr_pending.pop(user_id, None)
            self._clients[user_id] = client
            await self._register_handlers(user_id)
            return encrypt_session(session_string)

        return None

    async def get_entity(self, user_id: int, identifier: str):
        client = self._clients.get(user_id)
        if not client:
            raise RuntimeError("Userbot not connected. Authorize first.")
        return await client.get_entity(identifier)

    def is_connected(self, user_id: int) -> bool:
        client = self._clients.get(user_id)
        return client is not None and client.is_connected()


userbot_manager = UserbotManager()
