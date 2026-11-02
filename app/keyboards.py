from aiogram.utils.keyboard import InlineKeyboardBuilder

MAIN = [
    ("🏠 Мой день","home"), ("📝 Домашние задания","hw"),
    ("📌 Дела на день","chores"), ("📅 Расписание","schedule"),
    ("✅ Выполненные задания","done"), ("⏰ Просроченные","overdue"),
    ("📊 Статистика","stats"), ("⚙️ Настройки","settings")
]

def keyboard(items, columns=1):
    b=InlineKeyboardBuilder()
    for title, data in items:
        b.button(text=title, callback_data=data)
    b.adjust(columns)
    return b.as_markup()
