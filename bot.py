import asyncio
import logging
import os
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path

import aiosqlite
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "").strip()
DB_PATH = os.getenv("DB_PATH", "data/studyhelper.sqlite3")
if not TOKEN or TOKEN.startswith("PASTE_"):
    raise SystemExit("Укажите BOT_TOKEN в .env или переменных окружения.")

logging.basicConfig(level=logging.INFO)
bot = Bot(TOKEN)
dp = Dispatcher()
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
FREQS = {"30": 30, "60": 60, "120": 120, "daily": 1440}
FREQ_LABELS = {"30": "Каждые 30 минут", "60": "Каждый час", "120": "Каждые 2 часа", "daily": "Один раз в день"}

class Input(StatesGroup):
    subject = State()
    hw_text = State()
    hw_date = State()
    edit_hw = State()
    day_text = State()
    schedule_subject = State()
    schedule_start = State()
    schedule_end = State()
    setting_timezone = State()
    setting_homework_window = State()
    setting_chores_window = State()

async def db():
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    return conn

async def init_db():
    async with await db() as c:
        await c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          user_id INTEGER PRIMARY KEY, timezone TEXT NOT NULL DEFAULT 'Europe/Moscow',
          hw_enabled INTEGER NOT NULL DEFAULT 1, hw_frequency INTEGER NOT NULL DEFAULT 1440,
          hw_start TEXT NOT NULL DEFAULT '18:00', hw_end TEXT NOT NULL DEFAULT '21:00',
          hw_days TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
          chores_enabled INTEGER NOT NULL DEFAULT 1, chores_start TEXT NOT NULL DEFAULT '09:00',
          chores_end TEXT NOT NULL DEFAULT '21:00', last_hw_date TEXT, last_chore_slot TEXT
        );
        CREATE TABLE IF NOT EXISTS homework(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          subject TEXT NOT NULL, description TEXT NOT NULL, due_date TEXT NOT NULL,
          done INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS chores(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          description TEXT NOT NULL, task_date TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS subjects(
          user_id INTEGER NOT NULL, name TEXT NOT NULL, PRIMARY KEY(user_id,name),
          FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS lessons(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          weekday INTEGER NOT NULL, lesson_no INTEGER NOT NULL, subject TEXT NOT NULL,
          start_time TEXT NOT NULL, end_time TEXT,
          FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        """)
        await c.commit()

async def ensure_user(uid):
    async with await db() as c:
        await c.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (uid,))
        await c.commit()

async def user(uid):
    async with await db() as c:
        cur = await c.execute("SELECT * FROM users WHERE user_id=?", (uid,))
        return await cur.fetchone()

def menu_kb():
    b = InlineKeyboardBuilder()
    for label, data in [
        ("🏠 Мой день","home"),("📝 Домашние задания","hw"),
        ("📌 Дела на день","chores"),("📅 Расписание","schedule"),
        ("📊 Статистика","stats"),("⚙️ Настройки","settings")
    ]:
        b.button(text=label, callback_data=data)
    b.adjust(1)
    return b.as_markup()

def back_kb(target="home"):
    b=InlineKeyboardBuilder(); b.button(text="⬅️ Назад",callback_data=target); return b.as_markup()

async def show(target, event, text, kb=None):
    if isinstance(event, CallbackQuery):
        try: await event.message.edit_text(text, reply_markup=kb)
        except Exception: await event.message.answer(text, reply_markup=kb)
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb)

async def home_text(uid):
    u=await user(uid); tz=ZoneInfo(u["timezone"]); now=datetime.now(tz); today=now.date().isoformat()
    async with await db() as c:
        h=await (await c.execute("SELECT COUNT(*) n FROM homework WHERE user_id=? AND done=0",(uid,))).fetchone()
        ch=await (await c.execute("SELECT COUNT(*) n FROM chores WHERE user_id=? AND task_date=? AND done=0",(uid,today))).fetchone()
        lessons=await (await c.execute("SELECT lesson_no,subject,start_time FROM lessons WHERE user_id=? AND weekday=? ORDER BY lesson_no",(uid,now.weekday()))).fetchall()
    lines=[f"🏠 <b>Мой день</b> — {now.strftime('%d.%m.%Y')}","",f"📝 Невыполненных домашних заданий: <b>{h['n']}</b>",f"📌 Дел на сегодня: <b>{ch['n']}</b>"]
    if lessons:
        lines += ["","📅 <b>Уроки сегодня</b>"]+[f"{x['lesson_no']}. {x['start_time']} — {x['subject']}" for x in lessons]
    else: lines += ["","Сегодня уроки не добавлены."]
    return "\n".join(lines)

@dp.message(CommandStart())
async def start(m: Message, state:FSMContext):
    await state.clear(); await ensure_user(m.from_user.id)
    await m.answer("Привет! Я StudyHelper — помощник для учёбы.\n\nВыбери раздел:",reply_markup=menu_kb())

@dp.message(Command("cancel"))
async def cancel(m:Message,state:FSMContext):
    await state.clear(); await m.answer("Ввод отменён.",reply_markup=menu_kb())

@dp.callback_query(F.data=="home")
async def home(q:CallbackQuery):
    await show("home",q,await home_text(q.from_user.id),menu_kb())

@dp.callback_query(F.data=="hw")
async def hw(q:CallbackQuery):
    uid=q.from_user.id
    async with await db() as c:
        rows=await (await c.execute("SELECT * FROM homework WHERE user_id=? AND done=0 ORDER BY due_date,id",(uid,))).fetchall()
    b=InlineKeyboardBuilder()
    for r in rows:
        b.button(text=f"{r['due_date']} · {r['subject']}: {r['description'][:24]}",callback_data=f"hwitem:{r['id']}")
    b.button(text="➕ Добавить задание",callback_data="hwadd")
    b.button(text="🏠 Меню",callback_data="home"); b.adjust(1)
    txt="📝 <b>Домашние задания</b>\n\n"+("\n".join(f"• {r['due_date']} — {r['subject']}: {r['description']}" for r in rows) if rows else "Невыполненных заданий нет.")
    await show("hw",q,txt,b.as_markup())

@dp.callback_query(F.data=="hwadd")
async def hwadd(q:CallbackQuery,state:FSMContext):
    await state.set_state(Input.subject)
    b=InlineKeyboardBuilder(); b.button(text="Отмена",callback_data="hw")
    await show("hwadd",q,"Введи предмет:",b.as_markup())

@dp.message(Input.subject)
async def hw_subject(m:Message,state:FSMContext):
    await state.update_data(subject=m.text.strip())
    await state.set_state(Input.hw_text); await m.answer("Опиши домашнее задание:")

@dp.message(Input.hw_text)
async def hw_text(m:Message,state:FSMContext):
    await state.update_data(description=m.text.strip()); await state.set_state(Input.hw_date)
    b=InlineKeyboardBuilder()
    for label,delta in [("Сегодня",0),("Завтра",1),("Послезавтра",2)]:
        b.button(text=label,callback_data=f"hwdate:{delta}")
    b.button(text="Отмена",callback_data="hw")
    b.adjust(3,1); await m.answer("Когда срок сдачи?",reply_markup=b.as_markup())

@dp.callback_query(F.data.startswith("hwdate:"))
async def hw_date(q:CallbackQuery,state:FSMContext):
    delta=int(q.data.split(":")[1]); data=await state.get_data()
    due=(date.today()+timedelta(days=delta)).isoformat()
    async with await db() as c:
        await c.execute("INSERT INTO homework(user_id,subject,description,due_date) VALUES(?,?,?,?)",(q.from_user.id,data["subject"],data["description"],due)); await c.commit()
    await state.clear(); await show("hwdate",q,"✅ Домашнее задание сохранено.",menu_kb())

@dp.callback_query(F.data.startswith("hwitem:"))
async def hw_item(q:CallbackQuery):
    tid=int(q.data.split(":")[1]); uid=q.from_user.id
    async with await db() as c:
        r=await (await c.execute("SELECT * FROM homework WHERE id=? AND user_id=?",(tid,uid))).fetchone()
    if not r: return await q.answer("Задание не найдено.",show_alert=True)
    b=InlineKeyboardBuilder(); b.button(text="✅ Выполнено",callback_data=f"hwdone:{tid}"); b.button(text="🗑 Удалить",callback_data=f"hwdel:{tid}"); b.button(text="⬅️ К заданиям",callback_data="hw"); b.adjust(1)
    await show("hwitem",q,f"<b>{r['subject']}</b>\n{r['description']}\nСрок: {r['due_date']}",b.as_markup())

@dp.callback_query(F.data.startswith("hwdone:"))
async def hw_done(q:CallbackQuery):
    tid=int(q.data.split(":")[1])
    async with await db() as c:
        await c.execute("UPDATE homework SET done=1 WHERE id=? AND user_id=?",(tid,q.from_user.id)); await c.commit()
    await show("hwdone",q,"✅ Задание отмечено выполненным.",back_kb("hw"))

@dp.callback_query(F.data.startswith("hwdel:"))
async def hw_del(q:CallbackQuery):
    tid=int(q.data.split(":")[1])
    async with await db() as c:
        await c.execute("DELETE FROM homework WHERE id=? AND user_id=?",(tid,q.from_user.id)); await c.commit()
    await show("hwdel",q,"🗑 Задание удалено.",back_kb("hw"))

@dp.callback_query(F.data=="chores")
async def chores(q:CallbackQuery):
    uid=q.from_user.id; today=date.today().isoformat()
    async with await db() as c:
        rows=await (await c.execute("SELECT * FROM chores WHERE user_id=? AND task_date=? ORDER BY id",(uid,today))).fetchall()
    b=InlineKeyboardBuilder()
    for r in rows:
        b.button(text=("✅ " if r["done"] else "⬜ ")+r["description"][:45],callback_data=f"chdone:{r['id']}")
    b.button(text="➕ Добавить дело",callback_data="chadd"); b.button(text="🏠 Меню",callback_data="home"); b.adjust(1)
    txt="📌 <b>Дела на сегодня</b>\n\n"+("\n".join(("✅ " if r["done"] else "⬜ ")+r["description"] for r in rows) if rows else "На сегодня дел пока нет.")
    await show("chores",q,txt,b.as_markup())

@dp.callback_query(F.data=="chadd")
async def chadd(q:CallbackQuery,state:FSMContext):
    await state.set_state(Input.day_text); await show("chadd",q,"Напиши дело на сегодня:",back_kb("chores"))

@dp.message(Input.day_text)
async def chsave(m:Message,state:FSMContext):
    async with await db() as c:
        await c.execute("INSERT INTO chores(user_id,description,task_date) VALUES(?,?,?)",(m.from_user.id,m.text.strip(),date.today().isoformat())); await c.commit()
    await state.clear(); await m.answer("✅ Дело добавлено.",reply_markup=menu_kb())

@dp.callback_query(F.data.startswith("chdone:"))
async def chdone(q:CallbackQuery):
    tid=int(q.data.split(":")[1])
    async with await db() as c:
        await c.execute("UPDATE chores SET done=CASE done WHEN 0 THEN 1 ELSE 0 END WHERE id=? AND user_id=?",(tid,q.from_user.id)); await c.commit()
    await show("chdone",q,"Статус дела обновлён.",back_kb("chores"))

@dp.callback_query(F.data=="schedule")
async def schedule(q:CallbackQuery):
    uid=q.from_user.id
    async with await db() as c:
        rows=await (await c.execute("SELECT * FROM lessons WHERE user_id=? ORDER BY weekday,lesson_no",(uid,))).fetchall()
    b=InlineKeyboardBuilder(); b.button(text="➕ Добавить урок",callback_data="lessonadd"); b.button(text="🏠 Меню",callback_data="home"); b.adjust(1)
    txt="📅 <b>Расписание (Пн–Пт)</b>\n\n"+("\n".join(f"{DAYS[r['weekday']]} · {r['lesson_no']}. {r['start_time']}–{r['end_time'] or '—'} · {r['subject']}" for r in rows) if rows else "Расписание пока пустое.")
    await show("schedule",q,txt,b.as_markup())

@dp.callback_query(F.data=="lessonadd")
async def lessonadd(q:CallbackQuery,state:FSMContext):
    await state.set_state(Input.schedule_subject)
    await show("lessonadd",q,"Введи название предмета:",back_kb("schedule"))

@dp.message(Input.schedule_subject)
async def lesson_sub(m:Message,state:FSMContext):
    await state.update_data(subject=m.text.strip()); await state.set_state(Input.schedule_start)
    await m.answer("Введи день и номер урока в формате: Пн 1")

@dp.message(Input.schedule_start)
async def lesson_day(m:Message,state:FSMContext):
    try:
        d,n=m.text.strip().split(); weekday=DAYS.index(d.capitalize()); num=int(n)
        if weekday>4 or num<1: raise ValueError()
    except Exception:
        return await m.answer("Формат: Пн 1, Вт 2 ... Пт 7. Выходные не поддерживаются.")
    await state.update_data(weekday=weekday,lesson_no=num); await state.set_state(Input.schedule_end)
    await m.answer("Введи время начала и, через пробел, время окончания (например 08:30 09:15). Если окончания нет — введи только время начала.")

@dp.message(Input.schedule_end)
async def lesson_save(m:Message,state:FSMContext):
    parts=m.text.strip().split()
    try:
        time.fromisoformat(parts[0]); end=parts[1] if len(parts)>1 else None
        if end: time.fromisoformat(end)
    except Exception: return await m.answer("Время должно быть в формате ЧЧ:ММ, например 08:30 09:15.")
    d=await state.get_data()
    async with await db() as c:
        await c.execute("INSERT INTO lessons(user_id,weekday,lesson_no,subject,start_time,end_time) VALUES(?,?,?,?,?,?)",(m.from_user.id,d["weekday"],d["lesson_no"],d["subject"],parts[0],end)); await c.commit()
    await state.clear(); await m.answer("✅ Урок добавлен.",reply_markup=menu_kb())

@dp.callback_query(F.data=="stats")
async def stats(q:CallbackQuery):
    uid=q.from_user.id
    async with await db() as c:
        rows=await (await c.execute("SELECT COUNT(*) total,SUM(done) done FROM homework WHERE user_id=?",(uid,))).fetchone()
        overdue=await (await c.execute("SELECT COUNT(*) n FROM homework WHERE user_id=? AND done=0 AND due_date<?",(uid,date.today().isoformat()))).fetchone()
    total=rows["total"] or 0; done=rows["done"] or 0; pending=total-done; pct=round(done*100/total) if total else 0
    await show("stats",q,f"📊 <b>Статистика</b>\n\nВсего заданий: {total}\nВыполнено: {done}\nОсталось: {pending}\nПросрочено: {overdue['n']}\nПрогресс: {pct}%",back_kb())

@dp.callback_query(F.data=="settings")
async def settings(q:CallbackQuery):
    u=await user(q.from_user.id); b=InlineKeyboardBuilder()
    b.button(text=f"Домашние задания: {'Вкл' if u['hw_enabled'] else 'Выкл'}",callback_data="set_hw_toggle")
    b.button(text=f"Частота: {FREQ_LABELS.get(str(u['hw_frequency']), 'Ежедневно')}",callback_data="set_freq")
    b.button(text=f"Дни: {u['hw_days']}",callback_data="set_days")
    b.button(text=f"Время ДЗ: {u['hw_start']}–{u['hw_end']}",callback_data="set_hw_window")
    b.button(text=f"Дела каждые 30 мин: {'Вкл' if u['chores_enabled'] else 'Выкл'}",callback_data="set_ch_toggle")
    b.button(text=f"Время дел: {u['chores_start']}–{u['chores_end']}",callback_data="set_ch_window")
    b.button(text=f"Часовой пояс: {u['timezone']}",callback_data="set_tz")
    b.button(text="🏠 Меню",callback_data="home"); b.adjust(1)
    await show("settings",q,"⚙️ <b>Настройки уведомлений</b>\n\nВыбери параметр:",b.as_markup())

@dp.callback_query(F.data=="set_hw_toggle")
async def hw_toggle(q:CallbackQuery):
    async with await db() as c:
        await c.execute("UPDATE users SET hw_enabled=1-hw_enabled WHERE user_id=?",(q.from_user.id,)); await c.commit()
    await settings(q)

@dp.callback_query(F.data=="set_ch_toggle")
async def ch_toggle(q:CallbackQuery):
    async with await db() as c:
        await c.execute("UPDATE users SET chores_enabled=1-chores_enabled WHERE user_id=?",(q.from_user.id,)); await c.commit()
    await settings(q)

@dp.callback_query(F.data=="set_freq")
async def set_freq(q:CallbackQuery):
    b=InlineKeyboardBuilder()
    for k,v in FREQ_LABELS.items(): b.button(text=v,callback_data=f"freq:{k}")
    b.button(text="⬅️ Настройки",callback_data="settings"); b.adjust(1)
    await show("freq",q,"Выбери частоту уведомлений о домашних заданиях:",b.as_markup())

@dp.callback_query(F.data.startswith("freq:"))
async def freq(q:CallbackQuery):
    k=q.data.split(":")[1]
    async with await db() as c:
        await c.execute("UPDATE users SET hw_frequency=? WHERE user_id=?",(FREQS[k],q.from_user.id)); await c.commit()
    await settings(q)

@dp.callback_query(F.data=="set_days")
async def set_days(q:CallbackQuery):
    u=await user(q.from_user.id); chosen=set(map(int,u["hw_days"].split(","))) if u["hw_days"] else set()
    b=InlineKeyboardBuilder()
    for i,d in enumerate(DAYS):
        b.button(text=("✅ " if i in chosen else "▫️ ")+d,callback_data=f"day:{i}")
    b.button(text="Готово",callback_data="settings"); b.adjust(4,3,1)
    await show("set_days",q,"Выбери дни недели (можно несколько):",b.as_markup())

@dp.callback_query(F.data.startswith("day:"))
async def day_toggle(q:CallbackQuery):
    i=int(q.data.split(":")[1]); u=await user(q.from_user.id); s=set(map(int,u["hw_days"].split(","))) if u["hw_days"] else set()
    s.symmetric_difference_update({i})
    async with await db() as c:
        await c.execute("UPDATE users SET hw_days=? WHERE user_id=?",(",".join(map(str,sorted(s))),q.from_user.id)); await c.commit()
    await set_days(q)

@dp.callback_query(F.data=="set_hw_window")
async def set_hw_window(q:CallbackQuery,state:FSMContext):
    await state.set_state(Input.setting_homework_window)
    await show("set_hw_window",q,"Введи начало и конец окна напоминаний о ДЗ, например: 08:00 21:00",back_kb("settings"))

@dp.message(Input.setting_homework_window)
async def save_hw_window(m:Message,state:FSMContext):
    await save_window(m,state,"hw_start","hw_end")

async def save_window(m,state,a,b):
    p=m.text.strip().split()
    try:
        if len(p)!=2: raise ValueError()
        time.fromisoformat(p[0]); time.fromisoformat(p[1])
    except Exception: return await m.answer("Нужен формат ЧЧ:ММ ЧЧ:ММ, например 08:00 21:00.")
    async with await db() as c:
        await c.execute(f"UPDATE users SET {a}=?,{b}=? WHERE user_id=?",(p[0],p[1],m.from_user.id)); await c.commit()
    await state.clear(); await m.answer("✅ Время сохранено.",reply_markup=menu_kb())

@dp.callback_query(F.data=="set_ch_window")
async def set_ch_window(q:CallbackQuery,state:FSMContext):
    await state.set_state(Input.setting_chores_window)
    await show("set_ch_window",q,"Введи начало и конец напоминаний о делах, например: 09:00 21:00",back_kb("settings"))

@dp.message(Input.setting_chores_window)
async def save_ch_window(m:Message,state:FSMContext):
    await save_window(m,state,"chores_start","chores_end")

@dp.callback_query(F.data=="set_tz")
async def set_tz(q:CallbackQuery,state:FSMContext):
    await state.set_state(Input.setting_timezone)
    await show("set_tz",q,"Введи часовой пояс из базы IANA, например Europe/Moscow, Europe/Helsinki или Europe/Berlin.",back_kb("settings"))

@dp.message(Input.setting_timezone)
async def save_tz(m:Message,state:FSMContext):
    try: ZoneInfo(m.text.strip())
    except ZoneInfoNotFoundError: return await m.answer("Неизвестный часовой пояс. Пример: Europe/Moscow")
    async with await db() as c:
        await c.execute("UPDATE users SET timezone=? WHERE user_id=?",(m.text.strip(),m.from_user.id)); await c.commit()
    await state.clear(); await m.answer("✅ Часовой пояс сохранён.",reply_markup=menu_kb())

async def notification_loop():
    while True:
        try:
            async with await db() as c:
                users=await (await c.execute("SELECT * FROM users")).fetchall()
            now_utc=datetime.utcnow()
            for u in users:
                try: now=datetime.now(ZoneInfo(u["timezone"]))
                except Exception: continue
                clock=now.strftime("%H:%M"); today=now.date().isoformat()
                if u["chores_enabled"] and u["chores_start"] <= clock <= u["chores_end"] and now.minute % 30 == 0:
                    slot=now.strftime("%Y-%m-%d %H:%M")
                    if u["last_chore_slot"] != slot:
                        async with await db() as c:
                            rows=await (await c.execute("SELECT description FROM chores WHERE user_id=? AND task_date=? AND done=0",(u["user_id"],today))).fetchall()
                            await c.execute("UPDATE users SET last_chore_slot=? WHERE user_id=?",(slot,u["user_id"])); await c.commit()
                        if rows:
                            text="📌 <b>Напоминание о делах</b>\n\n"+"\n".join("• "+r["description"] for r in rows)
                            try: await bot.send_message(u["user_id"],text)
                            except Exception: pass
                if u["hw_enabled"] and clock >= u["hw_start"] and clock <= u["hw_end"] and now.weekday() in set(map(int,u["hw_days"].split(","))) and now.minute == 0:
                    freq=int(u["hw_frequency"]); due_slot=now.strftime("%Y-%m-%d %H:%M")
                    should=(now.hour*60+now.minute) % freq == 0
                    if should:
                        async with await db() as c:
                            rows=await (await c.execute("SELECT subject,description,due_date FROM homework WHERE user_id=? AND done=0 ORDER BY due_date",(u["user_id"],))).fetchall()
                        if rows:
                            text="📝 <b>Напоминание о домашних заданиях</b>\n\n"+"\n".join(f"• {r['subject']}: {r['description']} (до {r['due_date']})" for r in rows)
                            try: await bot.send_message(u["user_id"],text)
                            except Exception: pass
        except Exception:
            logging.exception("Ошибка цикла уведомлений")
        await asyncio.sleep(60)

async def main():
    await init_db()
    asyncio.create_task(notification_loop())
    await dp.start_polling(bot)

if __name__=="__main__":
    asyncio.run(main())
