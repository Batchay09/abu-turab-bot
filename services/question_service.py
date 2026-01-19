"""
Service for managing the question queue.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import Question, QuestionStatus, User, SelfAnsweredLog


class QuestionService:
    """Service for question queue management"""

    @staticmethod
    async def submit_question(
        session: AsyncSession,
        user_id: int,
        question_text: str
    ) -> Question:
        """Submit a new question to the queue"""
        question = Question(
            user_id=user_id,
            question_text=question_text,
            status=QuestionStatus.PENDING,
            created_at=datetime.utcnow()
        )
        session.add(question)
        await session.commit()
        await session.refresh(question)
        return question

    @staticmethod
    async def get_question(
        session: AsyncSession,
        question_id: int
    ) -> Optional[Question]:
        """Get a question by ID"""
        result = await session.execute(
            select(Question)
            .where(Question.id == question_id)
            .options(selectinload(Question.user))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_pending_questions(
        session: AsyncSession,
        page: int = 0,
        per_page: int = 10
    ) -> list[Question]:
        """Get paginated list of pending questions (FIFO order)"""
        result = await session.execute(
            select(Question)
            .where(Question.status == QuestionStatus.PENDING)
            .options(selectinload(Question.user))
            .order_by(Question.created_at.asc())
            .offset(page * per_page)
            .limit(per_page)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_assigned_questions(
        session: AsyncSession,
        admin_id: int,
        page: int = 0,
        per_page: int = 10
    ) -> list[Question]:
        """Get questions assigned to a specific admin"""
        result = await session.execute(
            select(Question)
            .where(
                Question.assigned_admin_id == admin_id,
                Question.status == QuestionStatus.IN_PROGRESS
            )
            .options(selectinload(Question.user))
            .order_by(Question.created_at.asc())
            .offset(page * per_page)
            .limit(per_page)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_queue_stats(
        session: AsyncSession,
        admin_id: Optional[int] = None
    ) -> dict:
        """Get queue statistics"""
        # Pending count
        pending_result = await session.execute(
            select(func.count(Question.id))
            .where(Question.status == QuestionStatus.PENDING)
        )
        pending = pending_result.scalar() or 0

        # In progress count
        in_progress_result = await session.execute(
            select(func.count(Question.id))
            .where(Question.status == QuestionStatus.IN_PROGRESS)
        )
        in_progress = in_progress_result.scalar() or 0

        # Answered today
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        answered_today_result = await session.execute(
            select(func.count(Question.id))
            .where(
                Question.status.in_([
                    QuestionStatus.ANSWERED_PUBLIC,
                    QuestionStatus.ANSWERED_PRIVATE
                ]),
                Question.answered_at >= today
            )
        )
        answered_today = answered_today_result.scalar() or 0

        # Total answered
        total_answered_result = await session.execute(
            select(func.count(Question.id))
            .where(
                Question.status.in_([
                    QuestionStatus.ANSWERED_PUBLIC,
                    QuestionStatus.ANSWERED_PRIVATE
                ])
            )
        )
        total_answered = total_answered_result.scalar() or 0

        # My assigned (if admin_id provided)
        my_assigned = 0
        if admin_id:
            my_assigned_result = await session.execute(
                select(func.count(Question.id))
                .where(
                    Question.assigned_admin_id == admin_id,
                    Question.status == QuestionStatus.IN_PROGRESS
                )
            )
            my_assigned = my_assigned_result.scalar() or 0

        # Self-answered statistics (users who found answers via search)
        self_answered_today_result = await session.execute(
            select(func.count(SelfAnsweredLog.id))
            .where(SelfAnsweredLog.created_at >= today)
        )
        self_answered_today = self_answered_today_result.scalar() or 0

        total_self_answered_result = await session.execute(
            select(func.count(SelfAnsweredLog.id))
        )
        total_self_answered = total_self_answered_result.scalar() or 0

        return {
            "pending": pending,
            "in_progress": in_progress,
            "answered_today": answered_today,
            "total_answered": total_answered,
            "my_assigned": my_assigned,
            "self_answered_today": self_answered_today,
            "total_self_answered": total_self_answered,
        }

    @staticmethod
    async def assign_to_admin(
        session: AsyncSession,
        question_id: int,
        admin_id: int
    ) -> Optional[Question]:
        """Assign a question to an admin"""
        question = await QuestionService.get_question(session, question_id)
        if not question:
            return None

        question.assigned_admin_id = admin_id
        question.status = QuestionStatus.IN_PROGRESS
        question.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(question)
        return question

    @staticmethod
    async def mark_answered(
        session: AsyncSession,
        question_id: int,
        answer_text: str,
        is_public: bool,
        channel_post_id: Optional[int] = None
    ) -> Optional[Question]:
        """Mark a question as answered"""
        question = await QuestionService.get_question(session, question_id)
        if not question:
            return None

        question.status = (
            QuestionStatus.ANSWERED_PUBLIC if is_public
            else QuestionStatus.ANSWERED_PRIVATE
        )
        question.answer_text = answer_text
        question.answered_at = datetime.utcnow()
        question.updated_at = datetime.utcnow()

        if channel_post_id:
            question.channel_post_id = channel_post_id

        await session.commit()
        await session.refresh(question)
        return question

    @staticmethod
    async def reject_question(
        session: AsyncSession,
        question_id: int
    ) -> Optional[Question]:
        """Reject a question"""
        question = await QuestionService.get_question(session, question_id)
        if not question:
            return None

        question.status = QuestionStatus.REJECTED
        question.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(question)
        return question

    @staticmethod
    async def get_user_questions(
        session: AsyncSession,
        user_id: int,
        limit: int = 10
    ) -> list[Question]:
        """Get user's submitted questions with channel post info"""
        result = await session.execute(
            select(Question)
            .options(selectinload(Question.channel_post))
            .where(Question.user_id == user_id)
            .order_by(Question.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_pending_count(session: AsyncSession) -> int:
        """Get count of pending questions"""
        result = await session.execute(
            select(func.count(Question.id))
            .where(Question.status == QuestionStatus.PENDING)
        )
        return result.scalar() or 0

    @staticmethod
    async def log_self_answered(
        session: AsyncSession,
        user_id: int,
        question_preview: str,
        found_post_id: Optional[int] = None
    ) -> SelfAnsweredLog:
        """Log when a user found their answer via search"""
        log = SelfAnsweredLog(
            user_id=user_id,
            question_preview=question_preview[:500],  # Limit preview length
            found_post_id=found_post_id
        )
        session.add(log)
        await session.commit()
        return log

    @staticmethod
    async def get_self_answered_count(session: AsyncSession) -> int:
        """Get total count of self-answered questions"""
        result = await session.execute(
            select(func.count(SelfAnsweredLog.id))
        )
        return result.scalar() or 0

    @staticmethod
    async def get_self_answered_today(session: AsyncSession) -> int:
        """Get count of self-answered questions today"""
        from datetime import date
        today = date.today()
        result = await session.execute(
            select(func.count(SelfAnsweredLog.id))
            .where(func.date(SelfAnsweredLog.created_at) == today)
        )
        return result.scalar() or 0
