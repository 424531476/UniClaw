import json
import logging
from dataclasses import dataclass


from tools.memory.consolidate import consolidate_session
from tools.memory.memory import Memory

logger = logging.getLogger(__name__)

REVIEW_INTERVAL_USER_MESSAGES = 10


async def review_and_save_if_due(task, config: dict) -> list[Memory]:
    """Review new conversation turns every 10 user messages and save useful memories."""
    messages = getattr(task, "messages", [])
    current_user_count = len(messages)
    last_reviewed = int(getattr(task, "memory_review_user_count", 0) or 0)

    if current_user_count - last_reviewed < REVIEW_INTERVAL_USER_MESSAGES:
        return []

    review_messages = messages[last_reviewed:]
    memories = await consolidate_session(review_messages, config)
    setattr(task, "memory_review_user_count", current_user_count)
    return memories
