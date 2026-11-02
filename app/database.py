import aiosqlite
from contextlib import asynccontextmanager
from .config import DB_PATH

@asynccontextmanager
async def connect():
    # Соединение await-ится один раз; не оборачивать `await connect()` в
    # async with, иначе aiosqlite может повторно запустить worker thread.
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    finally:
        await conn.close()

async def initialize():
    async with connect() as c:
        await c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          user_id INTEGER PRIMARY KEY, timezone TEXT NOT NULL DEFAULT 'Europe/Helsinki',
          hw_on INTEGER NOT NULL DEFAULT 1, hw_freq INTEGER NOT NULL DEFAULT 1440,
          hw_from TEXT NOT NULL DEFAULT '18:00', hw_to TEXT NOT NULL DEFAULT '21:00',
          hw_days TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
          chores_on INTEGER NOT NULL DEFAULT 1, chores_from TEXT NOT NULL DEFAULT '09:00',
          chores_to TEXT NOT NULL DEFAULT '21:00', lesson_lead INTEGER NOT NULL DEFAULT 0,
          last_hw TEXT, last_chore TEXT, last_lesson TEXT
        );
        CREATE TABLE IF NOT EXISTS homework(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          subject TEXT NOT NULL, body TEXT NOT NULL, due TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS chores(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          body TEXT NOT NULL, day TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS lessons(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 4), number INTEGER NOT NULL,
          subject TEXT NOT NULL, starts TEXT NOT NULL, ends TEXT,
          FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS hw_idx ON homework(user_id,due,done);
        CREATE INDEX IF NOT EXISTS chores_idx ON chores(user_id,day,done);
        CREATE INDEX IF NOT EXISTS lessons_idx ON lessons(user_id,weekday,starts);
        """)
