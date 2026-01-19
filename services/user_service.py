"""
Service for managing users.
"""

from datetime import datetime
from typing import Optional

from aiogram.types import User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from database.models import User


class UserService:
    """Service for user management"""

    @staticmethod
    async def get_or_create_user(
        session: AsyncSession,
        tg_user: TgUser
    ) -> User:
        """Get existing user or create new one"""
        result = await session.execute(
            select(User).where(User.id == tg_user.id)
        )
        user = result.scalar_one_or_none()

        if user:
            # Update last active and user info
            user.last_active = datetime.utcnow()
            user.username = tg_user.username
            user.first_name = tg_user.first_name or ""
            user.last_name = tg_user.last_name
            await session.commit()
            return user

        # Create new user
        user = User(
            id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name or "",
            last_name=tg_user.last_name,
            is_admin=tg_user.id in config.ADMIN_IDS,
            created_at=datetime.utcnow(),
            last_active=datetime.utcnow()
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    @staticmethod
    async def get_user(session: AsyncSession, user_id: int) -> Optional[User]:
        """Get user by ID"""
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def is_admin(session: AsyncSession, user_id: int) -> bool:
        """Check if user is admin"""
        # First check config
        if user_id in config.ADMIN_IDS:
            return True

        # Then check database
        user = await UserService.get_user(session, user_id)
        return user.is_admin if user else False

    @staticmethod
    async def set_admin(session: AsyncSession, user_id: int, is_admin: bool) -> bool:
        """Set user admin status"""
        user = await UserService.get_user(session, user_id)
        if not user:
            return False

        user.is_admin = is_admin
        await session.commit()
        return True

    @staticmethod
    async def ban_user(session: AsyncSession, user_id: int) -> bool:
        """Ban a user"""
        user = await UserService.get_user(session, user_id)
        if not user:
            return False

        user.is_banned = True
        await session.commit()
        return True

    @staticmethod
    async def unban_user(session: AsyncSession, user_id: int) -> bool:
        """Unban a user"""
        user = await UserService.get_user(session, user_id)
        if not user:
            return False

        user.is_banned = False
        await session.commit()
        return True

    @staticmethod
    async def is_banned(session: AsyncSession, user_id: int) -> bool:
        """Check if user is banned"""
        user = await UserService.get_user(session, user_id)
        return user.is_banned if user else False
