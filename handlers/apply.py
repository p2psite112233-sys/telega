import logging
from datetime import datetime, timezone, timedelta
from aiogram import types, F, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

import db
from config import ADMIN_ID  # Добавили импорт ID админа
from handlers.common import WorkerRegStates

logger = logging.getLogger(__name__)

def register_apply(dp, bot: Bot):

    # --- ШАГ 1: Старт анкеты ---
    @dp.callback_query(F.data == "worker_apply")
    async def worker_apply_start(call: types.CallbackQuery, state: FSMContext):
        await state.clear() 
        uid = call.from_user.id
        
        try:
            await call.message.delete()
        except:
            pass

        row = await db.db_fetchone(
            "SELECT next_apply_at FROM worker_applications WHERE user_id=$1", uid
        )
        if row and row["next_apply_at"]:
            next_apply = row["next_apply_at"]
            now = datetime.now(timezone.utc)
            if next_apply.replace(tzinfo=timezone.utc) > now:
                formatted = next_apply.strftime("%d %B %Y г., %H:%M")
                await bot.send_message(
                    call.message.chat.id,
                    f"⏳ <b>Повторная подача пока недоступна</b>\n\n"
                    f"Повторную заявку можно подать после {formatted}.",
                    parse_mode="HTML"
                )
                return await call.answer()

        username = f"@{call.from_user.username}" if call.from_user.username else f"ID: {uid}"
        await bot.send_message(
            call.message.chat.id,
            f"<b>📝 Заполнение анкеты исполнителя</b>\n\n"
            f"<blockquote>Ответьте на вопросы по шагам. На каждом этапе можно вернуться назад или остановить заполнение.</blockquote>\n\n"
            f"1. Ваш основной аккаунт {username}?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да", callback_data="apply_q1_yes")],
                [InlineKeyboardButton(text="❌ Нет", callback_data="apply_q1_no")],
                [InlineKeyboardButton(text="💔 Отмена", callback_data="client_back_menu")]
            ])
        )
        return await call.answer()

    # --- ШАГ 1 (Отказ) ---
    @dp.callback_query(F.data == "apply_q1_no")
    async def apply_q1_no(call: types.CallbackQuery):
        uid = call.from_user.id
        next_apply = datetime.now(timezone.utc) + timedelta(days=1)
        await db.db_execute(
            """INSERT INTO worker_applications (user_id, status, next_apply_at)
               VALUES ($1, 'rejected', $2)
               ON CONFLICT (user_id) DO UPDATE SET status='rejected', next_apply_at=$2""",
            uid, next_apply
        )
        formatted = next_apply.strftime("%d %B %Y г., %H:%M")
        await call.message.edit_text(
            f"❌ <b>Заявка недоступна</b>\n\n"
            f"Напишите нам с другого аккаунта.\n\n"
            f"Повторную заявку можно подать после {formatted}.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")]
            ])
        )
        return await call.answer()

    # --- ШАГ 2: Опыт ---
    @dp.callback_query(F.data == "apply_q1_yes")
    async def apply_q1_yes(call: types.CallbackQuery, state: FSMContext):
        await state.update_data(main_acc="Да")
        await call.message.edit_text(
            "<b>2️⃣ Опыт в сфере обменов и оплат</b>\n\n"
            "Выберите вариант, который лучше всего описывает ваш текущий опыт.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Менее 1 мес", callback_data="apply_q2_0")],
                [InlineKeyboardButton(text="1-2 мес", callback_data="apply_q2_1")],
                [InlineKeyboardButton(text="3-5 мес", callback_data="apply_q2_3")],
                [InlineKeyboardButton(text="Более 5+ мес", callback_data="apply_q2_5")],
                [InlineKeyboardButton(text="⏪ Назад", callback_data="worker_apply"),
                 InlineKeyboardButton(text="❌ Отмена заявки", callback_data="client_back_menu")]
            ])
        )
        return await call.answer()

    # --- ШАГ 3: Банки ---
    @dp.callback_query(F.data.startswith("apply_q2_"))
    async def apply_q2_done(call: types.CallbackQuery, state: FSMContext):
        exp_map = {"0": "Менее 1 мес", "1": "1-2 мес", "3": "3-5 мес", "5": "Более 5+ мес"}
        exp_key = call.data.split("_")[2]
        await state.update_data(experience=exp_map.get(exp_key, "Не указано"))
        
        await call.message.edit_text(
            "<b>3️⃣ Банки для работы</b>\n\nКакими банками (РФ) вы располагаете чаще всего?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Сбербанк / Т-Банк", callback_data="apply_q3_major")],
                [InlineKeyboardButton(text="Другие / Райффайзен / Альфа", callback_data="apply_q3_other")],
                [InlineKeyboardButton(text="⏪ Назад", callback_data="apply_q1_yes"),
                 InlineKeyboardButton(text="❌ Отмена", callback_data="client_back_menu")]
            ])
        )
        return await call.answer()

    @dp.callback_query(F.data == "apply_q3_back")
    async def apply_q3_back(call: types.CallbackQuery, state: FSMContext):
        await apply_q2_done(call, state)

    # --- ШАГ 4: Направления ---
    @dp.callback_query(F.data.startswith("apply_q3_"))
    async def apply_q3_done_select_dir(call: types.CallbackQuery, state: FSMContext):
        bank_value = "Сбер/Т-Банк" if "major" in call.data else "Другие"
        await state.update_data(bank=bank_value, directions=[])
        await show_q4(call, [])
        return await call.answer()

    async def show_q4(call: types.CallbackQuery, selected: list):
        options = [
            ("💳 Карта под оплату", "dir_card"), ("📲 Переводы по СБП", "dir_sbp"),
            ("🏦 Переводы по карте", "dir_transfer"), ("📱 Пополнение номеров", "dir_phone"),
            ("🔳 Оплата по QR-Коду", "dir_qr"),
        ]
        buttons = []
        for label, k in options:
            prefix = "✅ " if k in selected else ""
            buttons.append([InlineKeyboardButton(text=f"{prefix}{label}", callback_data=f"apply_q4_toggle_{k}")])
        
        nav = [InlineKeyboardButton(text="⏪ Назад", callback_data="apply_q3_back")]
        if selected:
            nav.append(InlineKeyboardButton(text="➡️ Далее", callback_data="apply_q4_next"))
        buttons.append(nav)
        buttons.append([InlineKeyboardButton(text="💔 Отмена", callback_data="client_back_menu")])
        
        await call.message.edit_text(
            "<b>4️⃣ Направления работы</b>\n\nВыберите варианты и нажмите «➡️ Далее».",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    @dp.callback_query(F.data.startswith("apply_q4_toggle_"))
    async def apply_q4_toggle(call: types.CallbackQuery, state: FSMContext):
        key = call.data.replace("apply_q4_toggle_", "")
        data = await state.get_data()
        selected = list(data.get("directions", []))
        if key in selected: selected.remove(key)
        else: selected.append(key)
        await state.update_data(directions=selected)
        await show_q4(call, selected)
        return await call.answer()

    # --- ШАГ 5: Чаты ---
    @dp.callback_query(F.data == "apply_q4_next")
    async def apply_q4_next(call: types.CallbackQuery, state: FSMContext):
        data = await state.get_data()
        await show_q5(call, data.get("chats", []))
        return await call.answer()

    async def show_q5(call: types.CallbackQuery, selected: list):
        options = [
            ("BSG", "chat_bsg"), ("FRK", "chat_frk"), ("OLD", "chat_old"),
            ("JESS", "chat_jess"), ("VERA", "chat_vera"), ("Другой чат", "chat_other")
        ]
        buttons = []
        for label, k in options:
            prefix = "✅ " if k in selected else ""
            buttons.append([InlineKeyboardButton(text=f"{prefix}{label}", callback_data=f"apply_q5_toggle_{k}")])
            
        nav = [InlineKeyboardButton(text="⏪ Назад", callback_data="apply_q4_back")]
        if selected:
            nav.append(InlineKeyboardButton(text="➡️ Далее", callback_data="apply_q5_next"))
        buttons.append(nav)
        buttons.append([InlineKeyboardButton(text="💔 Отмена", callback_data="client_back_menu")])
        
        await call.message.edit_text(
            "<b>5️⃣ Активные рабочие чаты</b>\n\nВыберите чаты, в которых состояли.",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    @dp.callback_query(F.data.startswith("apply_q5_toggle_"))
    async def apply_q5_toggle(call: types.CallbackQuery, state: FSMContext):
        key = call.data.replace("apply_q5_toggle_", "")
        data = await state.get_data()
        selected = list(data.get("chats", []))
        if key in selected: selected.remove(key)
        else: selected.append(key)
        await state.update_data(chats=selected)
        await show_q5(call, selected)
        return await call.answer()

    # --- ШАГ 6: Доп. информация ---
    @dp.callback_query(F.data == "apply_q5_next")
    async def apply_q6_start(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(WorkerRegStates.waiting_for_extra_info)
        text = (
            "<b>6️⃣ Дополнительная информация</b>\n\n"
            "<blockquote>Напишите всё, что поможет при рассмотрении анкеты (опыт, другие чаты, график).</blockquote>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏪ Назад", callback_data="apply_q4_next")],
            [InlineKeyboardButton(text="🛑 Отмена", callback_data="client_back_menu")]
        ])
        try:
            await call.message.delete()
        except:
            pass
        await bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=kb)
        return await call.answer()

    # --- ФИНАЛЬНЫЙ ПРЕДПРОСМОТР ---
    @dp.message(WorkerRegStates.waiting_for_extra_info)
    async def apply_q6_text_handler(message: types.Message, state: FSMContext):
        await state.update_data(extra_info=message.text)
        data = await state.get_data()
        
        dirs_map = {"dir_card": "Карта", "dir_sbp": "СБП", "dir_transfer": "Перевод", "dir_phone": "Телефон", "dir_qr": "QR"}
        chats_map = {"chat_bsg": "BSG", "chat_frk": "FRK", "chat_old": "OLD", "chat_jess": "JESS", "chat_vera": "VERA", "chat_other": "Другой"}
        
        sel_dirs = ", ".join([dirs_map.get(d, d) for d in data.get("directions", [])])
        sel_chats = ", ".join([chats_map.get(c, c) for c in data.get("chats", [])])
        
        report = (
            "📋 <b>Предпросмотр анкеты</b>\n\n"
            f"👤 <b>Аккаунт:</b> Да\n"
            f"📊 <b>Опыт:</b> {data.get('experience')}\n"
            f"🏦 <b>Банки:</b> {data.get('bank')}\n"
            f"🛠 <b>Направления:</b> {sel_dirs}\n"
            f"💬 <b>Чаты:</b> {sel_chats}\n"
            f"📝 <b>Доп. инфо:</b> <i>{data.get('extra_info')}</i>\n\n"
            "<blockquote>Проверьте данные. Если всё верно — отправляйте анкету.</blockquote>"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Отправить анкету", callback_data="apply_final_confirm")],
            [InlineKeyboardButton(text="🔄 Заполнить заново", callback_data="worker_apply")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="client_back_menu")]
        ])
        await message.answer(report, parse_mode="HTML", reply_markup=kb)

    # --- ФИНАЛЬНАЯ ОТПРАВКА АДМИНУ ---
    @dp.callback_query(F.data == "apply_final_confirm")
    async def apply_final_confirm(call: types.CallbackQuery, state: FSMContext, bot: Bot):
        data = await state.get_data()
        uid = call.from_user.id
        username = f"@{call.from_user.username}" if call.from_user.username else "скрыт"
        
        # Перевод данных для админа
        dirs_map = {"dir_card": "Карта", "dir_sbp": "СБП", "dir_transfer": "Перевод", "dir_phone": "Телефон", "dir_qr": "QR"}
        chats_map = {"chat_bsg": "BSG", "chat_frk": "FRK", "chat_old": "OLD", "chat_jess": "JESS", "chat_vera": "VERA", "chat_other": "Другой"}
        sel_dirs = ", ".join([dirs_map.get(d, d) for d in data.get("directions", [])])
        sel_chats = ", ".join([chats_map.get(c, c) for c in data.get("chats", [])])

        admin_text = (
            "📩 <b>НОВАЯ ЗАЯВКА ВОРКЕРА</b>\n\n"
            f"👤 <b>Юзер:</b> {username} (<code>{uid}</code>)\n"
            f"📊 <b>Опыт:</b> {data.get('experience')}\n"
            f"🏦 <b>Банки:</b> {data.get('bank')}\n"
            f"🛠 <b>Направления:</b> {sel_dirs}\n"
            f"💬 <b>Чаты:</b> {sel_chats}\n"
            f"📝 <b>Доп:</b> {data.get('extra_info')}"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принять", callback_data=f"adm_ap_yes_{uid}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_ap_no_{uid}")
            ]
        ])

        # САМА ОТПРАВКА
        try:
            await bot.send_message(ADMIN_ID, admin_text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error sending apply to admin: {e}")

        await call.message.edit_text(
            "✅ <b>Заявка отправлена!</b>\n\nОжидайте решения администрации. Вам придет уведомление.",
            parse_mode="HTML"
        )
        await state.clear()
        return await call.answer()
