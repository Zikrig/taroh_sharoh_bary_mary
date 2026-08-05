import asyncio
import logging

from aiogram import Bot, Dispatcher

from config import settings
from database import init_db
from handlers import router


async def main() -> None:
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN не задан. Скопируйте .env.example в .env и добавьте токен.")
    await init_db()
    bot = Bot(settings.bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
