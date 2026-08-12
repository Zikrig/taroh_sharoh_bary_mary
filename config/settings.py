from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    support_url: str = os.getenv("SUPPORT_URL", "https://t.me/your_support")
    ai_api_key: str = (
        os.getenv("AITUNNEL_API_KEY")
        or os.getenv("API_KEY")
        or os.getenv("OPENAI_API_KEY", "")
    )
    ai_base_url: str = os.getenv("AITUNNEL_BASE_URL", "https://api.aitunnel.ru/v1/")
    ai_model: str = os.getenv("AITUNNEL_MODEL", "deepseek-v4-flash-0731")
    ai_temperature: float = float(os.getenv("AITUNNEL_TEMPERATURE", "1.2"))
    ai_presence_penalty: float = float(os.getenv("AITUNNEL_PRESENCE_PENALTY", "0.3"))
    ai_frequency_penalty: float = float(os.getenv("AITUNNEL_FREQUENCY_PENALTY", "0.2"))
    database_path: Path = Path(os.getenv("DATABASE_PATH", "data/bot.db"))
    save_payload_samples: bool = os.getenv("SAVE_PAYLOAD_SAMPLES", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    admin_ids: tuple[int, ...] = tuple(
        int(value.strip())
        for value in os.getenv("ADMINS_ID", "").split(",")
        if value.strip().isdigit()
    )


settings = Settings()
