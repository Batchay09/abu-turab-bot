from datetime import datetime
from enum import Enum
from typing import Optional, List

from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    Enum as SQLEnum,
    Table,
)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class QuestionStatus(str, Enum):
    """Question status in the queue"""
    PENDING = "pending"  # Waiting for admin
    IN_PROGRESS = "in_progress"  # Admin is working on it
    ANSWERED_PRIVATE = "answered_private"  # Answered privately only
    ANSWERED_PUBLIC = "answered_public"  # Posted to channel
    REJECTED = "rejected"  # Rejected/invalid


# Association table for post tags
post_tags = Table(
    "post_tags",
    Base.metadata,
    Column("post_id", Integer, ForeignKey("channel_posts.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
)


class User(Base):
    """Telegram user"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user_id
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), default="")
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_active: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    questions: Mapped[List["Question"]] = relationship(
        "Question",
        back_populates="user",
        foreign_keys="Question.user_id"
    )


class Question(Base):
    """User submitted question"""
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[QuestionStatus] = mapped_column(
        SQLEnum(QuestionStatus),
        default=QuestionStatus.PENDING
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Admin handling
    assigned_admin_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Answer
    answer_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Channel post reference (if published)
    channel_post_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("channel_posts.id"),
        nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="questions", foreign_keys=[user_id])
    channel_post: Mapped[Optional["ChannelPost"]] = relationship("ChannelPost", back_populates="question")


class ChannelPost(Base):
    """Published Q&A post in the channel"""
    __tablename__ = "channel_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)  # Auto-incrementing #1, #2...
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # Telegram message_id

    # Content
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Metadata
    posted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    posted_by_admin_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Relationships
    question: Mapped[Optional["Question"]] = relationship("Question", back_populates="channel_post")
    tags: Mapped[List["Tag"]] = relationship("Tag", secondary=post_tags, back_populates="posts")


class Tag(Base):
    """Tag/category for questions"""
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    posts: Mapped[List["ChannelPost"]] = relationship("ChannelPost", secondary=post_tags, back_populates="tags")
