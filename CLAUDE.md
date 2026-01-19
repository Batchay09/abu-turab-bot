# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Abu Turab is a Telegram Q&A bot for Islamic religious questions built with Python. Users submit questions, administrators review and answer them, and answered questions are published to a Telegram channel. The bot features semantic search using FAISS and sentence-transformers to find similar previously-answered questions.

**Language**: Russian (all user-facing text)
**ML Model**: `sergeyzh/rubert-tiny-turbo` (312-dimensional Russian embeddings)

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python bot.py

# Index existing channel posts (ИНТЕРАКТИВНЫЙ - запускать вручную в терминале)
# Требует ввод номера телефона и кода из Telegram
python indexer.py

# Import Q&A from Telegram Desktop JSON export
python import_from_json.py /path/to/result.json
```

## Environment Setup

Copy `.env.example` to `.env` and configure:
- `BOT_TOKEN` - from @BotFather
- `CHANNEL_ID`, `CHANNEL_USERNAME` - target channel for publishing
- `ADMIN_IDS` - comma-separated Telegram user IDs
- `API_ID`, `API_HASH` - from my.telegram.org (only for indexer.py)

## Architecture

```
bot.py              # Entry point - initializes DB, search engine, registers routers
config.py           # Centralized configuration from environment variables

database/
  models.py         # SQLAlchemy models: User, Question, ChannelPost, Tag
  connection.py     # Async SQLite connection (aiosqlite)

services/
  search_engine.py  # FAISS-based semantic search (singleton pattern)
  question_service.py # Question CRUD operations
  channel_service.py  # Channel post publishing and formatting
  tag_service.py      # Tag/category management
  synonyms.py         # Islamic terminology synonym expansion

handlers/
  common.py         # /start, /help, cancel, main menu
  user.py           # Question submission flow with semantic search
  admin.py          # Admin panel, queue management, answering workflow

states/
  states.py         # FSM states for multi-step conversations

templates/
  messages.py       # All bot message strings (Russian)

data/               # Runtime data (auto-created)
  bot.db            # SQLite database
  faiss.index       # Vector search index
  documents.json    # Document metadata for search
```

## Key Patterns

- **FSM (Finite State Machine)**: aiogram FSM for multi-step conversations (question submission, admin answering)
- **Service Layer**: Business logic in `services/`, handlers only coordinate
- **Singleton Search Engine**: Global `search_engine` instance in `services/search_engine.py`
- **Async Throughout**: All database and Telegram API calls use async/await
- **CallbackData Classes**: Structured callback payloads for inline keyboards

## Question Flow

1. User submits question → semantic search shows similar existing answers
2. Question saved with status `pending`
3. Admin takes question (`in_progress`), writes answer, selects tags
4. Admin chooses destination: private reply or channel publication
5. Published posts get sequential numbers (#1, #2, etc.) and are indexed for search

## Database Models

- **User**: Telegram users with `is_admin`, `is_banned` flags
- **Question**: Status progression: `pending` → `in_progress` → `answered`/`rejected`
- **ChannelPost**: Published Q&A with sequential `post_number`
- **Tag**: 24 predefined Islamic categories (Pillars of Islam, Fiqh sections, Aqeedah, etc.)

## Notes

- Uses MemoryStorage for FSM; comment in `bot.py` notes Redis needed for multi-worker deployment
- Search threshold configured in `config.py`: `SIMILARITY_THRESHOLD = 0.5`
- Synonym expansion in `services/synonyms.py` improves search recall for Islamic terminology
