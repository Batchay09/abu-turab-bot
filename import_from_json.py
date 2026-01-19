#!/usr/bin/env python3
"""
Import Q&A posts from Telegram Desktop JSON export.

How to export:
1. Open Telegram Desktop
2. Go to the channel
3. Click ⋮ (three dots) → Export chat history
4. Select format: JSON
5. Uncheck media (not needed)
6. Export

Usage:
    python import_from_json.py path/to/result.json
"""

import asyncio
import json
import os
import re
import sys

from config import config
from services.search_engine import SearchEngine


# Pattern to extract Q&A from channel posts
QA_PATTERN = re.compile(
    r"(?:Вопрос\s*[№#]\s*(\d+)|[📝].*?[№#]\s*(\d+)).*?"
    r"(?:❓\s*)?(?:Вопрос:?\s*\n?)(.+?)"
    r"(?:✅\s*)?(?:Ответ:?\s*\n?)(.+?)(?:🏷️|📅|$)",
    re.DOTALL | re.IGNORECASE
)

SIMPLE_QA_PATTERN = re.compile(
    r"(?:вопрос|❓)[:\s]*\n?(.+?)(?:ответ|✅)[:\s]*\n?(.+?)(?:$|🏷️|📅|---)",
    re.DOTALL | re.IGNORECASE
)


def extract_qa_from_text(text: str, message_id: int) -> dict | None:
    """Extract question and answer from message text."""
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
                "post_id": message_id,
            }

    # Try simpler pattern
    match = SIMPLE_QA_PATTERN.search(text)
    if match:
        question = match.group(1).strip()
        answer = match.group(2).strip()

        if len(question) > 10 and len(answer) > 10:
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


def load_telegram_export(json_path: str) -> list[dict]:
    """
    Load messages from Telegram Desktop JSON export.

    The export format is:
    {
        "messages": [
            {
                "id": 123,
                "type": "message",
                "text": "message text" or [{"type": "plain", "text": "..."}]
            },
            ...
        ]
    }
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    messages = data.get("messages", [])
    qa_posts = []

    print(f"Processing {len(messages)} messages...")

    for msg in messages:
        if msg.get("type") != "message":
            continue

        msg_id = msg.get("id", 0)

        # Text can be string or array of text entities
        text_data = msg.get("text", "")

        if isinstance(text_data, str):
            text = text_data
        elif isinstance(text_data, list):
            # Combine text entities
            parts = []
            for part in text_data:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict) and "text" in part:
                    parts.append(part["text"])
            text = "".join(parts)
        else:
            continue

        if not text:
            continue

        qa = extract_qa_from_text(text, msg_id)
        if qa:
            qa_posts.append(qa)

    return qa_posts


async def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage: python import_from_json.py path/to/result.json")
        print("\nHow to export from Telegram Desktop:")
        print("1. Open Telegram Desktop")
        print("2. Go to the channel")
        print("3. Click ⋮ → Export chat history")
        print("4. Select format: JSON")
        print("5. Export and run this script with the result.json path")
        sys.exit(1)

    json_path = sys.argv[1]

    if not os.path.exists(json_path):
        print(f"ERROR: File not found: {json_path}")
        sys.exit(1)

    print("=" * 50)
    print("Import from Telegram JSON Export")
    print("=" * 50)

    # Load and parse messages
    qa_posts = load_telegram_export(json_path)

    if not qa_posts:
        print("\nNo Q&A posts found!")
        print("Make sure posts contain 'Вопрос:' and 'Ответ:' sections")
        sys.exit(1)

    print(f"\nFound {len(qa_posts)} Q&A posts")

    # Sort by post_number
    qa_posts.sort(key=lambda x: x["post_number"])

    # Show sample
    print("\nSample posts found:")
    for qa in qa_posts[:3]:
        print(f"  №{qa['post_number']}: {qa['question_text'][:50]}...")

    # Ensure data directory
    os.makedirs(config.DATA_DIR, exist_ok=True)

    # Save raw data
    raw_path = os.path.join(config.DATA_DIR, "raw_posts.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(qa_posts, f, ensure_ascii=False, indent=2)
    print(f"\nRaw posts saved to {raw_path}")

    # Build search index
    print("\nInitializing search engine...")
    search_engine = SearchEngine()
    await search_engine.initialize()

    print("Building search index...")
    search_engine.add_documents_batch(qa_posts)

    print(f"\nDone! Indexed {search_engine.get_document_count()} documents")
    print(f"Index saved to {config.FAISS_INDEX_PATH}")

    # Test search
    print("\n" + "=" * 50)
    print("Testing search...")
    print("=" * 50)

    test_queries = ["намаз", "закят", "пост"]

    for query in test_queries:
        print(f"\nQuery: '{query}'")
        results = search_engine.search(query, top_k=2)

        if results:
            for doc, score in results:
                print(f"  [{score:.3f}] №{doc['post_number']}: {doc['question_text'][:40]}...")
        else:
            print("  No results")


if __name__ == "__main__":
    asyncio.run(main())
