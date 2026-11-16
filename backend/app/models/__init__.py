"""Database models exported for Alembic metadata discovery."""

from app.models.adaptive import (
    AdaptiveProcessingJob,
    AdaptiveSettings,
    MemoryFeedback,
    MemoryPattern,
    UserPreference,
)
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.memory import (
    Memory, MemoryConflict, MemoryExtractionJob, MemoryHistory,
    MemoryRetrievalEvent, MemoryRetrievalItem, MemoryVectorOutbox,
)
from app.models.user import User

__all__ = [
    "AdaptiveProcessingJob", "AdaptiveSettings", "Conversation", "Memory", "MemoryConflict",
    "MemoryExtractionJob", "MemoryFeedback", "MemoryHistory", "MemoryPattern",
    "MemoryRetrievalEvent", "MemoryRetrievalItem", "MemoryVectorOutbox", "Message",
    "User", "UserPreference",
]
