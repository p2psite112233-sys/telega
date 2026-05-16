import logging
from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

import db

logger = logging.getLogger(__name__)

def register_apply(dp, bot):

    # Шаг 1: Старт анкеты / Проверка ограничений
    @dp.callback_query(F.data == "worker_apply")
    async def worker_apply_start(call: types.CallbackQuery):
        uid = call.from_user.id
        chat_id = call.message.chat.id
        
        try:
            await call.message.delete()
        except:
            pass

        from datetime import datetime, timezone
        row = await db.db_fetchone(
            "SELECT next_apply_at FROM worker_applications WHERE user_id=$1", uid
        )
        if row and row["next_apply_at"]:
            next_apply = row["next_apply_at"]
            now = datetime.now(timezone.utc)
            if next_apply.replace(tzinfo=timezone.utc) > now:
                formatted = next_apply.strftime("%d %B %Y г., %H:%M")
                await bot.send_message(
                    chat_id,
                    f"⏳ <b>Повторная подача пока недоступна</b>\n\n"
                    f"Повторную заявку можно подать после {formatted}.",
                    parse_mode="HTML"
                )
                return await call.answer()

        username = f"@{call.from_user.username}" if call.from_user.username else f"ID: {uid}"
        await bot.send_message(
            chat_id,
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

    # Шаг 1 (Отказ): Блокировка на сутки
    @dp.callback_query(F.data == "apply_q1_no")
    async def apply_q1_no(call: types.CallbackQuery):
        uid = call.from_user.id
        chat_id = call.message.chat.id
        
        try:
            await call.message.delete()
        except:
            pass

        from datetime import datetime, timezone, timedelta
        next_apply = datetime.now(timezone.utc) + timedelta(days=1)
        await db.db_execute(
            """INSERT INTO worker_applications (user_id, status, next_apply_at)
               VALUES ($1, 'rejected', $2)
               ON CONFLICT (user_id) DO UPDATE SET status='rejected', next_apply_at=$2""",
            uid, next_apply
        )
        formatted = next_apply.strftime("%d %B %Y г., %H:%M")
        await bot.send_message(
            chat_id,
            f"❌ <b>Заявка недоступна</b>\n\n"
            f"Напишите нам с другого аккаунта.\n\n"
            f"Повторную заявку можно подать после {formatted}.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")]
            ])
        )
        return await call.answer()

    # Шаг 2: Выбор опыта
    @dp.callback_query(F.data == "apply_q1_yes")
    async def apply_q1_yes(call: types.CallbackQuery):
        chat_id = call.message.chat.id
        try:
            await call.message.delete()
        except:
            pass

        await bot.send_message(
            chat_id,
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

    # Шаг 3: Выбор банков
    @dp.callback_query(F.data.startswith("apply_q2_"))
    async def apply_q2_done(call: types.CallbackQuery):
        chat_id = call.message.chat.id
        try:
            await call.message.delete()
        except:
            pass

        await bot.send_message(
            chat_id,
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

    # Шаг 3 (Назад)
    @dp.callback_query(F.data == "apply_q3_back")
    async def apply_q3_back(call: types.CallbackQuery):
        try:
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
        except Exception as e:
            logger.error(f"[apply_q3_back] edit error: {e}")
        return await call.answer()

    # Шаг 4: Выбор направлений (Первичный вход)
    @dp.callback_query(F.data.startswith("apply_q3_"))
    async def apply_q3_done_select_dir(call: types.CallbackQuery, state: FSMContext):
        chat_id = call.message.chat.id
        bank_value = call.data.split("_")[2]
        await state.update_data(bank=bank_value, directions=[])
        
        options = [
            ("💳 Карта под оплату", "dir_card"),
            ("📲 Переводы по СБП", "dir_sbp"),
            ("🏦 Переводы по карте", "dir_transfer"),
            ("📱 Пополнение номеров", "dir_phone"),
            ("🔳 Оплата по QR-Коду", "dir_qr"),
        ]
        buttons = []
        for label, k in options:
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"apply_q4_toggle_{k}")])
        
        buttons.append([
            InlineKeyboardButton(text="⏪ Назад", callback_data="apply_q3_back"),
            InlineKeyboardButton(text="💔 Отмена", callback_data="client_back_menu")
        ])

        try:
            await call.message.delete()
        except:
            pass

        await bot.send_message(
            chat_id,
            "<b>4️⃣ Направления работы</b>\n\n"
            "Выберите один или несколько вариантов (появятся галочки), затем нажмите кнопку «➡️ Далее».",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        return await call.answer()

    # Шаг 4: Переключение чекбоксов (галочек)
    @dp.callback_query(F.data.startswith("apply_q4_toggle_"))
    async def apply_q4_toggle(call: types.CallbackQuery, state: FSMContext):
        key = call.data.replace("apply_q4_toggle_", "")
        data = await state.get_data()
        selected = list(data.get("directions", []))
        
        if key in selected:
            selected.remove(key)
        else:
            selected.append(key)
            
        await state.update_data(directions=selected)
        
        options = [
            ("💳 Карта под оплату", "dir_card"),
            ("📲 Переводы по СБП", "dir_sbp"),
            ("🏦 Переводы по карте", "dir_transfer"),
            ("📱 Пополнение номеров", "dir_phone"),
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
        
        try:
            await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        except Exception as e:
            logger.error(f"[apply_q4_toggle] edit error: {e}")
        return await call.answer()

    # Шаг 4 (Назад): Возврат к выбору направлений
    @dp.callback_query(F.data == "apply_q4_back")
    async def apply_q4_back(call: types.CallbackQuery, state: FSMContext):
        data = await state.get_data()
        selected = list(data.get("directions", []))
        options = [
            ("💳 Карта под оплату", "dir_card"),
            ("📲 Переводы по СБП", "dir_sbp"),
            ("🏦 Переводы по карте", "dir_transfer"),
            ("📱 Пополнение номеров", "dir_phone"),
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
        
        try:
            await call.message.edit_text(
                "<b>4️⃣ Направления работы</b>\n\nМожно выбрать несколько вариантов.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
        except Exception as e:
            logger.error(f"[apply_q4_back] edit error: {e}")
        return await call.answer()

    # Шаг 5: Выбор чатов (Первичный вход)
    @dp.callback_query(F.data == "apply_q4_next")
    async def apply_q4_next(call: types.CallbackQuery, state: FSMContext):
        chat_id = call.message.chat.id
        data = await state.get_data()
        selected_chats = list(data.get("chats", []))
        
        options = [
            ("BSG", "chat_bsg"), ("FRK", "chat_frk"), ("OLD", "chat_old"),
            ("JESS", "chat_jess"), ("VERA", "chat_vera"), ("Другой чат", "chat_other")
        ]
        buttons = []
        for label, k in options:
            prefix = "✅ " if k in selected_chats else ""
            buttons.append([InlineKeyboardButton(text=f"{prefix}{label}", callback_data=f"apply_q5_toggle_{k}")])
            
        nav = [InlineKeyboardButton(text="⏪ Назад", callback_data="apply_q4_back")]
        if selected_chats:
            nav.append(InlineKeyboardButton(text="➡️ Далее", callback_data="apply_q5_next"))
        buttons.append(nav)
        buttons.append([InlineKeyboardButton(text="💔 Отмена", callback_data="client_back_menu")])
        
        text = (
            "<b>5️⃣ Активные рабочие чаты</b>\n\n"
            "Выберите чаты, в которых вы уже состоите или работали. После выбора появится кнопка перехода дальше."
        )
        try:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        except:
            await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        return await call.answer()

    # Шаг 5: Переключение чекбоксов чатов
    @dp.callback_query(F.data.startswith("apply_q5_toggle_"))
    async def apply_q5_toggle(call: types.CallbackQuery, state: FSMContext):
        key = call.data.replace("apply_q5_toggle_", "")
        data = await state.get_data()
        selected = list(data.get("chats", []))
        
        if key in selected:
            selected.remove(key)
        else:
            selected.append(key)
            
        await state.update_data(chats=selected)
        
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
        
        try:
            await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        except Exception as e:
            logger.error(f"[apply_q5_toggle] edit error: {e}")
        return await call.answer()

    # Конец анкеты (Заглушка)
    @dp.callback_query(F.data == "apply_q5_next")
    async def apply_q5_next_done(call: types.CallbackQuery):
        chat_id = call.message.chat.id
        text = "🚧 <b>Следующий шаг анкеты в разработке</b>"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")]])
        
        try:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except:
            await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)
        return await call.answer()
