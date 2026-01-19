import os
from typing import List
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Bot configuration"""

    # Telegram Bot
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

    # Channel
    CHANNEL_ID: int = int(os.getenv("CHANNEL_ID", "0"))
    CHANNEL_USERNAME: str = os.getenv("CHANNEL_USERNAME", "")
    BOT_USERNAME: str = os.getenv("BOT_USERNAME", "")

    # Admins
    ADMIN_IDS: List[int] = [
        int(x.strip())
        for x in os.getenv("ADMIN_IDS", "").split(",")
        if x.strip()
    ]

    # Pyrogram (for indexing)
    API_ID: int = int(os.getenv("API_ID", "0"))
    API_HASH: str = os.getenv("API_HASH", "")

    # Search settings
    SIMILARITY_THRESHOLD: float = 0.65
    MAX_SIMILAR_RESULTS: int = 3

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/bot.db"

    # Paths
    DATA_DIR: str = "data"
    FAISS_INDEX_PATH: str = "data/faiss.index"
    DOCUMENTS_PATH: str = "data/documents.json"


config = Config()
