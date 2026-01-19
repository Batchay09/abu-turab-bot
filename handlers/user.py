"""
User handlers - asking questions, viewing similar answers.
"""

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.callback_data import CallbackData

from config import config
from database import async_session, QuestionStatus
from services.user_service import UserService
from services.question_service import QuestionService
from services.search_engine import search_engine
from states import UserStates
from templates.messages import Messages

user_router = Router()


class SimilarCallback(CallbackData, prefix="similar"):
    """Callback data for similar questions"""
    action: str  # "view", "submit"
    post_id: int = 0


class QuestionCallback(CallbackData, prefix="question"):
    """Callback data for user questions"""
    action: str
    question_id: int = 0


@user_router.message(Command("ask"))
@user_router.callback_query(F.data == "ask_question")
async def start_asking(event: Message | CallbackQuery, state: FSMContext):
    """Start asking a question"""
    # Check if banned
    async with async_session() as session:
        is_banned = await UserService.is_banned(session, event.from_user.id)
        if is_banned:
            text = Messages.ERROR_BANNED
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            else:
                await event.answer(text)
            return

    # Set state
    await state.set_state(UserStates.typing_question)

    # Build keyboard
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="❌ Отмена", callback_data="cancel")

    text = Messages.ASK_QUESTION

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=keyboard.as_markup())
        await event.answer()
    else:
        await event.answer(text, reply_markup=keyboard.as_markup())


@user_router.message(UserStates.typing_question)
async def receive_question(message: Message, state: FSMContext):
    """Receive the user's question and search for similar"""
    question_text = message.text

    # Validate
    if not question_text or len(question_text) < 10:
        await message.answer(Messages.ERROR_QUESTION_TOO_SHORT)
        return

    if len(question_text) > 2000:
        await message.answer(Messages.ERROR_QUESTION_TOO_LONG)
        return

    # Store question
    await state.update_data(pending_question=question_text)

    # Send searching message
    searching_msg = await message.answer("🔍 Ищу похожие вопросы...\n\n⏳ Анализирую базу из 5000+ ответов...")

    # Search for similar
    similar = search_engine.search(
        query=question_text,
        top_k=config.MAX_SIMILAR_RESULTS,
        threshold=config.SIMILARITY_THRESHOLD,
        use_synonyms=True
    )

    if similar:
        # Found similar questions
        await state.set_state(UserStates.reviewing_similar)

        keyboard = InlineKeyboardBuilder()

        for doc, score in similar:
            # Short preview of the question
            preview = doc["question_text"][:40]
            if len(doc["question_text"]) > 40:
                preview += "..."
            keyboard.button(
                text=f"📝 №{doc['post_number']}: {preview}",
                callback_data=SimilarCallback(action="view", post_id=doc["post_id"]).pack()
            )

        keyboard.button(
            text="❌ Не нашёл ответ - Отправить вопрос",
            callback_data=SimilarCallback(action="submit").pack()
        )
        keyboard.button(text="🔙 Отмена", callback_data="cancel")
        keyboard.adjust(1)

        await searching_msg.edit_text(
            Messages.SIMILAR_FOUND,
            reply_markup=keyboard.as_markup()
        )
    else:
        # No similar found - go to confirm
        await state.set_state(UserStates.confirming_submit)

        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="✅ Отправить вопрос", callback_data="confirm_submit")
        keyboard.button(text="❌ Отмена", callback_data="cancel")
        keyboard.adjust(1)

        await searching_msg.edit_text(
            Messages.NO_SIMILAR,
            reply_markup=keyboard.as_markup()
        )


@user_router.callback_query(SimilarCallback.filter(F.action == "view"))
async def view_similar(callback: CallbackQuery, callback_data: SimilarCallback, state: FSMContext):
    """View a similar Q&A"""
    # Ensure we stay in reviewing_similar state
    current_state = await state.get_state()
    if current_state != UserStates.reviewing_similar:
        await state.set_state(UserStates.reviewing_similar)

    post_id = callback_data.post_id

    # Find document in search engine
    doc = None
    for d in search_engine.documents:
        if d.get("post_id") == post_id:
            doc = d
            break

    if not doc:
        await callback.answer("Ответ не найден", show_alert=True)
        return

    # Format answer preview
    answer_preview = doc["answer_text"]
    if len(answer_preview) > 500:
        answer_preview = answer_preview[:500] + "..."

    text = f"""📝 Вопрос №{doc['post_number']}

❓ Вопрос:
{doc['question_text']}

✅ Ответ:
{answer_preview}"""

    keyboard = InlineKeyboardBuilder()

    # Link to channel post
    if doc.get("message_id"):
        post_url = f"https://t.me/{config.CHANNEL_USERNAME}/{doc['message_id']}"
        keyboard.button(text="📢 Открыть на канале", url=post_url)

    keyboard.button(
        text="✅ Ответ найден",
        callback_data="cancel"
    )
    keyboard.button(
        text="🔙 Назад к списку",
        callback_data="back_to_similar"
    )
    keyboard.button(
        text="❌ Не то - Отправить вопрос",
        callback_data=SimilarCallback(action="submit").pack()
    )
    keyboard.adjust(1)

    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())
    await callback.answer()


@user_router.callback_query(F.data == "back_to_similar")
async def back_to_similar(callback: CallbackQuery, state: FSMContext):
    """Go back to similar questions list"""
    data = await state.get_data()
    question_text = data.get("pending_question", "")

    if not question_text:
        # Session expired - show menu instead of error
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="❓ Задать вопрос", callback_data="ask_question")
        keyboard.button(text="📋 Мои вопросы", callback_data="my_questions")
        keyboard.adjust(1)

        await callback.message.edit_text(
            "⏰ Сессия истекла. Начните заново.",
            reply_markup=keyboard.as_markup()
        )
        await callback.answer()
        await state.clear()
        return

    # Ensure state is set
    await state.set_state(UserStates.reviewing_similar)

    # Search again
    similar = search_engine.search(
        query=question_text,
        top_k=config.MAX_SIMILAR_RESULTS,
        threshold=config.SIMILARITY_THRESHOLD,
        use_synonyms=True
    )

    keyboard = InlineKeyboardBuilder()

    for doc, score in similar:
        # Short preview of the question
        preview = doc["question_text"][:40]
        if len(doc["question_text"]) > 40:
            preview += "..."
        keyboard.button(
            text=f"📝 №{doc['post_number']}: {preview}",
            callback_data=SimilarCallback(action="view", post_id=doc["post_id"]).pack()
        )

    keyboard.button(
        text="❌ Не нашёл ответ - Отправить вопрос",
        callback_data=SimilarCallback(action="submit").pack()
    )
    keyboard.button(text="🔙 Отмена", callback_data="cancel")
    keyboard.adjust(1)

    await callback.message.edit_text(
        Messages.SIMILAR_FOUND,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


@user_router.callback_query(SimilarCallback.filter(F.action == "submit"))
@user_router.callback_query(F.data == "confirm_submit")
async def submit_question(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Submit the question to the queue"""
    data = await state.get_data()
    question_text = data.get("pending_question")

    if not question_text:
        await callback.answer("Сессия истекла. Начните заново.", show_alert=True)
        await state.clear()
        return

    # Submit to database
    async with async_session() as session:
        # Ensure user exists
        await UserService.get_or_create_user(session, callback.from_user)

        # Create question
        question = await QuestionService.submit_question(
            session=session,
            user_id=callback.from_user.id,
            question_text=question_text
        )

    # Notify admins about new question
    username = f"@{callback.from_user.username}" if callback.from_user.username else "Без юзернейма"
    preview = question_text[:100] + "..." if len(question_text) > 100 else question_text

    admin_notification = (
        f"📥 Новый вопрос #{question.id}\n\n"
        f"👤 От: {username}\n"
        f"❓ {preview}\n\n"
        f"Используйте /admin для просмотра"
    )

    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(chat_id=admin_id, text=admin_notification)
        except Exception:
            pass  # Admin may have blocked the bot

    # Clear state
    await state.clear()

    # Show confirmation
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📋 Мои вопросы", callback_data="my_questions")
    keyboard.button(text="🏠 Главное меню", callback_data="main_menu")
    keyboard.adjust(1)

    await callback.message.edit_text(
        Messages.QUESTION_SUBMITTED.format(question_id=question.id),
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


class MyQuestionsCallback(CallbackData, prefix="myq"):
    """Callback data for my questions navigation"""
    action: str  # "folder", "view"
    folder: str = ""  # "pending", "answered", "all"
    question_id: int = 0


@user_router.message(Command("my"))
@user_router.callback_query(F.data == "my_questions")
async def my_questions(event: Message | CallbackQuery, state: FSMContext):
    """Show user's questions - main menu with folders"""
    async with async_session() as session:
        questions = await QuestionService.get_user_questions(
            session=session,
            user_id=event.from_user.id,
            limit=50  # Get more for counting
        )

    if not questions:
        text = Messages.NO_QUESTIONS
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="❓ Задать вопрос", callback_data="ask_question")
        keyboard.button(text="🏠 Главное меню", callback_data="main_menu")
        keyboard.adjust(1)
    else:
        # Count by status
        pending_count = sum(1 for q in questions if q.status in [QuestionStatus.PENDING, QuestionStatus.IN_PROGRESS])
        answered_count = sum(1 for q in questions if q.status in [QuestionStatus.ANSWERED_PUBLIC, QuestionStatus.ANSWERED_PRIVATE])
        rejected_count = sum(1 for q in questions if q.status == QuestionStatus.REJECTED)

        text = f"""📋 Мои вопросы

Всего вопросов: {len(questions)}

Выберите папку:"""

        keyboard = InlineKeyboardBuilder()

        if pending_count > 0:
            keyboard.button(
                text=f"⏳ Ожидают ответа ({pending_count})",
                callback_data=MyQuestionsCallback(action="folder", folder="pending").pack()
            )
        if answered_count > 0:
            keyboard.button(
                text=f"✅ Отвеченные ({answered_count})",
                callback_data=MyQuestionsCallback(action="folder", folder="answered").pack()
            )
        if rejected_count > 0:
            keyboard.button(
                text=f"❌ Отклонённые ({rejected_count})",
                callback_data=MyQuestionsCallback(action="folder", folder="rejected").pack()
            )

        keyboard.button(
            text=f"📁 Все вопросы ({len(questions)})",
            callback_data=MyQuestionsCallback(action="folder", folder="all").pack()
        )
        keyboard.button(text="❓ Задать новый вопрос", callback_data="ask_question")
        keyboard.button(text="🏠 Главное меню", callback_data="main_menu")
        keyboard.adjust(1)

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=keyboard.as_markup())
        await event.answer()
    else:
        await event.answer(text, reply_markup=keyboard.as_markup())


@user_router.callback_query(MyQuestionsCallback.filter(F.action == "folder"))
async def my_questions_folder(callback: CallbackQuery, callback_data: MyQuestionsCallback):
    """Show questions in a specific folder"""
    folder = callback_data.folder

    async with async_session() as session:
        questions = await QuestionService.get_user_questions(
            session=session,
            user_id=callback.from_user.id,
            limit=50
        )

    # Filter by folder
    if folder == "pending":
        filtered = [q for q in questions if q.status in [QuestionStatus.PENDING, QuestionStatus.IN_PROGRESS]]
        folder_name = "⏳ Ожидают ответа"
    elif folder == "answered":
        filtered = [q for q in questions if q.status in [QuestionStatus.ANSWERED_PUBLIC, QuestionStatus.ANSWERED_PRIVATE]]
        folder_name = "✅ Отвеченные"
    elif folder == "rejected":
        filtered = [q for q in questions if q.status == QuestionStatus.REJECTED]
        folder_name = "❌ Отклонённые"
    else:
        filtered = questions
        folder_name = "📁 Все вопросы"

    if not filtered:
        text = f"{folder_name}\n\nВ этой папке пока пусто."
    else:
        status_emoji = {
            QuestionStatus.PENDING: "⏳",
            QuestionStatus.IN_PROGRESS: "✍️",
            QuestionStatus.ANSWERED_PUBLIC: "✅",
            QuestionStatus.ANSWERED_PRIVATE: "✅",
            QuestionStatus.REJECTED: "❌",
        }

        lines = []
        for q in filtered[:10]:  # Show max 10
            emoji = status_emoji.get(q.status, "❓")
            preview = q.question_text[:30]
            if len(q.question_text) > 30:
                preview += "..."
            lines.append(f"{emoji} #{q.id}: {preview}")

        if len(filtered) > 10:
            lines.append(f"\n... и ещё {len(filtered) - 10}")

        text = f"""{folder_name}

{chr(10).join(lines)}"""

    keyboard = InlineKeyboardBuilder()

    # Add buttons to view individual questions (for answered ones)
    if folder == "answered":
        for q in filtered[:5]:  # Max 5 view buttons
            preview = q.question_text[:20]
            if len(q.question_text) > 20:
                preview += "..."
            keyboard.button(
                text=f"👁️ #{q.id}: {preview}",
                callback_data=MyQuestionsCallback(action="view", question_id=q.id).pack()
            )

    keyboard.button(text="🔙 Назад к папкам", callback_data="my_questions")
    keyboard.button(text="❓ Задать вопрос", callback_data="ask_question")
    keyboard.adjust(1)

    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())
    await callback.answer()


@user_router.callback_query(MyQuestionsCallback.filter(F.action == "view"))
async def view_my_question(callback: CallbackQuery, callback_data: MyQuestionsCallback):
    """View a specific answered question"""
    question_id = callback_data.question_id

    async with async_session() as session:
        question = await QuestionService.get_question(session, question_id)

    if not question or question.user_id != callback.from_user.id:
        await callback.answer("Вопрос не найден", show_alert=True)
        return

    # Format question details
    status_text = {
        QuestionStatus.PENDING: "⏳ Ожидает ответа",
        QuestionStatus.IN_PROGRESS: "✍️ В работе",
        QuestionStatus.ANSWERED_PUBLIC: "✅ Отвечен (публично)",
        QuestionStatus.ANSWERED_PRIVATE: "✅ Отвечен (приватно)",
        QuestionStatus.REJECTED: "❌ Отклонён",
    }

    text = f"""📝 Вопрос #{question.id}

📊 Статус: {status_text.get(question.status, "❓")}
📅 Дата: {question.created_at.strftime("%d.%m.%Y")}

❓ Вопрос:
{question.question_text}"""

    if question.answer_text:
        answer_preview = question.answer_text
        if len(answer_preview) > 800:
            answer_preview = answer_preview[:800] + "..."
        text += f"""

✅ Ответ:
{answer_preview}"""

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔙 Назад к папкам", callback_data="my_questions")
    keyboard.button(text="❓ Задать новый вопрос", callback_data="ask_question")
    keyboard.adjust(1)

    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())
    await callback.answer()
