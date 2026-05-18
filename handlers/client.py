import logging
from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import db
from config import PROFILE_BANNER_FILE_ID, ADMIN_ID
from handlers.common import WorkerRegStates
from handlers.dispute import DisputeStates

logger = logging.getLogger(__name__)

CLIENT_MENU_TEXT = (
    "<b>🏠 Send$Paid — Главное меню</b>\n\n"
    "<blockquote>Бот поможет получить карту под оплату, перевести деньги на карту/СБП, "
    "пополнить номер телефона или оплатить готовый QR-код.\n"
    "Все этапы заявки фиксируются внутри сервиса.</blockquote>\n\n"
    "💼 Комиссия сервиса: <b>20%</b> от суммы, но не меньше 30 RUB\n"
    "🆕 Уникальная карта: дополнительно <b>+5%</b>\n"
    "🔳 QR-оплата: скидка по комиссии <b>-8%</b>\n"
    "⚡️ Работаем <b>24/7</b>"
)

CLIENT_MENU_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="💳 Карта под оплату", callback_data="client_card"),
        InlineKeyboardButton(text="🏦 Перевод на карту", callback_data="client_transfer")
    ],
    [
        InlineKeyboardButton(text="📳 Пополнить номер", callback_data="client_phone"),
        InlineKeyboardButton(text="◾️ Оплата QR-Кода", callback_data="client_qr")
    ],
    [InlineKeyboardButton(text="🤑 Пополнить баланс", callback_data="client_topup")],
    [
        InlineKeyboardButton(text="🙋‍♂️ Профиль", callback_data="client_profile"),
        InlineKeyboardButton(text="📄 Стать исполнителем", callback_data="client_become_worker")
    ],
    [InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/usudhsuhd")]
])


def register_client(dp, bot):

    @dp.callback_query(F.data.startswith("cancel_order_"))
    async def cancel_order(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        uid = call.from_user.id
        row = await db.db_fetchone("SELECT status, total_usdt, worker_id FROM orders WHERE id=$1 AND user_id=$2", order_id, uid)
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)
        status = row["status"]
        if status == "DONE":
            return await call.answer("❌ Нельзя отменить завершённую заявку", show_alert=True)
        if status not in ("NEW", "IN_PROGRESS"):
            return await call.answer("❌ Заявку нельзя отменить", show_alert=True)
        result = await db.db_execute(
            "UPDATE orders SET status='CANCELLED' WHERE id=$1 AND status IN ('NEW', 'IN_PROGRESS')", order_id
        )
        if "UPDATE 0" in result:
            return await call.answer("❌ Заявка уже отменена или завершена", show_alert=True)
        total_usdt = float(row["total_usdt"]) if row["total_usdt"] else 0.0
        worker_id = row["worker_id"]
        await db.unfreeze_back(uid, total_usdt)
        try:
            await call.message.edit_text(f"❌ Заявка #{order_id} отменена\n\n💰 Средства возвращены на баланс")
        except Exception as e:
            logger.error(f"[cancel_order] edit error: {e}")
        await call.answer("✅ Заявка отменена", show_alert=True)
        if worker_id:
            try:
                await bot.send_message(worker_id, f"❌ Заявка #{order_id} была отменена клиентом")
            except:
                pass

    @dp.callback_query(F.data.startswith("client_paid_"))
    async def client_paid(call: types.CallbackQuery):
        parts = call.data.split("_")
        order_id = int(parts[2])
        uid = call.from_user.id
        row = await db.db_fetchone(
            "SELECT worker_id, amount, status, client_message_id, total_usdt, amount_usdt FROM orders WHERE id=$1 AND user_id=$2",
            order_id, uid
        )
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)
        worker_id = row["worker_id"]
        amount = float(row["amount"])
        status = row["status"]
        client_msg_id = row["client_message_id"]
        total_usdt = float(row["total_usdt"]) if row["total_usdt"] else 0.0
        amount_usdt = float(row["amount_usdt"]) if row["amount_usdt"] else 0.0
        if status == "DONE":
            return await call.answer("✅ Заявка уже завершена", show_alert=True)
        result = await db.db_execute("UPDATE orders SET status='DONE' WHERE id=$1 AND status IN ('IN_PROGRESS', 'DISPUTE')", order_id)
        if "UPDATE 0" in result:
            return await call.answer("✅ Заявка уже завершена", show_alert=True)
        try:
            await call.message.delete()
        except:
            pass
        await db.unfreeze_to_worker(uid, worker_id, total_usdt, amount_usdt)
        client_balance_new = await db.get_balance(uid)
        worker_balance = await db.get_balance(worker_id)
        worker_amount = round(amount_usdt + (total_usdt - amount_usdt) * 0.8, 4)

        w_row = await db.db_fetchone("SELECT worker_message_id FROM orders WHERE id=$1", order_id)
        if w_row and w_row["worker_message_id"]:
            try:
                await bot.delete_message(chat_id=worker_id, message_id=w_row["worker_message_id"])
            except:
                pass
        try:
            await bot.edit_message_text(
                chat_id=uid, message_id=client_msg_id,
                text=f"✅ Заявка #{order_id} завершена!\n\n🆔 ID: #{order_id}\n💳 Услуга: Карта под оплату\n"
                     f"💰 Сумма: {amount:.2f} RUB\n💸 Списано: {total_usdt:.4f} USDT\n\n"
                     f"📊 Статус: ✅ Завершена\n💰 Ваш баланс: {client_balance_new:.2f} USDT"
            )
        except Exception as e:
            logger.error(f"[client_paid] edit error: {e}")
        await call.answer("✅ Оплата подтверждена!", show_alert=True)
        try:
            await bot.send_message(
                worker_id,
                f"✅ Заявка #{order_id} завершена!\n\n🆔 <b>ID заявки:</b> #{order_id}\n💳 <b>Услуга:</b> Карта под оплату\n\n"
                f"💎 <b>Зачислено:</b> {worker_amount:.4f} USDT\n💰 <b>Ваш баланс:</b> {worker_balance:.2f} USDT",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"[client_paid] send_message error: {e}")

    @dp.callback_query(
        (
            F.data.startswith("lk_") |
            F.data.startswith("client_") |
            F.data.startswith("cards_") |
            F.data.startswith("card_") |
            F.data.startswith("history_") |
            F.data.startswith("worker_history_") |
            F.data.startswith("active_order_")
        )
        & ~F.data.startswith("client_paid_")
        & ~F.data.startswith("client_card")
        & ~F.data.startswith("client_topup")
        & ~F.data.startswith("send_req_")
        & ~F.data.startswith("worker_confirm_")
        & ~F.data.startswith("worker_apply")
        & ~F.data.startswith("take_")
        & ~F.data.startswith("lk_available")
        & ~F.data.in_({"card_unique_yes", "card_unique_no", "client_support"})
    )
    async def lk_buttons(call: types.CallbackQuery, state: FSMContext):
        uid = call.from_user.id
        chat_id = call.message.chat.id

        try:
            await call.message.delete()
        except:
            pass

        if call.data == "client_become_worker":
            await bot.send_message(
                chat_id,
                "<b>📝 Заявка на роль исполнителя</b>\n"
                "<blockquote>Заполните короткую анкету, чтобы мы могли рассмотреть вас на роль оплатчика.\n"
                "Все ответы отправятся одной заявкой на рассмотрение администрации после финальной проверки.</blockquote>\n"
                "Что важно:\n• можно вернуться к предыдущему вопросу;\n"
                "• можно отменить заполнение в любой момент;\n• перед отправкой будет итоговая сверка.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✍️ Отправить заявку", callback_data="worker_apply")],
                    [InlineKeyboardButton(text="🔙 Домой", callback_data="client_back_menu")]
                ])
            )
            return await call.answer()

        if call.data == "client_back_menu":
            from config import BANNER_FILE_ID
            await bot.send_photo(chat_id, photo=BANNER_FILE_ID, caption=CLIENT_MENU_TEXT, reply_markup=CLIENT_MENU_KEYBOARD, parse_mode="HTML")
            return await call.answer()

        if call.data == "client_profile":
            username = f"@{call.from_user.username}" if call.from_user.username else "нет username"
            balance = await db.get_balance(uid)
            frozen = await db.get_frozen(uid)
            row = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE user_id=$1 AND status='DONE'", uid)
            closed = row["count"] if row else 0
            row = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE user_id=$1 AND status='IN_PROGRESS'", uid)
            active = row["count"] if row else 0
            row = await db.db_fetchone("SELECT COUNT(*) FROM invoices WHERE user_id=$1 AND status='paid'", uid)
            paid_count = row["count"] if row else 0
            text = (
                f"<b>👤 Личный профиль</b>\n<blockquote>{username} [{uid}]</blockquote>\n\n"
                f"<b>💼 Финансы</b>\n• Баланс: <b>{balance:.2f} USDT</b>\n• Заморожено: <b>{frozen:.2f} USDT</b>\n\n"
                f"<b>📊 Статистика</b>\n• Закрыто заявок: {closed} шт\n• Активных заявок: {active} шт\n• Успешных пополнений: {paid_count} шт"
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data="client_ref")],
                [InlineKeyboardButton(text="📚 История", callback_data="client_history")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")]
            ])
            await bot.send_photo(chat_id, photo=PROFILE_BANNER_FILE_ID, caption=text, reply_markup=keyboard, parse_mode="HTML")
            return await call.answer()

        if call.data == "client_ref":
            ref_link = f"https://t.me/{(await bot.get_me()).username}?start={uid}"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад в профиль", callback_data="client_profile")]])
            await bot.send_message(chat_id, f"🔗 <b>Ваша реферальная ссылка:</b>\n<code>{ref_link}</code>", parse_mode="HTML", reply_markup=keyboard)
            return await call.answer()

        if call.data == "client_support":
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")]])
            await bot.send_message(chat_id, "🆘 <b>Поддержка сервиса</b>\n\nПо всем вопросам обращайтесь к администратору: @usudhsuhd", parse_mode="HTML", reply_markup=keyboard)
            return await call.answer()

        if call.data == "lk_cards":
            cards = await db.db_fetchall("SELECT id, card_number, expiry FROM cards WHERE worker_id=$1", uid)
            card_buttons = []
            for card in cards:
                masked = f"{card['card_number'][:6]}{'*'*6}{card['card_number'][-4:]} · {card['expiry']}"
                card_buttons.append([InlineKeyboardButton(text=f"💳 {masked}", callback_data=f"card_view_{card['id']}")])
            card_buttons.append([InlineKeyboardButton(text="➕ Добавить карту", callback_data="cards_add")])
            card_buttons.append([InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")])
            await bot.send_message(chat_id, f"💳 Управление картами\n\nВыберите карту или добавьте новую.\n\n💼 Сохранено карт: {len(cards)}", reply_markup=InlineKeyboardMarkup(inline_keyboard=card_buttons))
            return await call.answer()

        if call.data == "cards_add":
            await state.set_state(WorkerRegStates.waiting_for_card_data)
            await bot.send_message(chat_id, "➕ Добавление карты\n\nОтправьте данные карты в любом удобном виде.\nБот сам найдет номер, срок и CVV.")
            return await call.answer()

        if call.data == "lk_home":
            username = f"@{call.from_user.username}" if call.from_user.username else "нет username"
            balance = await db.get_balance(uid)
            row = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE worker_id=$1 AND status='DONE'", uid)
            done_count = row["count"] if row else 0
            row = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE worker_id=$1 AND status='IN_PROGRESS'", uid)
            active_count = row["count"] if row else 0
            text = (
                f"🛠 <b>Профиль работника</b>\n"
                f"Аккаунт: {username}\n\n"
                f"💼 <b>Финансы</b>\n"
                f"• Доступно: <b>{balance:.2f} USDT</b>\n\n"
                f"📊 <b>Статистика</b>\n"
                f"• Выполнено: {done_count} шт\n"
                f"• В работе: {active_count} шт"
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💸 Вывод средств", callback_data="lk_withdraw")],
                [InlineKeyboardButton(text="🟢 Активные заявки", callback_data="lk_active"),
                 InlineKeyboardButton(text="📚 История заявок", callback_data="lk_history")],
                [InlineKeyboardButton(text="💳 Управление картами", callback_data="lk_cards")]
            ])
            await bot.send_photo(chat_id, photo=PROFILE_BANNER_FILE_ID, caption=text, reply_markup=keyboard, parse_mode="HTML")
            return await call.answer()

        if call.data.startswith("card_view_"):
            card_id = int(call.data.split("_")[2])
            row = await db.db_fetchone("SELECT card_number, expiry, cvv, bank, created_at FROM cards WHERE id=$1 AND worker_id=$2", card_id, uid)
            if not row:
                return await call.answer("❌ Карта не найдена", show_alert=True)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🗑 Удалить карту", callback_data=f"card_delete_{card_id}")],
                [InlineKeyboardButton(text="◀️ К списку карт", callback_data="lk_cards")],
                [InlineKeyboardButton(text="🏠 В кабинет", callback_data="lk_home")]
            ])
            await bot.send_message(chat_id, f"💳 Карточка карты\n\n💳 Номер: {row['card_number']}\n📅 Срок: {row['expiry']}\n🔐 Код: {row['cvv']}\n🏦 Банк: {row['bank']}\n🕒 Добавлена: {row['created_at']}", reply_markup=keyboard)
            return await call.answer()

        if call.data.startswith("card_delete_"):
            card_id = int(call.data.split("_")[2])
            await db.db_execute("DELETE FROM cards WHERE id=$1 AND worker_id=$2", card_id, uid)
            await call.answer("✅ Карта удалена", show_alert=True)
            cards = await db.db_fetchall("SELECT id, card_number, expiry FROM cards WHERE worker_id=$1", uid)
            card_buttons = []
            for card in cards:
                masked = f"{card['card_number'][:6]}{'*'*6}{card['card_number'][-4:]} · {card['expiry']}"
                card_buttons.append([InlineKeyboardButton(text=f"💳 {masked}", callback_data=f"card_view_{card['id']}")])
            card_buttons.append([InlineKeyboardButton(text="➕ Добавить карту", callback_data="cards_add")])
            card_buttons.append([InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")])
            await bot.send_message(chat_id, f"💳 Управление картами\n\nСохранено карт: {len(cards)}", reply_markup=InlineKeyboardMarkup(inline_keyboard=card_buttons))
            return await call.answer()

        if call.data == "lk_active":
            orders = await db.db_fetchall(
                "SELECT id, amount, total_usdt FROM orders WHERE worker_id=$1 AND status='IN_PROGRESS' ORDER BY id DESC", uid
            )
            if not orders:
                await bot.send_message(chat_id, "🟢 Активных заявок нет", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
                ]))
                return await call.answer()
            buttons = []
            for order in orders:
                total_usdt = float(order["total_usdt"]) if order["total_usdt"] else 0
                buttons.append([InlineKeyboardButton(
                    text=f"🟢 #{order['id']} — {float(order['amount']):.0f} RUB • {total_usdt:.4f} USDT",
                    callback_data=f"active_order_{order['id']}"
                )])
            buttons.append([InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")])
            await bot.send_message(
                chat_id, "🟢 <b>Активные заявки</b>\n\nВыберите заявку для управления:",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
            return await call.answer()

        if call.data.startswith("active_order_"):
            order_id = int(call.data.split("_")[2])
            order = await db.db_fetchone("SELECT id, amount, total_usdt FROM orders WHERE id=$1 AND worker_id=$2", order_id, uid)
            if not order:
                return await call.answer("❌ Заявка не найдена", show_alert=True)
            total_usdt = float(order["total_usdt"]) if order["total_usdt"] else 0
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Отправить реквизиты", callback_data=f"send_req_{order_id}")],
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"worker_dispute_{order_id}")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="lk_active")]
            ])
            await bot.send_message(
                chat_id,
                f"🟢 <b>Заявка #{order_id}</b>\n\n💰 Сумма: {float(order['amount']):.2f} RUB\n💎 К получению: {total_usdt:.4f} USDT",
                parse_mode="HTML", reply_markup=keyboard
            )
            return await call.answer()

        if call.data == "lk_history":
            done_orders = await db.db_fetchall(
                "SELECT id, amount, total_usdt, status FROM orders WHERE worker_id=$1 AND status IN ('DONE', 'CANCELLED') ORDER BY id DESC LIMIT 20", uid
            )
            if not done_orders:
                await bot.send_message(chat_id, "📚 История заявок пуста")
                return await call.answer()
            buttons = []
            for order in done_orders:
                total_usdt = float(order["total_usdt"]) if order["total_usdt"] else 0
                icon = "✅" if order["status"] == "DONE" else "❌"
                buttons.append([InlineKeyboardButton(
                    text=f"{icon} #{order['id']} — {float(order['amount']):.0f} RUB → {total_usdt:.2f} USDT",
                    callback_data=f"worker_history_order_{order['id']}"
                )])
            buttons.append([InlineKeyboardButton(text="🏠 В кабинет", callback_data="lk_home")])
            await bot.send_photo(
                chat_id, photo=PROFILE_BANNER_FILE_ID,
                caption="<b>📚 История воркера</b>\n\n<blockquote>Выберите запись из истории, чтобы открыть подробную карточку.</blockquote>",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
            return await call.answer()

        if call.data.startswith("worker_history_order_"):
            order_id = int(call.data.split("_")[3])
            row = await db.db_fetchone("SELECT id, amount, total_usdt, status FROM orders WHERE id=$1 AND worker_id=$2", order_id, uid)
            if not row:
                return await call.answer("❌ Заявка не найдена", show_alert=True)
            total_usdt = float(row["total_usdt"]) if row["total_usdt"] else 0
            status_text = "✅ Завершена" if row["status"] == "DONE" else "❌ Отменена"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="lk_history")]])
            await bot.send_message(
                chat_id,
                f"<b>📋 Заявка #{row['id']}</b>\n\n💳 Услуга: Карта под оплату\n"
                f"💰 Сумма: {float(row['amount']):.2f} RUB\n💎 Зачислено: {total_usdt:.2f} USDT\n📊 Статус: {status_text}",
                parse_mode="HTML", reply_markup=keyboard
            )
            return await call.answer()

        if call.data == "client_history":
            active_orders = await db.db_fetchall(
                "SELECT id, amount, total_usdt, status FROM orders WHERE user_id=$1 AND status IN ('NEW', 'IN_PROGRESS') ORDER BY id DESC", uid
            )
            done_orders = await db.db_fetchall(
                "SELECT id, amount, total_usdt, status FROM orders WHERE user_id=$1 AND status IN ('DONE', 'CANCELLED') ORDER BY id DESC LIMIT 20", uid
            )
            if not active_orders and not done_orders:
                await bot.send_message(chat_id, "📚 История заявок пуста")
                return await call.answer()
            buttons = []
            for order in active_orders:
                status_icon = "🟡" if order["status"] == "NEW" else "🟢"
                status_name = "Новая" if order["status"] == "NEW" else "В работе"
                buttons.append([InlineKeyboardButton(
                    text=f"{status_icon} #{order['id']} — {float(order['amount']):.0f} RUB ({status_name})",
                    callback_data=f"history_order_{order['id']}"
                )])
            for order in done_orders:
                total_usdt = float(order["total_usdt"]) if order["total_usdt"] else 0
                icon = "✅" if order["status"] == "DONE" else "❌"
                buttons.append([InlineKeyboardButton(
                    text=f"{icon} #{order['id']} — {float(order['amount']):.0f} RUB → {total_usdt:.2f} USDT",
                    callback_data=f"history_order_{order['id']}"
                )])
            buttons.append([InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")])
            await bot.send_photo(
                chat_id, photo=PROFILE_BANNER_FILE_ID,
                caption="<b>📚 История клиента</b>\n\n<blockquote>Выберите запись из истории, чтобы открыть подробную карточку.</blockquote>",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
            return await call.answer()

        if call.data.startswith("history_order_"):
            order_id = int(call.data.split("_")[2])
            row = await db.db_fetchone("SELECT id, amount, total_usdt, status FROM orders WHERE id=$1 AND user_id=$2", order_id, uid)
            if not row:
                return await call.answer("❌ Заявка не найдена", show_alert=True)
            total_usdt = float(row["total_usdt"]) if row["total_usdt"] else 0
            status = row["status"]
            if status == "DONE": status_text = "✅ Завершена"
            elif status == "IN_PROGRESS": status_text = "🟢 В работе"
            elif status == "CANCELLED": status_text = "❌ Отменена"
            else: status_text = "🟡 Новая"
            buttons = [[InlineKeyboardButton(text="◀️ Назад", callback_data="client_history")]]
            if status == "NEW":
                buttons.insert(0, [InlineKeyboardButton(text="❌ Отменить заявку", callback_data=f"cancel_order_{row['id']}")])
            elif status == "IN_PROGRESS":
                buttons.insert(0, [InlineKeyboardButton(text="🆘 Спор", callback_data=f"dispute_{row['id']}")])
                buttons.insert(0, [InlineKeyboardButton(text="❌ Отменить заявку", callback_data=f"cancel_order_{row['id']}")])
            await bot.send_message(
                chat_id,
                f"<b>📋 Заявка #{row['id']}</b>\n\n💳 Услуга: Карта под оплату\n"
                f"💰 Сумма: {float(row['amount']):.2f} RUB\n💸 Списано: {total_usdt:.2f} USDT\n📊 Статус: {status_text}",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
            return await call.answer()

        await call.answer("🚧 Раздел в разработке", show_alert=True)
