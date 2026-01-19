"""
Service for managing tags/categories.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Tag


# Default tags to initialize
DEFAULT_TAGS = [
    # Pillars of Islam - Столпы ислама
    {"name": "намаз", "description": "Вопросы о молитве (салят)"},
    {"name": "закят", "description": "Обязательная милостыня"},
    {"name": "пост", "description": "Вопросы о посте (саум, ураза)"},
    {"name": "хадж", "description": "Большое паломничество"},
    {"name": "умра", "description": "Малое паломничество"},

    # Fiqh sections - Разделы фикха
    {"name": "тахарат", "description": "Очищение, омовение"},
    {"name": "никах", "description": "Брак, женитьба"},
    {"name": "талак", "description": "Развод"},
    {"name": "торговля", "description": "Купля-продажа, финансы"},
    {"name": "наследство", "description": "Вопросы наследования"},
    {"name": "еда", "description": "Халяль/харам в еде"},
    {"name": "одежда", "description": "Вопросы одежды, аура"},

    # Belief - Вероубеждение
    {"name": "акыда", "description": "Вероубеждение"},
    {"name": "таухид", "description": "Единобожие"},
    {"name": "ширк", "description": "Многобожие, его виды"},

    # Other - Другое
    {"name": "семья", "description": "Семейные отношения"},
    {"name": "воспитание", "description": "Воспитание детей"},
    {"name": "женщинам", "description": "Вопросы для женщин"},
    {"name": "похороны", "description": "Джаназа, погребение"},
    {"name": "дуа", "description": "Мольбы, зикр"},
    {"name": "Коран", "description": "Вопросы о Коране"},
    {"name": "хадисы", "description": "Вопросы о хадисах"},
    {"name": "общее", "description": "Общие вопросы"},
]


class TagService:
    """Service for tag management"""

    @staticmethod
    async def init_default_tags(session: AsyncSession):
        """Initialize default tags if they don't exist"""
        for tag_data in DEFAULT_TAGS:
            existing = await session.execute(
                select(Tag).where(Tag.name == tag_data["name"])
            )
            if not existing.scalar_one_or_none():
                tag = Tag(name=tag_data["name"], description=tag_data["description"])
                session.add(tag)

        await session.commit()

    @staticmethod
    async def get_all_tags(session: AsyncSession) -> list[Tag]:
        """Get all tags"""
        result = await session.execute(
            select(Tag).order_by(Tag.name)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_tag(session: AsyncSession, tag_id: int) -> Optional[Tag]:
        """Get a tag by ID"""
        result = await session.execute(
            select(Tag).where(Tag.id == tag_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_tag_by_name(session: AsyncSession, name: str) -> Optional[Tag]:
        """Get a tag by name"""
        result = await session.execute(
            select(Tag).where(Tag.name == name)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_tag(
        session: AsyncSession,
        name: str,
        description: Optional[str] = None
    ) -> Tag:
        """Create a new tag"""
        tag = Tag(name=name, description=description)
        session.add(tag)
        await session.commit()
        await session.refresh(tag)
        return tag

    @staticmethod
    async def delete_tag(session: AsyncSession, tag_id: int) -> bool:
        """Delete a tag"""
        tag = await TagService.get_tag(session, tag_id)
        if not tag:
            return False

        await session.delete(tag)
        await session.commit()
        return True

    @staticmethod
    async def get_tags_by_ids(session: AsyncSession, tag_ids: list[int]) -> list[Tag]:
        """Get multiple tags by their IDs"""
        if not tag_ids:
            return []

        result = await session.execute(
            select(Tag).where(Tag.id.in_(tag_ids))
        )
        return list(result.scalars().all())
