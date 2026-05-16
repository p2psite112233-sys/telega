import logging
from aiogram import types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

logger = logging.getLogger(__name__)

# =====================================================================
# 1. ВСЕ СОСТОЯНИЯ FSM (FINITE STATE MACHINE)
# =====================================================================

class ClientOrderStates(StatesGroup):
    """Состояния FSM для создания заявок клиентом (Карта под оплату, СБП, телефон, QR)"""
    waiting_for_amount = State()      # Ожидание ввода суммы в RUB
    waiting_for_unique = State()      # Ожидание выбора: уникальная карта или нет
    waiting_for_phone = State()       # Ожидание ввода номера телефона (для пополнения)
    waiting_for_qr = State()          # Ожидание загрузки фото/файла QR-кода
    waiting_for_invoice = State()     # Ожидание оплаты инвойса клиентом (USDT)


class ClientTopupStates(StatesGroup):
    """Состояния FSM для прямого пополнения баланса клиентом"""
    waiting_for_topup_amount = State() # Ожидание суммы пополнения в USDT


class WorkerWithdrawStates(StatesGroup):
    """Состояния FSM для вывода средств воркером из личного кабинета"""
    waiting_for_withdraw_amount = State() # Ожидание суммы вывода
    waiting_for_withdraw_wallet = State() # Ожидание USDT-адреса (TRC-20)


class WorkerOrderStates(StatesGroup):
    """Состояния FSM для воркера в процессе выполнения взятого заказа"""
    waiting_for_requisites = State()         # Ожидание отправки реквизитов клиенту
    waiting_for_confirm_screenshot = State() # Ожидание скриншота/чека подтверждения оплаты


class WorkerRegStates(StatesGroup):
    """Состояния FSM для анкеты 'Стать исполнителем' и управления картами"""
    # Шаги анкеты
    waiting_for_username_confirm = State()  # Шаг 1: Подтверждение аккаунта
    waiting_for_experience = State()        # Шаг 2: Выбор опыта
    waiting_for_banks = State()             # Шаг 3: Выбор банков
    waiting_for_directions = State()        # Шаг 4: Выбор направлений (чекбоксы)
    waiting_for_chats = State()             # Шаг 5: Выбор активных чатов (чекбоксы)
    
    # Личный кабинет воркера
    waiting_for_card_data = State()         # Добавление реквизитов карты (парсинг текста)


class AdminStates(StatesGroup):
    """Состояния FSM для административной панели (рассылки, ручные балансы)"""
    waiting_for_broadcast_text = State()   # Текст для массовой рассылки
    waiting_for_user_id_balance = State()  # ID пользователя для изменения баланса
    waiting_for_balance_amount = State()   # Сумма для начисления/списания


# =====================================================================
# 2. ГЛОБАЛЬНЫЕ ХЭНДЛЕРЫ ОТМЕНЫ (ДЛЯ ВСЕХ СОСТОЯНИЙ)
# =====================================================================

def register_common(dp):
    """
    Регистрация базовых хэндлеров, которые должны работать 
    в любой момент времени, независимо от текущего стейта.
    """

    # Сброс по текстовой команде /cancel
    @dp.message(F.text.casefold() == "/cancel")
    async def cmd_cancel(message: types.Message, state: FSMContext):
        current_state = await state.get_state()
        if current_state is None:
            return await message.reply("❌ У вас нет активных действий для отмены.")

        logger.info(f"Пользователь {message.from_user.id} прервал стейт: {current_state}")
        await state.clear()
        await message.reply(
            "❌ <b>Действие отменено.</b>\nВоспользуйтесь меню бота для продолжения работы.",
            parse_mode="HTML"
        )

    # Сброс по инлайн-кнопке отмены, если она используется глобально
    @dp.callback_query(F.data == "global_cancel")
    async def cb_cancel(call: types.CallbackQuery, state: FSMContext):
        current_state = await state.get_state()
        if current_state is not None:
            logger.info(f"Пользователь {call.from_user.id} прервал стейт через callback: {current_state}")
            await state.clear()
        
        try:
            await call.message.delete()
        except:
            pass
            
        await call.message.answer("❌ Действие успешно отменено.")
        return await call.answer()
