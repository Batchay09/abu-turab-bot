"""
Admin handlers - queue management, answering questions.
"""

from datetime import datetime
from typing import Optional

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
from services.channel_service import ChannelService
from services.tag_service import TagService
from services.tag_suggester import suggest_tags
from services.search_engine import search_engine
from states import AdminStates
from templates.messages import Messages

admin_router = Router()


class AdminQueueCallback(CallbackData, prefix="aq"):
    """Callback data for admin queue"""
    action: str  # "view", "detail", "assign", "page"
    question_id: int = 0
    page: int = 0


class AdminAnswerCallback(CallbackData, prefix="aa"):
    """Callback data for admin answering"""
    action: str  # "answer", "reject", "back"
    question_id: int = 0


class AdminTagCallback(CallbackData, prefix="at"):
    """Callback data for tag selection"""
    action: str  # "toggle", "done", "add_new"
    tag_id: int = 0


class AdminDestCallback(CallbackData, prefix="ad"):
    """Callback data for destination selection"""
    action: str  # "private", "channel"


async def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    async with async_session() as session:
        return await UserService.is_admin(session, user_id)


@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    """Admin panel entry point"""
    if not await is_admin(message.from_user.id):
        await message.answer(Messages.ERROR_NOT_ADMIN)
        return

    await state.clear()
    await show_admin_panel(message, state)


async def show_admin_panel(event: Message | CallbackQuery, state: FSMContext):
    """Show admin panel with stats"""
    async with async_session() as session:
        stats = await QuestionService.get_queue_stats(
            session=session,
            admin_id=event.from_user.id
        )

    text = Messages.ADMIN_PANEL.format(**stats)

    keyboard = InlineKeyboardBuilder()
    keyboard.button(
        text=f"📥 Очередь ({stats['pending']})",
        callback_data=AdminQueueCallback(action="view", page=0).pack()
    )
    keyboard.button(
        text=f"📝 Мои вопросы ({stats['my_assigned']})",
        callback_data=AdminQueueCallback(action="assigned", page=0).pack()
    )
    keyboard.button(
        text="🏷️ Управление тегами",
        callback_data="manage_tags"
    )
    keyboard.adjust(1)

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=keyboard.as_markup())
        await event.answer()
    else:
        await event.answer(text, reply_markup=keyboard.as_markup())


@admin_router.callback_query(F.data == "admin_panel")
async def callback_admin_panel(callback: CallbackQuery, state: FSMContext):
    """Return to admin panel"""
    if not await is_admin(callback.from_user.id):
        await callback.answer(Messages.ERROR_NOT_ADMIN, show_alert=True)
        return

    await state.clear()
    await show_admin_panel(callback, state)


@admin_router.callback_query(AdminQueueCallback.filter(F.action == "view"))
async def view_queue(callback: CallbackQuery, callback_data: AdminQueueCallback, state: FSMContext):
    """View pending questions queue"""
    if not await is_admin(callback.from_user.id):
        await callback.answer(Messages.ERROR_NOT_ADMIN, show_alert=True)
        return

    page = callback_data.page

    async with async_session() as session:
        questions = await QuestionService.get_pending_questions(
            session=session,
            page=page,
            per_page=5
        )

    if not questions:
        await callback.answer("Очередь пуста!", show_alert=True)
        return

    keyboard = InlineKeyboardBuilder()

    for q in questions:
        preview = q.question_text[:40]
        if len(q.question_text) > 40:
            preview += "..."

        keyboard.button(
            text=f"#{q.id}: {preview}",
            callback_data=AdminQueueCallback(action="detail", question_id=q.id).pack()
        )
    keyboard.adjust(1)

    # Pagination
    nav_row = []
    if page > 0:
        nav_row.append(("⬅️", AdminQueueCallback(action="view", page=page - 1).pack()))
    if len(questions) == 5:
        nav_row.append(("➡️", AdminQueueCallback(action="view", page=page + 1).pack()))

    if nav_row:
        for text, data in nav_row:
            keyboard.button(text=text, callback_data=data)
        keyboard.adjust(1, len(nav_row))

    keyboard.button(text="🔙 Назад", callback_data="admin_panel")
    keyboard.adjust(1)

    await callback.message.edit_text(
        f"📥 Очередь вопросов (стр. {page + 1})\n\nВыберите вопрос:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


@admin_router.callback_query(AdminQueueCallback.filter(F.action == "assigned"))
async def view_assigned(callback: CallbackQuery, callback_data: AdminQueueCallback, state: FSMContext):
    """View questions assigned to this admin"""
    if not await is_admin(callback.from_user.id):
        await callback.answer(Messages.ERROR_NOT_ADMIN, show_alert=True)
        return

    page = callback_data.page

    async with async_session() as session:
        questions = await QuestionService.get_assigned_questions(
            session=session,
            admin_id=callback.from_user.id,
            page=page,
            per_page=5
        )

    if not questions:
        await callback.answer("У вас нет назначенных вопросов", show_alert=True)
        return

    keyboard = InlineKeyboardBuilder()

    for q in questions:
        preview = q.question_text[:40]
        if len(q.question_text) > 40:
            preview += "..."

        keyboard.button(
            text=f"#{q.id}: {preview}",
            callback_data=AdminQueueCallback(action="detail", question_id=q.id).pack()
        )
    keyboard.adjust(1)

    keyboard.button(text="🔙 Назад", callback_data="admin_panel")
    keyboard.adjust(1)

    await callback.message.edit_text(
        f"📝 Мои вопросы (стр. {page + 1})\n\nВыберите вопрос:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


@admin_router.callback_query(AdminQueueCallback.filter(F.action == "detail"))
async def view_question_detail(callback: CallbackQuery, callback_data: AdminQueueCallback, state: FSMContext):
    """View question details"""
    if not await is_admin(callback.from_user.id):
        await callback.answer(Messages.ERROR_NOT_ADMIN, show_alert=True)
        return

    question_id = callback_data.question_id

    async with async_session() as session:
        question = await QuestionService.get_question(session, question_id)

    if not question:
        await callback.answer("Вопрос не найден", show_alert=True)
        return

    # Store current question
    await state.update_data(current_question_id=question_id)
    await state.set_state(AdminStates.viewing_question)

    # Format status
    status_names = {
        QuestionStatus.PENDING: "⏳ Ожидает",
        QuestionStatus.IN_PROGRESS: "✍️ В работе",
        QuestionStatus.ANSWERED_PUBLIC: "✅ Отвечен (канал)",
        QuestionStatus.ANSWERED_PRIVATE: "✅ Отвечен (личка)",
        QuestionStatus.REJECTED: "❌ Отклонён",
    }

    # Count user's questions for context
    async with async_session() as session:
        user_questions = await QuestionService.get_user_questions(session, question.user_id, limit=100)
    user_question_count = len(user_questions)

    text = Messages.QUESTION_DETAIL.format(
        question_id=question.id,
        username=f"ID:{question.user_id} ({user_question_count} вопр.)",
        date=question.created_at.strftime("%d.%m.%Y %H:%M"),
        status=status_names.get(question.status, "Неизвестно"),
        question_text=question.question_text
    )

    keyboard = InlineKeyboardBuilder()

    if question.status in [QuestionStatus.PENDING, QuestionStatus.IN_PROGRESS]:
        keyboard.button(
            text="✍️ Ответить",
            callback_data=AdminAnswerCallback(action="answer", question_id=question.id).pack()
        )
        keyboard.button(
            text="❌ Отклонить",
            callback_data=AdminAnswerCallback(action="reject", question_id=question.id).pack()
        )
        keyboard.adjust(2)

    # Button to view user's question history
    if user_question_count > 1:
        keyboard.button(
            text=f"📋 История ({user_question_count})",
            callback_data=AdminQueueCallback(action="user_history", question_id=question.user_id).pack()
        )

    keyboard.button(text="🔙 Назад", callback_data="admin_panel")
    keyboard.adjust(1)

    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())
    await callback.answer()


@admin_router.callback_query(AdminQueueCallback.filter(F.action == "user_history"))
async def view_user_history(callback: CallbackQuery, callback_data: AdminQueueCallback, state: FSMContext):
    """View question history for a specific user"""
    if not await is_admin(callback.from_user.id):
        await callback.answer(Messages.ERROR_NOT_ADMIN, show_alert=True)
        return

    user_id = callback_data.question_id  # Reusing question_id field for user_id

    async with async_session() as session:
        questions = await QuestionService.get_user_questions(session, user_id, limit=20)

    if not questions:
        await callback.answer("История пуста", show_alert=True)
        return

    # Format status icons
    status_icons = {
        QuestionStatus.PENDING: "⏳",
        QuestionStatus.IN_PROGRESS: "✍️",
        QuestionStatus.ANSWERED_PUBLIC: "📢",
        QuestionStatus.ANSWERED_PRIVATE: "✉️",
        QuestionStatus.REJECTED: "❌",
    }

    text = f"📋 История вопросов ID:{user_id}\n\n"

    for q in questions[:10]:  # Show last 10
        icon = status_icons.get(q.status, "❓")
        date = q.created_at.strftime("%d.%m")
        preview = q.question_text[:50].replace("\n", " ")
        if len(q.question_text) > 50:
            preview += "..."
        text += f"{icon} [{date}] {preview}\n\n"

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔙 Назад", callback_data="admin_panel")

    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())
    await callback.answer()


@admin_router.callback_query(AdminAnswerCallback.filter(F.action == "answer"))
async def start_answering(callback: CallbackQuery, callback_data: AdminAnswerCallback, state: FSMContext):
    """Start answering a question"""
    if not await is_admin(callback.from_user.id):
        await callback.answer(Messages.ERROR_NOT_ADMIN, show_alert=True)
        return

    question_id = callback_data.question_id

    async with async_session() as session:
        question = await QuestionService.get_question(session, question_id)

        # Auto-assign if not assigned
        if question and question.status == QuestionStatus.PENDING:
            await QuestionService.assign_to_admin(
                session=session,
                question_id=question_id,
                admin_id=callback.from_user.id
            )

    if not question:
        await callback.answer("Вопрос не найден", show_alert=True)
        return

    await state.update_data(
        answering_question_id=question_id,
        question_text=question.question_text
    )
    await state.set_state(AdminStates.typing_answer)

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="❌ Отмена", callback_data="admin_panel")

    await callback.message.edit_text(
        Messages.TYPE_ANSWER.format(question_text=question.question_text),
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


@admin_router.message(AdminStates.typing_answer)
async def receive_answer(message: Message, state: FSMContext):
    """Receive admin's answer"""
    if not await is_admin(message.from_user.id):
        await message.answer(Messages.ERROR_NOT_ADMIN)
        return

    answer_text = message.text

    if not answer_text or len(answer_text) < 10:
        await message.answer("Ответ слишком короткий")
        return

    # Store answer
    await state.update_data(answer_text=answer_text, selected_tags=[])
    await state.set_state(AdminStates.selecting_tags)

    # Show tag selection
    await show_tag_selection(message, state)


async def show_tag_selection(event: Message | CallbackQuery, state: FSMContext, show_all: bool = False):
    """Show tag selection interface with smart suggestions"""
    data = await state.get_data()
    selected_tags = data.get("selected_tags", [])
    question_text = data.get("question_text", "")

    async with async_session() as session:
        all_tags = await TagService.get_all_tags(session)

    # Get suggested tags based on question content
    suggested_names = suggest_tags(question_text, top_n=3)

    # Build tag_id -> tag mapping
    tag_by_name = {tag.name: tag for tag in all_tags}
    tag_by_id = {tag.id: tag for tag in all_tags}

    # Pre-select suggested tags if nothing selected yet
    if not selected_tags and not show_all:
        for name in suggested_names:
            if name in tag_by_name:
                selected_tags.append(tag_by_name[name].id)
        await state.update_data(selected_tags=selected_tags)

    # Format selected tags
    selected_names = [tag_by_id[tid].name for tid in selected_tags if tid in tag_by_id]
    selected_str = ", ".join(selected_names) if selected_names else "не выбраны"

    keyboard = InlineKeyboardBuilder()

    if show_all:
        # Show all tags in compact grid
        for tag in all_tags:
            prefix = "✅" if tag.id in selected_tags else "⬜"
            keyboard.button(
                text=f"{prefix} {tag.name}",
                callback_data=AdminTagCallback(action="toggle", tag_id=tag.id).pack()
            )
        keyboard.adjust(3)  # 3 columns for compact view
    else:
        # Show suggested tags (pre-selected)
        keyboard.row()
        for name in suggested_names:
            if name in tag_by_name:
                tag = tag_by_name[name]
                prefix = "✅" if tag.id in selected_tags else "⬜"
                keyboard.button(
                    text=f"{prefix} {tag.name}",
                    callback_data=AdminTagCallback(action="toggle", tag_id=tag.id).pack()
                )
        keyboard.adjust(3)

        # Button to show all tags
        keyboard.button(
            text="📋 Все теги...",
            callback_data="show_all_tags"
        )

    keyboard.button(
        text="➕ Новый тег",
        callback_data=AdminTagCallback(action="add_new").pack()
    )
    keyboard.button(
        text="✅ Готово",
        callback_data=AdminTagCallback(action="done").pack()
    )
    keyboard.button(
        text="❌ Отмена",
        callback_data="admin_panel"
    )
    keyboard.adjust(2, 1, 1)

    text = f"🏷️ Теги: {selected_str}\n\n"
    if not show_all:
        text += "Предложенные теги (на основе вопроса):"
    else:
        text += "Все теги:"

    if isinstance(event, Message):
        await event.answer(text, reply_markup=keyboard.as_markup())
    else:
        await event.message.edit_text(text, reply_markup=keyboard.as_markup())
        await event.answer()


@admin_router.callback_query(F.data == "show_all_tags")
async def show_all_tags(callback: CallbackQuery, state: FSMContext):
    """Show all tags for selection"""
    if not await is_admin(callback.from_user.id):
        await callback.answer(Messages.ERROR_NOT_ADMIN, show_alert=True)
        return
    await show_tag_selection(callback, state, show_all=True)


@admin_router.callback_query(AdminTagCallback.filter(F.action == "toggle"))
async def toggle_tag(callback: CallbackQuery, callback_data: AdminTagCallback, state: FSMContext):
    """Toggle tag selection"""
    if not await is_admin(callback.from_user.id):
        await callback.answer(Messages.ERROR_NOT_ADMIN, show_alert=True)
        return

    data = await state.get_data()
    selected_tags = data.get("selected_tags", [])

    tag_id = callback_data.tag_id

    if tag_id in selected_tags:
        selected_tags.remove(tag_id)
    else:
        selected_tags.append(tag_id)

    await state.update_data(selected_tags=selected_tags)
    await show_tag_selection(callback, state)


@admin_router.callback_query(AdminTagCallback.filter(F.action == "add_new"))
async def add_new_tag_prompt(callback: CallbackQuery, state: FSMContext):
    """Prompt for new tag name"""
    if not await is_admin(callback.from_user.id):
        await callback.answer(Messages.ERROR_NOT_ADMIN, show_alert=True)
        return

    await state.set_state(AdminStates.adding_new_tag)

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="❌ Отмена", callback_data="back_to_tags")

    await callback.message.edit_text(
        "➕ Введите название нового тега:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


@admin_router.message(AdminStates.adding_new_tag)
async def create_new_tag(message: Message, state: FSMContext):
    """Create new tag"""
    if not await is_admin(message.from_user.id):
        await message.answer(Messages.ERROR_NOT_ADMIN)
        return

    tag_name = message.text.strip().lower()

    if not tag_name or len(tag_name) < 2:
        await message.answer("Название тега слишком короткое")
        return

    if len(tag_name) > 50:
        await message.answer("Название тега слишком длинное")
        return

    async with async_session() as session:
        # Check if exists
        existing = await TagService.get_tag_by_name(session, tag_name)
        if existing:
            await message.answer(f"Тег '{tag_name}' уже существует")
            # Go back to tag selection
            await state.set_state(AdminStates.selecting_tags)
            await show_tag_selection(message, state)
            return

        # Create new tag
        new_tag = await TagService.create_tag(session, tag_name)

        # Add to selected
        data = await state.get_data()
        selected_tags = data.get("selected_tags", [])
        selected_tags.append(new_tag.id)
        await state.update_data(selected_tags=selected_tags)

    await state.set_state(AdminStates.selecting_tags)
    await message.answer(f"✅ Тег '{tag_name}' создан и выбран")
    await show_tag_selection(message, state)


@admin_router.callback_query(F.data == "back_to_tags")
async def back_to_tags(callback: CallbackQuery, state: FSMContext):
    """Go back to tag selection"""
    await state.set_state(AdminStates.selecting_tags)
    await show_tag_selection(callback, state)


@admin_router.callback_query(AdminTagCallback.filter(F.action == "done"))
async def tags_done(callback: CallbackQuery, state: FSMContext):
    """Tags selected, choose destination"""
    if not await is_admin(callback.from_user.id):
        await callback.answer(Messages.ERROR_NOT_ADMIN, show_alert=True)
        return

    await state.set_state(AdminStates.choosing_destination)

    keyboard = InlineKeyboardBuilder()
    keyboard.button(
        text="📢 В пост",
        callback_data=AdminDestCallback(action="channel").pack()
    )
    keyboard.button(
        text="📩 В личку",
        callback_data=AdminDestCallback(action="private").pack()
    )
    keyboard.button(text="🔙 Назад к тегам", callback_data="back_to_tags")
    keyboard.adjust(2, 1)

    await callback.message.edit_text(
        Messages.CHOOSE_DESTINATION,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


@admin_router.callback_query(AdminDestCallback.filter(F.action == "private"))
async def send_private_answer(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Send answer privately only"""
    if not await is_admin(callback.from_user.id):
        await callback.answer(Messages.ERROR_NOT_ADMIN, show_alert=True)
        return

    data = await state.get_data()
    question_id = data.get("answering_question_id")
    answer_text = data.get("answer_text")
    question_text = data.get("question_text")

    if not question_id or not answer_text:
        await callback.answer("Ошибка: данные сессии потеряны", show_alert=True)
        await state.clear()
        return

    async with async_session() as session:
        question = await QuestionService.get_question(session, question_id)

        if not question:
            await callback.answer("Вопрос не найден", show_alert=True)
            return

        # Mark as answered
        await QuestionService.mark_answered(
            session=session,
            question_id=question_id,
            answer_text=answer_text,
            is_public=False
        )

        # Send to user
        try:
            await bot.send_message(
                chat_id=question.user_id,
                text=Messages.ANSWER_RECEIVED_PRIVATE.format(
                    question=question_text,
                    answer=answer_text
                )
            )
        except Exception as e:
            print(f"Failed to send answer to user: {e}")

    await state.clear()

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔙 В панель", callback_data="admin_panel")

    await callback.message.edit_text(
        Messages.ANSWER_SENT,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


@admin_router.callback_query(AdminDestCallback.filter(F.action == "channel"))
async def preview_channel_post(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Preview post before publishing to channel"""
    if not await is_admin(callback.from_user.id):
        await callback.answer(Messages.ERROR_NOT_ADMIN, show_alert=True)
        return

    data = await state.get_data()
    question_text = data.get("question_text")
    answer_text = data.get("answer_text")
    selected_tag_ids = data.get("selected_tags", [])

    async with async_session() as session:
        tags = await TagService.get_tags_by_ids(session, selected_tag_ids)
        next_number = await ChannelService.get_next_post_number(session)

    # Create preview
    channel_service = ChannelService(bot)
    date_str = datetime.now().strftime("%d.%m.%Y")

    preview_text = channel_service.format_post(
        post_number=next_number,
        question=question_text,
        answer=answer_text,
        tags=tags,
        date=date_str
    )

    await state.set_state(AdminStates.previewing_post)

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="✅ Опубликовать", callback_data="publish_post")
    keyboard.button(text="✏️ Редактировать ответ", callback_data="edit_answer")
    keyboard.button(text="🔙 Назад", callback_data="back_to_destination")
    keyboard.adjust(1)

    await callback.message.edit_text(
        Messages.POST_PREVIEW.format(post_text=preview_text),
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


@admin_router.callback_query(F.data == "back_to_destination")
async def back_to_destination(callback: CallbackQuery, state: FSMContext):
    """Go back to destination selection"""
    await state.set_state(AdminStates.choosing_destination)

    keyboard = InlineKeyboardBuilder()
    keyboard.button(
        text="📢 В пост",
        callback_data=AdminDestCallback(action="channel").pack()
    )
    keyboard.button(
        text="📩 В личку",
        callback_data=AdminDestCallback(action="private").pack()
    )
    keyboard.button(text="🔙 Назад к тегам", callback_data="back_to_tags")
    keyboard.adjust(2, 1)

    await callback.message.edit_text(
        Messages.CHOOSE_DESTINATION,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


@admin_router.callback_query(F.data == "edit_answer")
async def edit_answer(callback: CallbackQuery, state: FSMContext):
    """Edit answer text"""
    if not await is_admin(callback.from_user.id):
        await callback.answer(Messages.ERROR_NOT_ADMIN, show_alert=True)
        return

    data = await state.get_data()
    question_text = data.get("question_text")

    await state.set_state(AdminStates.typing_answer)

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="❌ Отмена", callback_data="admin_panel")

    await callback.message.edit_text(
        Messages.TYPE_ANSWER.format(question_text=question_text),
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


@admin_router.callback_query(F.data == "publish_post")
async def publish_post(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Publish post to channel"""
    if not await is_admin(callback.from_user.id):
        await callback.answer(Messages.ERROR_NOT_ADMIN, show_alert=True)
        return

    data = await state.get_data()
    question_id = data.get("answering_question_id")
    question_text = data.get("question_text")
    answer_text = data.get("answer_text")
    selected_tag_ids = data.get("selected_tags", [])

    if not question_id or not answer_text:
        await callback.answer("Ошибка: данные сессии потеряны", show_alert=True)
        await state.clear()
        return

    channel_service = ChannelService(bot)

    async with async_session() as session:
        question = await QuestionService.get_question(session, question_id)

        if not question:
            await callback.answer("Вопрос не найден", show_alert=True)
            return

        tags = await TagService.get_tags_by_ids(session, selected_tag_ids)

        # Publish to channel
        channel_post = await channel_service.publish_post(
            session=session,
            question_text=question_text,
            answer_text=answer_text,
            tags=tags,
            admin_id=callback.from_user.id
        )

        # Mark question as answered
        await QuestionService.mark_answered(
            session=session,
            question_id=question_id,
            answer_text=answer_text,
            is_public=True,
            channel_post_id=channel_post.id
        )

        # Add to search index
        search_engine.add_document({
            "post_id": channel_post.id,
            "post_number": channel_post.post_number,
            "question_text": question_text,
            "answer_text": answer_text,
            "message_id": channel_post.message_id
        })

        # Get post URL
        post_url = channel_service.get_post_url(channel_post.message_id)

        # Send notification to user (only link, no answer text)
        try:
            await bot.send_message(
                chat_id=question.user_id,
                text=Messages.ANSWER_RECEIVED_PUBLIC.format(
                    question=question_text,
                    post_url=post_url
                )
            )
        except Exception as e:
            print(f"Failed to send answer to user: {e}")

    await state.clear()

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔙 В панель", callback_data="admin_panel")

    await callback.message.edit_text(
        Messages.POST_PUBLISHED.format(
            post_number=channel_post.post_number,
            post_url=post_url
        ),
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


@admin_router.callback_query(AdminAnswerCallback.filter(F.action == "reject"))
async def reject_question(callback: CallbackQuery, callback_data: AdminAnswerCallback, state: FSMContext):
    """Reject a question"""
    if not await is_admin(callback.from_user.id):
        await callback.answer(Messages.ERROR_NOT_ADMIN, show_alert=True)
        return

    async with async_session() as session:
        await QuestionService.reject_question(session, callback_data.question_id)

    await state.clear()

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔙 В панель", callback_data="admin_panel")

    await callback.message.edit_text(
        Messages.QUESTION_REJECTED,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


# Tag management
@admin_router.callback_query(F.data == "manage_tags")
async def manage_tags(callback: CallbackQuery, state: FSMContext):
    """Tag management screen"""
    if not await is_admin(callback.from_user.id):
        await callback.answer(Messages.ERROR_NOT_ADMIN, show_alert=True)
        return

    async with async_session() as session:
        tags = await TagService.get_all_tags(session)

    text = "🏷️ Управление тегами\n\nВсего тегов: " + str(len(tags)) + "\n\n"

    for tag in tags:
        text += f"• {tag.name}\n"

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="➕ Добавить тег", callback_data="admin_add_tag")
    keyboard.button(text="🔙 Назад", callback_data="admin_panel")
    keyboard.adjust(1)

    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())
    await callback.answer()


@admin_router.callback_query(F.data == "admin_add_tag")
async def admin_add_tag_prompt(callback: CallbackQuery, state: FSMContext):
    """Prompt to add a new tag (outside of answering flow)"""
    if not await is_admin(callback.from_user.id):
        await callback.answer(Messages.ERROR_NOT_ADMIN, show_alert=True)
        return

    await state.set_state(AdminStates.adding_new_tag)
    await state.update_data(return_to="manage_tags")

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="❌ Отмена", callback_data="manage_tags")

    await callback.message.edit_text(
        "➕ Введите название нового тега:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()
