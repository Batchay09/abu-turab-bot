"""
Service for managing channel posts.
"""

from datetime import datetime
from typing import Optional

from aiogram import Bot
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import config
from database.models import ChannelPost, Tag


class ChannelService:
    """Service for channel post management"""

    # Post template
    POST_TEMPLATE = """📝 Вопрос №{post_number}

❓ Вопрос:
{question}

✅ Ответ:
{answer}

{tags_line}
📅 {date}
🔗 Задать вопрос: @{bot_username}"""

    def __init__(self, bot: Bot):
        self.bot = bot

    @staticmethod
    async def get_next_post_number(session: AsyncSession) -> int:
        """Get the next sequential post number"""
        result = await session.execute(
            select(func.max(ChannelPost.post_number))
        )
        max_number = result.scalar() or 0
        return max_number + 1

    @staticmethod
    def format_tags(tags: list[Tag]) -> str:
        """Format tags as hashtags"""
        if not tags:
            return ""
        return "🏷️ " + " ".join(f"#{tag.name.replace(' ', '_')}" for tag in tags)

    def format_post(
        self,
        post_number: int,
        question: str,
        answer: str,
        tags: list[Tag],
        date: str
    ) -> str:
        """Format a channel post"""
        tags_line = self.format_tags(tags)

        return self.POST_TEMPLATE.format(
            post_number=post_number,
            question=question.strip(),
            answer=answer.strip(),
            tags_line=tags_line,
            date=date,
            bot_username=config.BOT_USERNAME
        )

    async def publish_post(
        self,
        session: AsyncSession,
        question_text: str,
        answer_text: str,
        tags: list[Tag],
        admin_id: int
    ) -> ChannelPost:
        """
        Publish a Q&A post to the channel.

        Returns:
            Created ChannelPost object
        """
        # Get next post number
        post_number = await self.get_next_post_number(session)

        # Format the post
        date_str = datetime.now().strftime("%d.%m.%Y")
        post_text = self.format_post(
            post_number=post_number,
            question=question_text,
            answer=answer_text,
            tags=tags,
            date=date_str
        )

        # Send to channel
        message = await self.bot.send_message(
            chat_id=config.CHANNEL_ID,
            text=post_text,
            parse_mode=None  # Plain text for better compatibility
        )

        # Create database record
        channel_post = ChannelPost(
            post_number=post_number,
            message_id=message.message_id,
            question_text=question_text,
            answer_text=answer_text,
            posted_at=datetime.utcnow(),
            posted_by_admin_id=admin_id
        )
        channel_post.tags = tags

        session.add(channel_post)
        await session.commit()
        await session.refresh(channel_post)

        return channel_post

    @staticmethod
    async def get_post(
        session: AsyncSession,
        post_id: int
    ) -> Optional[ChannelPost]:
        """Get a channel post by ID"""
        result = await session.execute(
            select(ChannelPost)
            .where(ChannelPost.id == post_id)
            .options(selectinload(ChannelPost.tags))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_post_by_number(
        session: AsyncSession,
        post_number: int
    ) -> Optional[ChannelPost]:
        """Get a channel post by post number"""
        result = await session.execute(
            select(ChannelPost)
            .where(ChannelPost.post_number == post_number)
            .options(selectinload(ChannelPost.tags))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_posts(session: AsyncSession) -> list[ChannelPost]:
        """Get all channel posts for indexing"""
        result = await session.execute(
            select(ChannelPost)
            .options(selectinload(ChannelPost.tags))
            .order_by(ChannelPost.post_number)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_post_count(session: AsyncSession) -> int:
        """Get total number of posts"""
        result = await session.execute(
            select(func.count(ChannelPost.id))
        )
        return result.scalar() or 0

    def get_post_url(self, message_id: int) -> str:
        """Get the URL to a channel post"""
        return f"https://t.me/{config.CHANNEL_USERNAME}/{message_id}"
