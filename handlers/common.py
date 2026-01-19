"""
Common handlers - /start, /help, cancel.
"""

from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from database import async_session
from services.user_service import UserService
from services.question_service import QuestionService
from templates.messages import Messages

common_router = Router()


@common_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Handle /start command"""
    # Clear any existing state
    await state.clear()

    # Register user
    async with async_session() as session:
        user = await UserService.get_or_create_user(session, message.from_user)

        # Check if banned
        if user.is_banned:
            await message.answer(Messages.ERROR_BANNED)
            return

    # Check if admin - show admin panel directly
    if message.from_user.id in config.ADMIN_IDS:
        from handlers.admin import show_admin_panel
        await show_admin_panel(message, state)
        return

    # Show welcome message with buttons for regular users
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="❓ Задать вопрос", callback_data="ask_question")
    keyboard.button(text="📋 Мои вопросы", callback_data="my_questions")
    keyboard.adjust(1)

    await message.answer(
        Messages.WELCOME,
        reply_markup=keyboard.as_markup()
    )


@common_router.message(Command("help"))
async def cmd_help(message: Message):
    """Handle /help command"""
    help_text = """📖 Помощь по боту

Команды:
/start - Начать
/ask - Задать вопрос
/my - Мои вопросы
/help - Эта справка

Как пользоваться:
1. Нажмите «Задать вопрос»
2. Напишите ваш вопрос
3. Просмотрите похожие ответы (если найдены)
4. Если не нашли ответ - отправьте вопрос
5. Ожидайте ответа (до 1 недели)

По вопросам работы бота обращайтесь к администратору."""

    await message.answer(help_text)


@common_router.callback_query(F.data == "cancel")
async def callback_cancel(callback: CallbackQuery, state: FSMContext):
    """Handle cancel callback - show menu with options"""
    await state.clear()

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="❓ Задать вопрос", callback_data="ask_question")
    keyboard.button(text="📋 Мои вопросы", callback_data="my_questions")
    keyboard.adjust(1)

    await callback.message.edit_text(
        Messages.QUESTION_CANCELLED,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


@common_router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery, state: FSMContext):
    """Return to main menu"""
    await state.clear()

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="❓ Задать вопрос", callback_data="ask_question")
    keyboard.button(text="📋 Мои вопросы", callback_data="my_questions")
    keyboard.adjust(1)

    await callback.message.edit_text(
        Messages.WELCOME,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()
