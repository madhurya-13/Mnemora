"""Database models exported for Alembic metadata discovery."""

from app.models.adaptive import (
    AdaptiveProcessingJob,
    AdaptiveSettings,
    MemoryFeedback,
    MemoryPattern,
    UserPreference,
)
from app.models.agent import (
    AgentApproval,
    AgentExecution,
    AgentPlan,
    AgentTask,
    ExecutionEvent,
    TaskVerification,
    ToolInvocation,
    WorkflowTemplate,
)
from app.models.conversation import Conversation
from app.models.graph import (
    GraphEntity,
    GraphHistory,
    GraphMergeRecord,
    GraphRelationship,
    GraphSyncRecord,
)
from app.models.message import Message
from app.models.memory import (
    Memory, MemoryConflict, MemoryExtractionJob, MemoryHistory,
    MemoryRetrievalEvent, MemoryRetrievalItem, MemoryVectorOutbox,
)
from app.models.user import User

__all__ = [
    "AdaptiveProcessingJob", "AdaptiveSettings", "AgentApproval", "AgentExecution",
    "AgentPlan", "AgentTask", "Conversation", "ExecutionEvent", "GraphEntity",
    "GraphHistory", "GraphMergeRecord", "GraphRelationship", "GraphSyncRecord",
    "Memory", "MemoryConflict", "MemoryExtractionJob", "MemoryFeedback",
    "MemoryHistory", "MemoryPattern", "MemoryRetrievalEvent", "MemoryRetrievalItem",
    "MemoryVectorOutbox", "Message", "TaskVerification", "ToolInvocation", "User",
    "UserPreference", "WorkflowTemplate",
]
