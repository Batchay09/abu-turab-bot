#!/usr/bin/env python3
"""
Channel indexer script.
Fetches existing Q&A posts from a Telegram channel and builds the search index.

Usage:
    python indexer.py

This script uses Pyrogram to access channel history and extracts Q&A posts.
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime

from pyrogram import Client
from pyrogram.errors import FloodWait

from config import config
from services.search_engine import SearchEngine


# Pattern to extract Q&A from channel posts
# Matches posts like:
# 📝 Вопрос №123
# ❓ Вопрос:
# ...question text...
# ✅ Ответ:
# ...answer text...
QA_PATTERN = re.compile(
    r"(?:Вопрос\s*[№#]\s*(\d+)|[📝].*?[№#]\s*(\d+)).*?"
    r"(?:❓\s*)?(?:Вопрос:?\s*\n?)(.+?)"
    r"(?:✅\s*)?(?:Ответ:?\s*\n?)(.+?)(?:🏷️|📅|$)",
    re.DOTALL | re.IGNORECASE
)

# Alternative simpler pattern
SIMPLE_QA_PATTERN = re.compile(
    r"(?:вопрос|❓)[:\s]*\n?(.+?)(?:ответ|✅)[:\s]*\n?(.+?)(?:$|🏷️|📅|---)",
    re.DOTALL | re.IGNORECASE
)


def extract_qa_from_text(text: str, message_id: int) -> dict | None:
    """
    Extract question and answer from a channel post text.

    Args:
        text: Message text
        message_id: Telegram message ID

    Returns:
        Dict with question_text, answer_text, post_number, message_id or None
    """
    if not text:
        return None

    # Try main pattern first
    match = QA_PATTERN.search(text)
    if match:
        post_number = int(match.group(1) or match.group(2) or 0)
        question = match.group(3).strip()
        answer = match.group(4).strip()

        if len(question) > 10 and len(answer) > 10:
            return {
                "question_text": question,
                "answer_text": answer,
                "post_number": post_number if post_number > 0 else message_id,
                "message_id": message_id,
                "post_id": message_id,  # Use message_id as post_id for indexed posts
            }

    # Try simpler pattern
    match = SIMPLE_QA_PATTERN.search(text)
    if match:
        question = match.group(1).strip()
        answer = match.group(2).strip()

        if len(question) > 10 and len(answer) > 10:
            # Try to extract number from anywhere in text
            num_match = re.search(r"[№#]\s*(\d+)", text)
            post_number = int(num_match.group(1)) if num_match else message_id

            return {
                "question_text": question,
                "answer_text": answer,
                "post_number": post_number,
                "message_id": message_id,
                "post_id": message_id,
            }

    return None


async def fetch_channel_posts(
    client: Client,
    channel: str,
    limit: int = 0
) -> list[dict]:
    """
    Fetch all text messages from a channel.

    Args:
        client: Pyrogram client
        channel: Channel username or ID
        limit: Maximum number of messages to fetch (0 = all)

    Returns:
        List of extracted Q&A dicts
    """
    qa_posts = []
    count = 0
    processed = 0

    print(f"Fetching messages from {channel}...")

    try:
        async for message in client.get_chat_history(channel):
            processed += 1

            if processed % 100 == 0:
                print(f"Processed {processed} messages, found {count} Q&A posts...")

            if limit > 0 and count >= limit:
                break

            if not message.text:
                continue

            qa = extract_qa_from_text(message.text, message.id)
            if qa:
                qa_posts.append(qa)
                count += 1

    except FloodWait as e:
        print(f"Flood wait: sleeping {e.value} seconds...")
        await asyncio.sleep(e.value)
        # Could recursively continue here, but for simplicity we just return what we have

    print(f"Fetched {count} Q&A posts from {processed} messages")
    return qa_posts


async def main():
    """Main indexer function"""
    print("=" * 50)
    print("Channel Indexer")
    print("=" * 50)

    # Validate config
    if not config.API_ID or not config.API_HASH:
        print("ERROR: API_ID and API_HASH must be set in .env file")
        print("Get them from https://my.telegram.org")
        sys.exit(1)

    if not config.CHANNEL_USERNAME:
        print("ERROR: CHANNEL_USERNAME must be set in .env file")
        sys.exit(1)

    # Ensure data directory exists
    os.makedirs(config.DATA_DIR, exist_ok=True)

    # Initialize Pyrogram client
    print("\nInitializing Telegram client...")
    client = Client(
        "indexer_session",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        workdir=config.DATA_DIR
    )

    async with client:
        print("Connected to Telegram!")

        # Fetch channel posts
        channel = config.CHANNEL_USERNAME
        if not channel.startswith("@"):
            channel = "@" + channel

        qa_posts = await fetch_channel_posts(client, channel)

        if not qa_posts:
            print("\nNo Q&A posts found in channel!")
            print("Make sure the channel contains posts with 'Вопрос:' and 'Ответ:' format")
            return

        print(f"\nFound {len(qa_posts)} Q&A posts")

        # Sort by post_number
        qa_posts.sort(key=lambda x: x["post_number"])

        # Save raw data for debugging
        raw_path = os.path.join(config.DATA_DIR, "raw_posts.json")
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(qa_posts, f, ensure_ascii=False, indent=2)
        print(f"Raw posts saved to {raw_path}")

    # Initialize search engine and build index
    print("\nInitializing search engine...")
    search_engine = SearchEngine()
    await search_engine.initialize()

    print("Building search index...")
    search_engine.add_documents_batch(qa_posts)

    print(f"\nDone! Indexed {search_engine.get_document_count()} documents")
    print(f"Index saved to {config.FAISS_INDEX_PATH}")
    print(f"Documents saved to {config.DOCUMENTS_PATH}")

    # Test search
    print("\n" + "=" * 50)
    print("Testing search...")
    print("=" * 50)

    test_queries = [
        "как делать омовение",
        "закят с зарплаты",
        "можно ли слушать музыку",
    ]

    for query in test_queries:
        print(f"\nQuery: '{query}'")
        results = search_engine.search(query, top_k=3)

        if results:
            for doc, score in results:
                print(f"  [{score:.3f}] №{doc['post_number']}: {doc['question_text'][:50]}...")
        else:
            print("  No results found")


if __name__ == "__main__":
    asyncio.run(main())
