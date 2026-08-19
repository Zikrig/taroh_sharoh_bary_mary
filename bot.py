import asyncio
import logging

from aiogram import Bot, Dispatcher

from config.settings import settings
from database.repository import init_db
from handlers.router import bot_commands, router
from handlers.admin_prompts import router as prompt_admin_router


async def main() -> None:
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN не задан. Скопируйте .env.example в .env и добавьте токен.")
    await init_db()
    bot = Bot(settings.bot_token)
    await bot.set_my_commands(bot_commands())
    dispatcher = Dispatcher()
    dispatcher.include_router(prompt_admin_router)
    dispatcher.include_router(router)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
