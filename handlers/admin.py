import logging
import traceback
from datetime import datetime, timedelta
from aiogram import types, F, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import db
from config import ADMIN_ID
from utils.shared import set_role

logger = logging.getLogger(__name__)

class AdminStates(StatesGroup):
    waiting_for_broadcast_text = State()
    waiting_for_worker_id = State()

def register_admin(dp, bot: Bot):

    # --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ (Исправлено через Try/Except) ---
    async def send_admin_menu(message: types.Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats_menu"),
                InlineKeyboardButton(text="💰 Касса", callback_data="adm_finance_menu")
            ],
            [
                InlineKeyboardButton(text="👥 Воркеры", callback_data="adm_workers_manage"),
                InlineKeyboardButton(text="📢 Рассылка", callback_data="adm_broadcast")
            ],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="adm_close")]
        ])
        text = "🛠 <b>Панель управления проектом</b>"
        
        try:
            # Пытаемся отредактировать (если это вызов из callback)
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            # Если это новое сообщение (команда /admin) или текст тот же
            await message.answer(text, reply_markup=kb, parse_mode="HTML")

    @dp.message(F.text == "/admin")
    async def admin_start(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await state.clear()
        await send_admin_menu(message)

    @dp.callback_query(F.data == "adm_back_to_main")
    async def back_to_main(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        await send_admin_menu(call.message)
        await call.answer()

    # --- ОБРАБОТКА ЗАЯВОК (Исправлен Split) ---
    @dp.callback_query(F.data.startswith("app_"))
    async def process_app(call: types.CallbackQuery):
        # Data: app_accept_12345 или app_decline_12345
        parts = call.data.split("_")
        action = parts[1]  # accept / decline
        target_id = int(parts[2])
        
        if action == "accept":
            await db.db_execute("INSERT INTO workers (user_id) VALUES ($1) ON CONFLICT DO NOTHING", target_id)
            await db.db_execute("UPDATE worker_applications SET status='accepted' WHERE user_id=$1", target_id)
            set_role(target_id, "worker")
            try:
                await bot.send_message(target_id, "🎉 <b>Ваша заявка одобрена!</b>\nТеперь вы можете принимать заказы.", parse_mode="HTML")
            except: pass
            await call.message.edit_text(f"✅ Юзер <code>{target_id}</code> принят в воркеры.", parse_mode="HTML")
        else:
            await db.db_execute("UPDATE worker_applications SET status='declined' WHERE user_id=$1", target_id)
            await call.message.edit_text(f"❌ Заявка <code>{target_id}</code> отклонена.", parse_mode="HTML")
        await call.answer()

    # --- УПРАВЛЕНИЕ ВОРКЕРАМИ ---
    @dp.callback_query(F.data == "adm_workers_manage")
    async def workers_manage(call: types.CallbackQuery):
        count = await db.db_fetchone("SELECT COUNT(*) FROM workers")
        apps = await db.db_fetchone("SELECT COUNT(*) FROM worker_applications WHERE status='pending'")
        
        text = (
            "👥 <b>Управление персоналом</b>\n\n"
            f"• Воркеров в штате: <b>{count['count']}</b>\n"
            f"• Новых заявок: <b>{apps['count']}</b>"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📨 Просмотр заявок", callback_data="adm_view_apps")],
            [InlineKeyboardButton(text="➕ Назначить по ID", callback_data="adm_add_worker_manual")],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]
        ])
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

    @dp.callback_query(F.data == "adm_view_apps")
    async def view_apps(call: types.CallbackQuery):
        apps = await db.db_fetchall("SELECT user_id, created_at FROM worker_applications WHERE status='pending' LIMIT 5")
        if not apps:
            return await call.answer("📩 Новых заявок нет", show_alert=True)
        
        await call.message.delete() # Удаляем меню, чтобы вывести карточки заявок
        for app in apps:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Принять", callback_data=f"app_accept_{app['user_id']}"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"app_decline_{app['user_id']}")
                ]
            ])
            await call.message.answer(f"👤 <b>Заявка от:</b> <code>{app['user_id']}</code>\n📅 Дата: {app['created_at']}", reply_markup=kb, parse_mode="HTML")

    # --- РАССЫЛКА ---
    @dp.callback_query(F.data == "adm_broadcast")
    async def broadcast_start(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.waiting_for_broadcast_text)
        await call.message.edit_text("📢 <b>Введите текст рассылки:</b>\n\nПоддерживается HTML-теги.", 
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="adm_back_to_main")]]))

    @dp.message(AdminStates.waiting_for_broadcast_text)
    async def broadcast_finish(message: types.Message, state: FSMContext):
        query = "SELECT user_id FROM balances UNION SELECT user_id FROM invoices"
        users = await db.db_fetchall(query)
        
        sent = 0
        status_msg = await message.answer(f"⏳ Отправка... (0/{len(users)})")
        
        for u in users:
            try:
                await bot.send_message(u['user_id'], message.text, parse_mode="HTML")
                sent += 1
            except: pass
        
        await status_msg.edit_text(f"✅ Рассылка завершена!\nДоставлено: <b>{sent}</b> пользователям.", parse_mode="HTML")
        await state.clear()
        await send_admin_menu(message)

    # --- ЗАКРЫТИЕ И ПРОЧЕЕ ---
    @dp.callback_query(F.data == "adm_close")
    async def close_admin(call: types.CallbackQuery):
        await call.message.delete()
        await call.answer()
