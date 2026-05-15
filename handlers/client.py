from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import db
from utils.crypto import crypto_get_rate
from handlers.common import waiting, waiting_topup, waiting_card


CLIENT_MENU_TEXT = (
    "🏠 Главное меню клиента\n\n"
    "Бот поможет получить карту под оплату, перевести деньги на карту/СБП, "
    "пополнить номер телефона или оплатить готовый QR-код.\n"
    "Все этапы заявки фиксируются внутри сервиса.\n\n"
    "💼 Комиссия сервиса: 20.00% от суммы заявки, но не меньше 30 RUB\n"
    "🆕 Уникальная карта: дополнительно +5%\n"
    "🔳 QR-оплата: скидка по комиссии -8.00%\n"
    "⚡️ Наши работники готовы обрабатывать заявки 24/7"
)

CLIENT_MENU_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="💳 Карта под оплату", callback_data="client_card"),
        InlineKeyboardButton(text="🏦 Перевод на карту", callback_data="client_transfer")
    ],
    [
        InlineKeyboardButton(text="📳 Пополнить номер телефона через банк", callback_data="client_phone"),
        InlineKeyboardButton(text="◾️ Оплата QR-Кода", callback_data="client_qr")
    ],
    [InlineKeyboardButton(text="🤑 Пополнить баланс", callback_data="client_topup")],
    [
        InlineKeyboardButton(text="🙋‍♂️ Профиль", callback_data="client_profile"),
        InlineKeyboardButton(text="📄 Стать исполнителем", callback_data="client_become_worker")
    ],
    [InlineKeyboardButton(text="🆘 Поддержка", callback_data="client_support")]
])


def register_client(dp, bot):

    @dp.callback_query(F.data.startswith("client_paid_"))
    async def client_paid(call: types.CallbackQuery):
        parts = call.data.split("_")
        order_id = int(parts[2])
        total_usdt = float(parts[3])
        uid = call.from_user.id

        row = await db.db_fetchone(
            "SELECT worker_id, amount, status, client_message_id FROM orders WHERE id=$1 AND user_id=$2",
            order_id, uid
        )
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)

        worker_id = row["worker_id"]
        amount = float(row["amount"])
        status = row["status"]
        client_msg_id = row["client_message_id"]

        if status == "DONE":
            return await call.answer("✅ Заявка уже завершена", show_alert=True)

        # Берём total_usdt из заявки (зафиксирован при создании)
        row2 = await db.db_fetchone("SELECT total_usdt FROM orders WHERE id=$1", order_id)
        total_usdt = float(row2["total_usdt"]) if row2 and row2["total_usdt"] else total_usdt

        await db.unfreeze_to_worker(uid, worker_id, total_usdt)
        await db.db_execute("UPDATE orders SET status='DONE' WHERE id=$1", order_id)

        client_balance_new = await db.get_balance(uid)
        worker_balance = await db.get_balance(worker_id)

        try:
            await bot.edit_message_text(
                chat_id=uid,
                message_id=client_msg_id,
                text=f"✅ Заявка #{order_id} завершена!\n\n"
                     f"🆔 ID: #{order_id}\n"
                     f"💳 Услуга: Карта под оплату\n"
                     f"💰 Сумма: {amount:.2f} RUB\n\n"
                     f"📊 Статус: ✅ DONE\n"
                     f"💸 Списано: {total_usdt:.4f} USDT\n"
                     f"💰 Ваш баланс: {client_balance_new:.4f} USDT"
            )
        except:
            pass

        await call.answer("✅ Оплата подтверждена!", show_alert=True)

        try:
            await bot.send_message(
                worker_id,
                f"✅ Заявка #{order_id} завершена!\n\n"
                f"💎 Зачислено: {total_usdt:.4f} USDT\n"
                f"💰 Ваш баланс: {worker_balance:.4f} USDT"
            )
        except:
            pass

    @dp.callback_query(
        (F.data.startswith("lk_") | F.data.startswith("client_") | F.data.startswith("cards_") | F.data.startswith("card_"))
        & ~F.data.startswith("client_paid_")
    )
    async def lk_buttons(call: types.CallbackQuery):
        uid = call.from_user.id

        if call.data == "client_card":
            await call.message.answer_photo(
                photo="AgACAgIAAxkBAAIC92oG8dC8NL-jzOBotlCM2XGM-i86AALcE2sbIOg5SDV64bApD116AQADAgADeQADOwQ",
                caption=(
                    "<b>💳 Карта под оплату</b>\n\n"
                    "<blockquote>Вам нужна уникальная карта?\n"
                    "Уникальная карта — карта которую никто кроме вас не использовал.\n"
                    "Дополнительная комиссия: <b>+5%</b></blockquote>"
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Да (+5%)", callback_data="card_unique_yes"),
                        InlineKeyboardButton(text="❌ Нет", callback_data="card_unique_no")
                    ]
                ])
            )
            return await call.answer()

        if call.data in ("card_unique_yes", "card_unique_no"):
            unique = call.data == "card_unique_yes"
            waiting[uid] = {"unique": unique}
            extra = " (+5% за уникальность)" if unique else ""
            await call.message.edit_caption(
                caption=(
                    f"<b>💳 Карта под оплату</b>\n\n"
                    f"<blockquote>Введите сумму в RUB, на которую нужна карта.\n"
                    f"После подтверждения исполнитель отправит реквизиты для оплаты.</blockquote>\n\n"
                    f"💸 Сумма заявки: в рублях{extra}\nПример: <b>500</b>"
                ),
                parse_mode="HTML",
                reply_markup=None
            )
            return await call.answer()

        if call.data == "client_topup":
            waiting_topup[uid] = True
            await call.message.answer(
                "💳 Пополнение баланса\n\n"
                "Введите сумму пополнения в рублях.\n\n"
                "💸 Сумма пополнения: в рублях"
            )
            return await call.answer()

        if call.data == "client_profile":
            from handlers.common import PROFILE_BANNER_FILE_ID
            username = f"@{call.from_user.username}" if call.from_user.username else "нет username"
            balance = await db.get_balance(uid)
            frozen = await db.get_frozen(uid)
            row = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE user_id=$1 AND status='DONE'", uid)
            closed = row[0] if row else 0
            row = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE user_id=$1 AND status='IN_PROGRESS'", uid)
            active = row[0] if row else 0
            row = await db.db_fetchone("SELECT COUNT(*) FROM invoices WHERE user_id=$1 AND status='paid'", uid)
            paid_count = row[0] if row else 0
            text = (
                f"<b>👤 Личный профиль</b>\n"
                f"<blockquote>{username} [{uid}]</blockquote>\n\n"
                f"<b>💼 Финансы</b>\n"
                f"• Баланс: <b>{balance:.4f} USDT</b>\n"
                f"• Заморожено: <b>{frozen:.4f} USDT</b>\n\n"
                f"<b>📊 Статистика</b>\n"
                f"• Закрыто заявок: {closed} шт\n"
                f"• Активных заявок: {active} шт\n"
                f"• Успешных пополнений: {paid_count} шт"
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data="client_ref")],
                [InlineKeyboardButton(text="📚 История", callback_data="client_history")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")]
            ])
            await call.message.answer_photo(
                photo=PROFILE_BANNER_FILE_ID,
                caption=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return await call.answer()

        if call.data == "client_back_menu":
            await call.message.answer(CLIENT_MENU_TEXT, reply_markup=CLIENT_MENU_KEYBOARD)
            return await call.answer()

        if call.data == "lk_cards":
            cards = await db.db_fetchall("SELECT id, card_number, expiry FROM cards WHERE worker_id=$1", uid)
            card_buttons = []
            for card in cards:
                masked = f"{card['card_number'][:6]}{'*'*6}{card['card_number'][-4:]} · {card['expiry']}"
                card_buttons.append([InlineKeyboardButton(text=f"💳 {masked}", callback_data=f"card_view_{card['id']}")])
            card_buttons.append([InlineKeyboardButton(text="🔎 Поиск", callback_data="cards_search")])
            card_buttons.append([InlineKeyboardButton(text="➕ Добавить карту", callback_data="cards_add")])
            card_buttons.append([InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=card_buttons)
            await call.message.answer(
                f"💳 Управление картами\n\nВыберите карту или добавьте новую.\n\n💼 Сохранено карт: {len(cards)}",
                reply_markup=keyboard
            )
            return await call.answer()

        if call.data == "cards_add":
            waiting_card[uid] = True
            await call.message.answer(
                "➕ Добавление карты\n\nОтправьте данные карты в любом удобном виде.\nБот сам найдет номер, срок и CVV."
            )
            return await call.answer()

        if call.data == "lk_home":
            from handlers.common import get_role
            username = f"@{call.from_user.username}" if call.from_user.username else "нет username"
            balance = await db.get_balance(uid)
            row = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE worker_id=$1 AND status='DONE'", uid)
            done_count = row[0] if row else 0
            row = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE worker_id=$1 AND status='IN_PROGRESS'", uid)
            active_count = row[0] if row else 0
            text = (
                f"🛠 Профиль работника\n"
                f"Ваш профиль: {username} [{uid}]\n\n"
                f"💼 Финансы\n"
                f"• Доступно для вывода: {balance:.4f} USDT\n\n"
                f"📊 Статистика\n"
                f"• Обработано заявок: {done_count} шт\n"
                f"• Активных заявок: {active_count} шт"
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💸 Вывод средств", callback_data="lk_withdraw")],
                [
                    InlineKeyboardButton(text="🟢 Активные заявки", callback_data="lk_active"),
                    InlineKeyboardButton(text="📚 История заявок", callback_data="lk_history")
                ],
                [InlineKeyboardButton(text="💳 Управление картами", callback_data="lk_cards")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="lk_menu")]
            ])
            await call.message.answer(text, reply_markup=keyboard)
            return await call.answer()

        if call.data.startswith("card_view_"):
            card_id = int(call.data.split("_")[2])
            row = await db.db_fetchone(
                "SELECT card_number, expiry, cvv, bank, created_at FROM cards WHERE id=$1 AND worker_id=$2",
                card_id, uid
            )
            if not row:
                return await call.answer("❌ Карта не найдена", show_alert=True)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🗑 Удалить карту", callback_data=f"card_delete_{card_id}")],
                [InlineKeyboardButton(text="◀️ К списку карт", callback_data="lk_cards")],
                [InlineKeyboardButton(text="🏠 В кабинет", callback_data="lk_home")]
            ])
            await call.message.answer(
                f"💳 Карточка карты\n\n"
                f"💳 Номер: {row['card_number']}\n"
                f"📅 Срок: {row['expiry']}\n"
                f"🔐 Код: {row['cvv']}\n"
                f"🏦 Банк: {row['bank']}\n"
                f"🕒 Добавлена: {row['created_at']}",
                reply_markup=keyboard
            )
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
            card_buttons.append([InlineKeyboardButton(text="🔎 Поиск", callback_data="cards_search")])
            card_buttons.append([InlineKeyboardButton(text="➕ Добавить карту", callback_data="cards_add")])
            card_buttons.append([InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=card_buttons)
            await call.message.answer(
                f"💳 Управление картами\n\nСохранено карт: {len(cards)}",
                reply_markup=keyboard
            )
            return

        if call.data == "lk_active":
            orders = await db.db_fetchall(
                "SELECT id, amount, status, total_usdt FROM orders WHERE worker_id=$1 AND status='IN_PROGRESS' ORDER BY id DESC",
                uid
            )
            if not orders:
                await call.message.answer("🟢 Активных заявок нет")
                return await call.answer()
            for order in orders:
                total_usdt = float(order["total_usdt"]) if order["total_usdt"] else 0
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Отправить реквизиты", callback_data=f"send_req_{order['id']}")],
                    [InlineKeyboardButton(text="✅ Оплата прошла", callback_data=f"worker_confirm_{order['id']}")]
                ])
                await call.message.answer(
                    f"🟢 Заявка #{order['id']}\n\n"
                    f"💰 Сумма: {float(order['amount']):.2f} RUB\n"
                    f"💎 К получению: {total_usdt:.4f} USDT\n"
                    f"📊 Статус: {order['status']}",
                    reply_markup=keyboard
                )
            return await call.answer()

        if call.data == "lk_history":
            orders = await db.db_fetchall(
                "SELECT id, amount, total_usdt FROM orders WHERE worker_id=$1 AND status='DONE' ORDER BY id DESC LIMIT 20",
                uid
            )
            if not orders:
                await call.message.answer("📚 История заявок пуста")
                return await call.answer()
            text = "📚 История заявок (последние 20)\n\n"
            for order in orders:
                total_usdt = float(order["total_usdt"]) if order["total_usdt"] else 0
                text += f"✅ #{order['id']} — {float(order['amount']):.2f} RUB → {total_usdt:.4f} USDT\n"
            await call.message.answer(text)
            return await call.answer()

        await call.answer("🚧 Раздел в разработке", show_alert=True)
 