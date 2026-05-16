import logging
from aiogram import types, F, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

import db
from handlers.common import WorkerRegStates # Убедись, что импорт корректен

logger = logging.getLogger(__name__)

def register_apply(dp, bot: Bot):

    # --- ТВОИ ПРЕДЫДУЩИЕ ХЕНДЛЕРЫ (Шаги 1-5) ОСТАЮТСЯ ТЕМИ ЖЕ ---
    # ... (код регистрации, выбора опыта, банков, направлений и чатов) ...

    # Шаг 6: Дополнительная информация (Вход в состояние)
    # Заменяет твою старую заглушку apply_q5_next
    @dp.callback_query(F.data == "apply_q5_next")
    async def apply_q6_start(call: types.CallbackQuery, state: FSMContext):
        # Устанавливаем состояние ожидания текстового ввода
        await state.set_state(WorkerRegStates.waiting_for_extra_info)
        
        # Дизайн 1-в-1 по твоему запросу
        text = (
            "<b>6. Дополнительная информация</b>\n"
            "<blockquote>Напишите всё, что может помочь при рассмотрении анкеты.</blockquote>"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏪ Назад", callback_data="apply_q6_back")],
            [InlineKeyboardButton(text="🛑 Отмена", callback_data="client_back_menu")]
        ])

        try:
            await call.message.delete()
        except:
            pass

        await bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=kb)
        await call.answer()

    # Шаг 6: Прием сообщения и сохранение в FSM
    @dp.message(WorkerRegStates.waiting_for_extra_info)
    async def apply_q6_text_handler(message: types.Message, state: FSMContext):
        # Сохраняем текст
        await state.update_data(extra_info=message.text)
        
        # Временное подтверждение для теста
        await message.answer(
            "✅ <b>Информация сохранена!</b>\n\n"
            "Делай деплой. Если текст принимается — в следующем обновлении выведем финальную анкету.",
            parse_mode="HTML"
        )

    # Шаг 6 (Назад): Возврат к чатам
    @dp.callback_query(F.data == "apply_q6_back")
    async def apply_q6_back(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(None) # Сбрасываем ожидание текста
        
        # Возвращаемся к функции отрисовки Шага 5 (Чаты)
        # В твоем коде это функция apply_q4_next
        try:
            await apply_q4_next(call, state)
        except Exception as e:
            logger.error(f"Error returning to step 5: {e}")
        await call.answer()

    # --- ОСТАЛЬНЫЕ ФУНКЦИИ (register_apply и т.д.) ---
