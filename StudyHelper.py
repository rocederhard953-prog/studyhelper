import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart

TOKEN = "9281990528:AAH9UkVXdlPJhri8Kk_WyHVN5ZhaWdDxv-k"

bot = Bot(token=TOKEN)
dp = Dispatcher()

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Домашние задания", callback_data="homework")],
        [InlineKeyboardButton(text="➕ Добавить задание", callback_data="add")],
        [InlineKeyboardButton(text="📅 Расписание", callback_data="schedule")],
        [InlineKeyboardButton(text="✅ Выполненные", callback_data="done")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")]
    ])

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "📚 STUDYHELPER\n\n"
        "Привет! 👋\n"
        "Я помогу тебе организовать учёбу!\n\n"
        "Выбери нужный раздел:",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "homework")
async def homework(callback):
    await callback.message.edit_text(
        "📝 Твои домашние задания\n\n"
        "Пока заданий нет.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить ДЗ", callback_data="add")],
            [InlineKeyboardButton(text="↩️ Главное меню", callback_data="menu")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "menu")
async def menu(callback):
    await callback.message.edit_text(
        "📚 STUDYHELPER\n\nВыбери нужный раздел:",
        reply_markup=main_menu()
    )
    await callback.answer()

@dp.callback_query()
async def other_buttons(callback):
    await callback.answer("Эта функция пока находится в разработке!")

async def main():
    print("StudyHelper запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())