import asyncio, logging
from datetime import datetime, date, timedelta, time
from zoneinfo import ZoneInfo
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery
from app.config import TOKEN
from app.database import connect, initialize
from app.keyboards import MAIN, keyboard

logging.basicConfig(level=logging.INFO)
bot=Bot(TOKEN)
dp=Dispatcher(storage=MemoryStorage())
WD=["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
FREQ={30:"Каждые 30 минут",60:"Каждый час",120:"Каждые 2 часа",1440:"Ежедневно"}

class S(StatesGroup):
    subject=State(); body=State(); due=State(); hwedit=State()
    chore=State(); choreedit=State()
    lsubject=State(); lday=State(); ltime=State(); ledit=State()
    hwwindow=State(); chwindow=State(); timezone=State()

async def ensure(uid):
    async with connect() as c:
        await c.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)",(uid,))

async def getuser(uid):
    async with connect() as c:
        return await (await c.execute("SELECT * FROM users WHERE user_id=?",(uid,))).fetchone()

async def now_for(uid):
    u=await getuser(uid)
    return datetime.now(ZoneInfo(u["timezone"])),u

async def show(q,text,items=MAIN):
    try: await q.message.edit_text(text,reply_markup=keyboard(items))
    except Exception: await q.message.answer(text,reply_markup=keyboard(items))
    await q.answer()

def parse_date(s): return datetime.strptime(s.strip(),"%d.%m.%Y").date().isoformat()
def parse_time(s): return time.fromisoformat(s.strip()).strftime("%H:%M")

@dp.message(CommandStart())
async def start(m:Message,state:FSMContext):
    await state.clear(); await ensure(m.from_user.id)
    await m.answer("Привет! Это StudyHelper. Выбери раздел:",reply_markup=keyboard(MAIN))

@dp.message(Command("cancel"))
async def cancel(m:Message,state:FSMContext):
    await state.clear(); await m.answer("Ввод отменён.",reply_markup=keyboard(MAIN))

@dp.callback_query(F.data=="home")
async def home(q:CallbackQuery):
    await ensure(q.from_user.id); now,_=await now_for(q.from_user.id); day=now.date().isoformat()
    async with connect() as c:
        h=await (await c.execute("SELECT COUNT(*) n FROM homework WHERE user_id=? AND done=0",(q.from_user.id,))).fetchone()
        ch=await (await c.execute("SELECT COUNT(*) n FROM chores WHERE user_id=? AND day=? AND done=0",(q.from_user.id,day))).fetchone()
        ls=await (await c.execute("SELECT number,subject,starts FROM lessons WHERE user_id=? AND weekday=? ORDER BY starts",(q.from_user.id,now.weekday()))).fetchall()
    text=f"🏠 <b>Мой день — {now:%d.%m.%Y}</b>\n\nДомашних заданий: {h['n']}\nДел на сегодня: {ch['n']}\n\n<b>Уроки</b>\n"
    text+="\n".join(f"{r['number']}. {r['starts']} — {r['subject']}" for r in ls) if ls else "Уроки не добавлены."
    await show(q,text)

async def hwlist(q,kind):
    now,_=await now_for(q.from_user.id); today=now.date().isoformat()
    cond={"all":"done=0","today":"done=0 AND due=?","overdue":"done=0 AND due<?","done":"done=1"}[kind]
    params=(q.from_user.id,today) if kind in ("today","overdue") else (q.from_user.id,)
    async with connect() as c:
        rows=await (await c.execute(f"SELECT * FROM homework WHERE user_id=? AND {cond} ORDER BY due,id",params)).fetchall()
    labels={"all":"Домашние задания","today":"На сегодня","overdue":"Просроченные задания","done":"Выполненные задания"}
    b=[(f"{r['due']} · {r['subject']} · {r['body'][:22]}",f"hwitem:{r['id']}") for r in rows]
    b += [("➕ Добавить","hwadd"),("На сегодня","hwtoday"),("Все невыполненные","hw"),("🏠 Меню","home")]
    text=f"📝 <b>{labels[kind]}</b>\n\n"+("\n".join(f"• {r['due']} — {r['subject']}: {r['body']}" for r in rows) if rows else "Список пуст.")
    await show(q,text,b)

@dp.callback_query(F.data=="hw")
async def hw(q): await hwlist(q,"all")
@dp.callback_query(F.data=="hwtoday")
async def hwtoday(q): await hwlist(q,"today")
@dp.callback_query(F.data=="overdue")
async def overdue(q): await hwlist(q,"overdue")
@dp.callback_query(F.data=="done")
async def done(q): await hwlist(q,"done")

@dp.callback_query(F.data=="hwadd")
async def hwadd(q,state):
    await state.set_state(S.subject); await show(q,"Введи предмет:",[("Отмена","hw")])
@dp.message(S.subject)
async def subject(m,state):
    if not m.text: return await m.answer("Введи название предмета.")
    await state.update_data(subject=m.text.strip()); await state.set_state(S.body); await m.answer("Опиши домашнее задание:")
@dp.message(S.body)
async def body(m,state):
    if not m.text: return await m.answer("Введи описание.")
    await state.update_data(body=m.text.strip()); await state.set_state(S.due)
    await m.answer("Срок: ДД.ММ.ГГГГ или выбери:",reply_markup=keyboard([("Сегодня","due:0"),("Завтра","due:1"),("Послезавтра","due:2")],3))
async def savehw(uid,data,due):
    async with connect() as c:
        await c.execute("INSERT INTO homework(user_id,subject,body,due) VALUES(?,?,?,?)",(uid,data["subject"],data["body"],due))
@dp.callback_query(F.data.startswith("due:"))
async def duebutton(q,state):
    d=await state.get_data()
    if "subject" not in d: return await q.answer("Начни добавление заново.",show_alert=True)
    due=(date.today()+timedelta(days=int(q.data.split(":")[1]))).isoformat()
    await savehw(q.from_user.id,d,due); await state.clear(); await show(q,"✅ Задание сохранено.",[("К заданиям","hw"),("Меню","home")])
@dp.message(S.due)
async def duetext(m,state):
    try: due=parse_date(m.text)
    except Exception: return await m.answer("Дата должна быть в формате ДД.ММ.ГГГГ.")
    await savehw(m.from_user.id,await state.get_data(),due); await state.clear(); await m.answer("Сохранено.",reply_markup=keyboard(MAIN))

@dp.callback_query(F.data.startswith("hwitem:"))
async def hwitem(q):
    tid=int(q.data.split(":")[1])
    async with connect() as c: r=await (await c.execute("SELECT * FROM homework WHERE id=? AND user_id=?",(tid,q.from_user.id))).fetchone()
    if not r: return await q.answer("Не найдено.",show_alert=True)
    await show(q,f"<b>{r['subject']}</b>\n{r['body']}\nСрок: {r['due']}",[("✅ Выполнено",f"hwdone:{tid}"),("✏️ Изменить",f"hwedit:{tid}"),("🗑 Удалить",f"hwdel:{tid}"),("Назад","hw")])
@dp.callback_query(F.data.startswith("hwdone:"))
async def hwdone(q):
    tid=int(q.data.split(":")[1])
    async with connect() as c: await c.execute("UPDATE homework SET done=1 WHERE id=? AND user_id=?",(tid,q.from_user.id))
    await show(q,"Отмечено выполненным.",[("Выполненные","done"),("Задания","hw")])
@dp.callback_query(F.data.startswith("hwdel:"))
async def hwdel(q):
    tid=int(q.data.split(":")[1])
    async with connect() as c: await c.execute("DELETE FROM homework WHERE id=? AND user_id=?",(tid,q.from_user.id))
    await show(q,"Удалено.",[("Задания","hw"),("Меню","home")])
@dp.callback_query(F.data.startswith("hwedit:"))
async def hwedit(q,state):
    tid=int(q.data.split(":")[1])
    async with connect() as c: r=await (await c.execute("SELECT id FROM homework WHERE id=? AND user_id=?",(tid,q.from_user.id))).fetchone()
    if not r: return await q.answer("Не найдено.",show_alert=True)
    await state.update_data(tid=tid); await state.set_state(S.hwedit)
    await show(q,"Введи: Предмет | Описание",[("Отмена","hw")])
@dp.message(S.hwedit)
async def hwedit_save(m,state):
    try: sub,body=[x.strip() for x in m.text.split("|",1)]
    except Exception: return await m.answer("Формат: Математика | Упражнения 4–6")
    d=await state.get_data()
    async with connect() as c: await c.execute("UPDATE homework SET subject=?,body=? WHERE id=? AND user_id=?",(sub,body,d["tid"],m.from_user.id))
    await state.clear(); await m.answer("Изменено.",reply_markup=keyboard(MAIN))

@dp.callback_query(F.data=="chores")
async def chores(q):
    now,_=await now_for(q.from_user.id); today=now.date().isoformat()
    async with connect() as c: rows=await (await c.execute("SELECT * FROM chores WHERE user_id=? AND day=? ORDER BY id",(q.from_user.id,today))).fetchall()
    b=[(("✅ " if r["done"] else "⬜ ")+r["body"][:35],f"chitem:{r['id']}") for r in rows]
    b += [("➕ Добавить дело","chadd"),("📚 История","chhistory"),("🏠 Меню","home")]
    await show(q,"📌 <b>Дела на сегодня</b>\n\n"+("\n".join(("✅ " if r["done"] else "⬜ ")+r["body"] for r in rows) if rows else "Пока нет дел."),b)
@dp.callback_query(F.data=="chadd")
async def chadd(q,state):
    await state.set_state(S.chore); await show(q,"Напиши дело:",[("Отмена","chores")])
@dp.message(S.chore)
async def chsave(m,state):
    now,_=await now_for(m.from_user.id)
    async with connect() as c: await c.execute("INSERT INTO chores(user_id,body,day) VALUES(?,?,?)",(m.from_user.id,m.text.strip(),now.date().isoformat()))
    await state.clear(); await m.answer("Дело добавлено.",reply_markup=keyboard(MAIN))
@dp.callback_query(F.data.startswith("chitem:"))
async def chitem(q):
    tid=int(q.data.split(":")[1])
    async with connect() as c: r=await (await c.execute("SELECT * FROM chores WHERE id=? AND user_id=?",(tid,q.from_user.id))).fetchone()
    if not r: return await q.answer("Не найдено.",show_alert=True)
    await show(q,r["body"],[("Выполнено/не выполнено",f"chdone:{tid}"),("✏️ Изменить",f"chedit:{tid}"),("🗑 Удалить",f"chdel:{tid}"),("Назад","chores")])
@dp.callback_query(F.data.startswith("chdone:"))
async def chdone(q):
    tid=int(q.data.split(":")[1])
    async with connect() as c: await c.execute("UPDATE chores SET done=1-done WHERE id=? AND user_id=?",(tid,q.from_user.id))
    await show(q,"Статус обновлён.",[("К делам","chores")])
@dp.callback_query(F.data.startswith("chedit:"))
async def chedit(q,state):
    tid=int(q.data.split(":")[1])
    await state.update_data(tid=tid); await state.set_state(S.choreedit); await show(q,"Введи новое название дела:",[("Отмена","chores")])
@dp.message(S.choreedit)
async def chedit_save(m,state):
    d=await state.get_data()
    async with connect() as c: await c.execute("UPDATE chores SET body=? WHERE id=? AND user_id=?",(m.text.strip(),d["tid"],m.from_user.id))
    await state.clear(); await m.answer("Изменено.",reply_markup=keyboard(MAIN))
@dp.callback_query(F.data.startswith("chdel:"))
async def chdel(q):
    tid=int(q.data.split(":")[1])
    async with connect() as c: await c.execute("DELETE FROM chores WHERE id=? AND user_id=?",(tid,q.from_user.id))
    await show(q,"Удалено.",[("К делам","chores")])
@dp.callback_query(F.data=="chhistory")
async def chhistory(q):
    async with connect() as c: rows=await (await c.execute("SELECT day,body,done FROM chores WHERE user_id=? AND day<? ORDER BY day DESC LIMIT 50",(q.from_user.id,date.today().isoformat()))).fetchall()
    text="📚 <b>История дел</b>\n\n"+("\n".join(f"{r['day']} {'✅' if r['done'] else '⬜'} {r['body']}" for r in rows) if rows else "История пуста.")
    await show(q,text,[("Назад","chores"),("Меню","home")])

@dp.callback_query(F.data=="schedule")
async def schedule(q):
    async with connect() as c: rows=await (await c.execute("SELECT * FROM lessons WHERE user_id=? ORDER BY weekday,number",(q.from_user.id,))).fetchall()
    b=[(f"{WD[r['weekday']]} {r['number']}. {r['subject']} {r['starts']}",f"lesson:{r['id']}") for r in rows]
    b += [("➕ Добавить урок","lessonadd"),("🏠 Меню","home")]
    text="📅 <b>Расписание Пн–Пт</b>\n\n"+("\n".join(f"{WD[r['weekday']]} · {r['number']}. {r['starts']}–{r['ends'] or '—'} {r['subject']}" for r in rows) if rows else "Расписание пустое.")
    await show(q,text,b)
@dp.callback_query(F.data=="lessonadd")
async def lessonadd(q,state):
    await state.set_state(S.lsubject); await show(q,"Введи предмет:",[("Отмена","schedule")])
@dp.message(S.lsubject)
async def lsubject(m,state):
    await state.update_data(subject=m.text.strip()); await state.set_state(S.lday); await m.answer("День и номер урока, например Пн 1:")
@dp.message(S.lday)
async def lday(m,state):
    try:
        d,n=m.text.split(); wd=WD.index(d.capitalize()); num=int(n)
        if wd>4 or num<1: raise ValueError
    except Exception: return await m.answer("Пример: Пн 1. Только Пн–Пт.")
    await state.update_data(wd=wd,num=num); await state.set_state(S.ltime); await m.answer("Время начала и необязательного окончания: 08:30 09:15")
@dp.message(S.ltime)
async def ltime(m,state):
    try:
        p=m.text.split()
        if len(p) not in (1,2): raise ValueError
        start=parse_time(p[0]); end=parse_time(p[1]) if len(p)==2 else None
    except Exception: return await m.answer("Формат: 08:30 или 08:30 09:15")
    d=await state.get_data()
    async with connect() as c: await c.execute("INSERT INTO lessons(user_id,weekday,number,subject,starts,ends) VALUES(?,?,?,?,?,?)",(m.from_user.id,d["wd"],d["num"],d["subject"],start,end))
    await state.clear(); await m.answer("Урок добавлен.",reply_markup=keyboard(MAIN))
@dp.callback_query(F.data.startswith("lesson:"))
async def lesson_item(q):
    lid=int(q.data.split(":")[1])
    async with connect() as c: r=await (await c.execute("SELECT * FROM lessons WHERE id=? AND user_id=?",(lid,q.from_user.id))).fetchone()
    if not r: return await q.answer("Не найдено.",show_alert=True)
    await show(q,f"{WD[r['weekday']]} {r['number']}. {r['subject']}\n{r['starts']}–{r['ends'] or '—'}",[("✏️ Изменить",f"lessonedit:{lid}"),("🗑 Удалить",f"lessondel:{lid}"),("Назад","schedule")])
@dp.callback_query(F.data.startswith("lessonedit:"))
async def lessonedit(q,state):
    lid=int(q.data.split(":")[1]); await state.update_data(lid=lid); await state.set_state(S.ledit)
    await show(q,"Предмет | Пн | номер | начало | конец (конец можно пропустить)",[("Отмена","schedule")])
@dp.message(S.ledit)
async def lessonedit_save(m,state):
    try:
        p=[x.strip() for x in m.text.split("|")]; sub,day,num,st=p[:4]; wd=WD.index(day.capitalize()); num=int(num); st=parse_time(st); en=parse_time(p[4]) if len(p)>4 and p[4] else None
        if wd>4: raise ValueError
    except Exception: return await m.answer("Пример: Математика | Пн | 1 | 08:30 | 09:15")
    d=await state.get_data()
    async with connect() as c: await c.execute("UPDATE lessons SET subject=?,weekday=?,number=?,starts=?,ends=? WHERE id=? AND user_id=?",(sub,wd,num,st,en,d["lid"],m.from_user.id))
    await state.clear(); await m.answer("Урок изменён.",reply_markup=keyboard(MAIN))
@dp.callback_query(F.data.startswith("lessondel:"))
async def lessondel(q):
    lid=int(q.data.split(":")[1])
    async with connect() as c: await c.execute("DELETE FROM lessons WHERE id=? AND user_id=?",(lid,q.from_user.id))
    await show(q,"Урок удалён.",[("Расписание","schedule")])

@dp.callback_query(F.data=="stats")
async def stats(q):
    async with connect() as c:
        a=await (await c.execute("SELECT COUNT(*) n FROM homework WHERE user_id=?",(q.from_user.id,))).fetchone()
        b=await (await c.execute("SELECT COUNT(*) n FROM homework WHERE user_id=? AND done=1",(q.from_user.id,))).fetchone()
        o=await (await c.execute("SELECT COUNT(*) n FROM homework WHERE user_id=? AND done=0 AND due<?",(q.from_user.id,date.today().isoformat()))).fetchone()
    total=a["n"]; done=b["n"]
    await show(q,f"📊 <b>Статистика</b>\n\nВсего: {total}\nВыполнено: {done}\nОсталось: {total-done}\nПросрочено: {o['n']}\nПрогресс: {round(done*100/total) if total else 0}%",[("Меню","home")])

@dp.callback_query(F.data=="settings")
async def settings(q):
    u=await getuser(q.from_user.id)
    await show(q,"⚙️ <b>Настройки</b>",[
        (f"ДЗ: {'Вкл' if u['hw_on'] else 'Выкл'}","cfg:hw"),
        (f"Частота ДЗ: {FREQ[u['hw_freq']]}","cfg:freq"),
        (f"Дни ДЗ: {u['hw_days'] or 'не выбраны'}","cfg:days"),
        (f"Окно ДЗ: {u['hw_from']}–{u['hw_to']}","cfg:hwtime"),
        (f"Напоминания о делах: {'Вкл' if u['chores_on'] else 'Выкл'}","cfg:ch"),
        (f"Окно дел: {u['chores_from']}–{u['chores_to']}","cfg:chtime"),
        (f"Напоминание об уроке: {u['lesson_lead']} мин","cfg:lesson"),
        (f"Часовой пояс: {u['timezone']}","cfg:tz"),
        ("Меню","home")])
@dp.callback_query(F.data=="cfg:hw")
async def cfg_hw(q):
    async with connect() as c: await c.execute("UPDATE users SET hw_on=1-hw_on WHERE user_id=?",(q.from_user.id,))
    await settings(q)
@dp.callback_query(F.data=="cfg:ch")
async def cfg_ch(q):
    async with connect() as c: await c.execute("UPDATE users SET chores_on=1-chores_on WHERE user_id=?",(q.from_user.id,))
    await settings(q)
@dp.callback_query(F.data=="cfg:freq")
async def cfg_freq(q):
    await show(q,"Частота напоминаний о ДЗ:",[(v,f"freq:{k}") for k,v in FREQ.items()]+[("Назад","settings")])
@dp.callback_query(F.data.startswith("freq:"))
async def set_freq(q):
    val=int(q.data.split(":")[1])
    async with connect() as c: await c.execute("UPDATE users SET hw_freq=? WHERE user_id=?",(val,q.from_user.id))
    await settings(q)
@dp.callback_query(F.data=="cfg:days")
async def cfg_days(q):
    u=await getuser(q.from_user.id); selected=set(map(int,u["hw_days"].split(","))) if u["hw_days"] else set()
    b=[(("✅ " if i in selected else "▫️ ")+d,f"wd:{i}") for i,d in enumerate(WD)]
    b.append(("Готово","settings")); await show(q,"Выбери дни уведомлений:",b)
@dp.callback_query(F.data.startswith("wd:"))
async def set_day(q):
    i=int(q.data.split(":")[1]); u=await getuser(q.from_user.id); s=set(map(int,u["hw_days"].split(","))) if u["hw_days"] else set()
    s.symmetric_difference_update({i})
    async with connect() as c: await c.execute("UPDATE users SET hw_days=? WHERE user_id=?",(",".join(map(str,sorted(s))),q.from_user.id))
    await cfg_days(q)
@dp.callback_query(F.data=="cfg:hwtime")
async def cfg_hwtime(q,state):
    await state.set_state(S.hwwindow); await show(q,"Введи начало и конец окна ДЗ: 08:00 21:00",[("Отмена","settings")])
@dp.message(S.hwwindow)
async def save_hwtime(m,state): await save_window(m,state,"hw_from","hw_to")
@dp.callback_query(F.data=="cfg:chtime")
async def cfg_chtime(q,state):
    await state.set_state(S.chwindow); await show(q,"Введи начало и конец окна дел: 09:00 21:00",[("Отмена","settings")])
@dp.message(S.chwindow)
async def save_chtime(m,state): await save_window(m,state,"chores_from","chores_to")
async def save_window(m,state,col1,col2):
    try:
        p=m.text.split()
        if len(p)!=2: raise ValueError
        a,b=parse_time(p[0]),parse_time(p[1])
        if a>=b: raise ValueError
    except Exception: return await m.answer("Формат ЧЧ:ММ ЧЧ:ММ; начало должно быть раньше конца.")
    async with connect() as c: await c.execute(f"UPDATE users SET {col1}=?,{col2}=? WHERE user_id=?",(a,b,m.from_user.id))
    await state.clear(); await m.answer("Сохранено.",reply_markup=keyboard(MAIN))
@dp.callback_query(F.data=="cfg:lesson")
async def cfg_lesson(q):
    await show(q,"За сколько минут до урока напоминать?",[("Выключить","lead:0"),("5 минут","lead:5"),("10 минут","lead:10"),("15 минут","lead:15"),("30 минут","lead:30"),("Назад","settings")])
@dp.callback_query(F.data.startswith("lead:"))
async def set_lead(q):
    val=int(q.data.split(":")[1])
    async with connect() as c: await c.execute("UPDATE users SET lesson_lead=? WHERE user_id=?",(val,q.from_user.id))
    await settings(q)
@dp.callback_query(F.data=="cfg:tz")
async def cfg_tz(q,state):
    await state.set_state(S.timezone); await show(q,"Введи часовой пояс, например Europe/Helsinki или Europe/Berlin.",[("Отмена","settings")])
@dp.message(S.timezone)
async def save_tz(m,state):
    try: ZoneInfo(m.text.strip())
    except Exception: return await m.answer("Неизвестный часовой пояс.")
    async with connect() as c: await c.execute("UPDATE users SET timezone=? WHERE user_id=?",(m.text.strip(),m.from_user.id))
    await state.clear(); await m.answer("Часовой пояс сохранён.",reply_markup=keyboard(MAIN))

async def notifier():
    while True:
        try:
            async with connect() as c: users=await (await c.execute("SELECT * FROM users")).fetchall()
            for u in users:
                uid=u["user_id"]
                try: now=datetime.now(ZoneInfo(u["timezone"]))
                except Exception: continue
                day=now.date().isoformat(); minute=now.hour*60+now.minute; clock=now.strftime("%H:%M")
                # Дела: каждый 30-минутный интервал, начиная с выбранного времени.
                if u["chores_on"] and u["chores_from"]<=clock<=u["chores_to"]:
                    start=int(u["chores_from"][:2])*60+int(u["chores_from"][3:])
                    if minute>=start and (minute-start)%30==0:
                        slot=now.strftime("%Y-%m-%d %H:%M")
                        if slot!=u["last_chore"]:
                            async with connect() as c:
                                rows=await (await c.execute("SELECT body FROM chores WHERE user_id=? AND day=? AND done=0",(uid,day))).fetchall()
                                await c.execute("UPDATE users SET last_chore=? WHERE user_id=?",(slot,uid))
                            if rows:
                                try: await bot.send_message(uid,"📌 <b>Дела на сегодня</b>\n"+"\n".join("• "+r["body"] for r in rows))
                                except Exception: pass
                # ДЗ: интервал от начала окна; ежедневное — ровно в начале окна.
                days=set(map(int,u["hw_days"].split(","))) if u["hw_days"] else set()
                if u["hw_on"] and now.weekday() in days and u["hw_from"]<=clock<=u["hw_to"]:
                    start=int(u["hw_from"][:2])*60+int(u["hw_from"][3:]); elapsed=minute-start; freq=int(u["hw_freq"])
                    if elapsed>=0 and (elapsed==0 if freq==1440 else elapsed%freq==0):
                        slot=now.strftime("%Y-%m-%d %H:%M")
                        if slot!=u["last_hw"]:
                            async with connect() as c:
                                rows=await (await c.execute("SELECT subject,body,due FROM homework WHERE user_id=? AND done=0 ORDER BY due",(uid,))).fetchall()
                                await c.execute("UPDATE users SET last_hw=? WHERE user_id=?",(slot,uid))
                            if rows:
                                try: await bot.send_message(uid,"📝 <b>Домашние задания</b>\n"+"\n".join(f"• {r['subject']}: {r['body']} (до {r['due']})" for r in rows))
                                except Exception: pass
                # Напоминание об уроке за заданное число минут.
                lead=int(u["lesson_lead"])
                if lead and now.weekday()<5:
                    async with connect() as c:
                        lessons=await (await c.execute("SELECT subject,starts FROM lessons WHERE user_id=? AND weekday=?",(uid,now.weekday()))).fetchall()
                    for lesson in lessons:
                        startdt=datetime.combine(now.date(),time.fromisoformat(lesson["starts"]),tzinfo=now.tzinfo)
                        delta=(startdt-now).total_seconds()
                        if 0<=delta<60 and int(delta//60)==lead:
                            slot=f"{day} {lesson['starts']} {lead}"
                            if slot!=u["last_lesson"]:
                                async with connect() as c: await c.execute("UPDATE users SET last_lesson=? WHERE user_id=?",(slot,uid))
                                try: await bot.send_message(uid,f"🔔 Через {lead} минут урок: <b>{lesson['subject']}</b>.")
                                except Exception: pass
        except Exception: logging.exception("Ошибка планировщика")
        await asyncio.sleep(30)

async def main():
    await initialize()
    asyncio.create_task(notifier())
    logging.info("StudyHelper started")
    await dp.start_polling(bot)

if __name__=="__main__":
    asyncio.run(main())
