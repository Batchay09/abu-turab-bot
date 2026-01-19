"""
FSM States for the bot.
"""

from aiogram.fsm.state import State, StatesGroup


class UserStates(StatesGroup):
    """States for regular users asking questions"""

    # Question submission flow
    typing_question = State()       # User is typing their question
    reviewing_similar = State()     # User is reviewing similar Q&As
    confirming_submit = State()     # User confirms they want to submit


class AdminStates(StatesGroup):
    """States for admin/responders"""

    # Answering flow
    viewing_question = State()      # Looking at a specific question
    typing_answer = State()         # Composing answer
    selecting_tags = State()        # Choosing tags for the answer
    adding_new_tag = State()        # Adding a new tag
    choosing_destination = State()  # Private reply or channel post
    previewing_post = State()       # Preview before publishing
