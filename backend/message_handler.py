import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.models import Destination, Keyword, KeywordType

logger = logging.getLogger(__name__)


async def process_message(event, user_id: int, session_factory: async_sessionmaker) -> None:
    try:
        async with session_factory() as db:
            kw_result = await db.execute(select(Keyword).where(Keyword.user_id == user_id))
            keywords = kw_result.scalars().all()

            dest_result = await db.execute(select(Destination).where(Destination.user_id == user_id))
            destination = dest_result.scalar_one_or_none()

        if not destination:
            return

        text: str = ""
        if event.message.text:
           text = event.message.text
        else:
           text = getattr(event.message, "caption", "") or ""

        if not text and not event.message.media:
            return

        minus_words = [k.word for k in keywords if k.type == KeywordType.MINUS]
        for word in minus_words:
            if word.lower() in text.lower():
                logger.debug("Message blocked by MINUS keyword '%s'", word)
                return

        try:
            chat = await event.get_chat()
            source_name = getattr(chat, "title", None) or "Unknown"
        except Exception:
            source_name = "Unknown"

        footer = f"\n\n📍 Джерело: {source_name}"

        plus_words = [k.word for k in keywords if k.type == KeywordType.PLUS]
        for word in plus_words:
            if word.lower() in text.lower():
                msg = f"⚡️ ВАЖЛИВО | {text}{footer}"
                await _send(event.client, destination.chat_id, msg, event)
                return

        msg = f"📢 [{source_name}] | {text}{footer}"
        await _send(event.client, destination.chat_id, msg, event)

    except Exception as exc:
        logger.exception("Error processing message for user %s: %s", user_id, exc)


async def _send(client, chat_id: int, text: str, event) -> None:
    try:
        if event.message.media:
            await client.send_file(chat_id, event.message.media, caption=text[:1024])
        else:
            await client.send_message(chat_id, text)
    except Exception as exc:
        logger.exception("Failed to send message to %s: %s", chat_id, exc)
