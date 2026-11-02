import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "").strip()
DB_PATH = os.getenv("DB_PATH", "data/studyhelper.sqlite3")
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
if not TOKEN or TOKEN == "PASTE_TOKEN_FROM_BOTFATHER":
    raise RuntimeError("Не задан BOT_TOKEN: заполните .env или переменную окружения хостинга.")
