import logging
from aiogram import types, F, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta
from aiogram.fsm.context import FSMContext

import db
from config import ADMIN_ID

logger = logging.getLogger(__name__)

def register_admin(dp, bot: Bot):

    # 1. ГЛАВНОЕ МЕНЮ (Вызывается командой /admin)
    @dp.message(F.text == "/admin")
    async def admin_main_menu(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        
        # Принудительно сбрасываем любые стейты (вводы сумм и т.д.) из других файлов
        await state.clear()
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats_menu")],
            [InlineKeyboardButton(text="👥 Воркеры", callback_data="adm_workers_menu")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="adm_close")]
        ])
        await message.answer("🛠 <b>Панель администратора</b>", reply_markup=kb)

    # 2. МЕНЮ ВЫБОРА ПЕРИОДА
    @dp.callback_query(F.data == "adm_stats_menu")
    async def stats_menu(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 День", callback_data="st_day"),
                InlineKeyboardButton(text="📆 Неделя", callback_data="st_week"),
                InlineKeyboardButton(text="🗓 Месяц", callback_data="st_month")
            ],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]
        ])
        await call.message.edit_text("📈 <b>Выберите период для отчета:</b>", reply_markup=kb)
        await call.answer()

    # 3. ОБРАБОТКА СТАТИСТИКИ (ИСПРАВЛЕНО: БЕЗ ОШИБОК ДАТЫ)
    @dp.callback_query(F.data.startswith("st_"))
    async def process_stats(call: types.CallbackQuery):
        period = call.data.split("_")[1]
        
        # Используем "наивное" время без часовых поясов (offset-naive)
        now = datetime.now()
        
        if period == "day": 
            since = now - timedelta(days=1)
            label = "день"
        elif period == "week": 
            since = now - timedelta(weeks=1)
            label = "неделю"
        else: 
            since = now - timedelta(days=30)
            label = "месяц"

        try:
            # Принудительно убираем инфо о часовом поясе для совместимости с БД
            since = since.replace(tzinfo=None)

            # Выполняем запрос
            row = await db.db_fetchone("SELECT COUNT(*) as total FROM orders WHERE created_at >= $1", since)
            total = row["total"] if row else 0

            text = (f"📈 <b>Статистика за {label}:</b>\n\n"
                    f"▫️ Всего заказов: <b>{total}</b>")

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_stats_menu")]
            ])
            await call.message.edit_text(text, reply_markup=kb)
        except Exception as e:
            logger.error(f"Ошибка БД в статистике: {e}")
            await call.message.answer(f"⚠️ Ошибка БД: <code>{e}</code>")
        
        await call.answer()

    # 4. МЕНЮ ВОРКЕРОВ
    @dp.callback_query(F.data == "adm_workers_menu")
    async def workers_menu(call: types.CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Найти по ID", callback_data="adm_find_worker")],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]
        ])
        await call.message.edit_text("👤 <b>Управление воркерами</b>", reply_markup=kb)
        await call.answer()

    # 5. НАВИГАЦИЯ (НАЗАД / ЗАКРЫТЬ)
    @dp.callback_query(F.data == "adm_back_to_main")
    async def back_to_main(call: types.CallbackQuery, state: FSMContext):
        # Сбрасываем стейт и вызываем функцию главного меню
        await state.clear()
        # Для простоты просто редактируем текущее сообщение под главное меню
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats_menu")],
            [InlineKeyboardButton(text="👥 Воркеры", callback_data="adm_workers_menu")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="adm_close")]
        ])
        await call.message.edit_text("🛠 <b>Панель администратора</b>", reply_markup=kb)
        await call.answer()

    @dp.callback_query(F.data == "adm_close")
    async def close_admin(call: types.CallbackQuery):
        try:
            await call.message.delete()
        except:
            pass
        await call.answer()
