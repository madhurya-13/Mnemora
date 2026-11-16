"""Reproducible Milestone 7 evaluation on a synthetic, isolated database.

Run from the repository root with the backend on PYTHONPATH:

    python scripts/adaptive_evaluation.py

No provider calls, no real user data and no production database are used.
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from importlib import import_module

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.database.db import make_engine
from app.models.adaptive import MemoryFeedback, UserPreference
from app.models.conversation import Conversation
from app.models.memory import Memory
from app.models.message import Message
from app.models.user import User
from app.retrieval import conflict_detector
from app.schemas.adaptive import FeedbackCreateRequest
from app.services.adaptive_memory import (
    adaptive_engine,
    feedback_processor,
    memory_decay,
    personalization_engine,
    preference_learner,
)

import_module("app.models")  # register every table with Base.metadata


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _user(db) -> User:
    user = User(username="Evaluation user", guest_session_hash=f"eval-{uuid4()}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _conversation(db, user: User, index: int) -> Conversation:
    conversation = Conversation(user_id=user.user_id, title=f"Eval conversation {index}")
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def _message(db, conversation: Conversation, content: str, role: str = "user") -> Message:
    message = Message(
        conversation_id=conversation.conversation_id,
        role=role,
        content=content,
        status="completed",
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def _memory(db, user: User, content: str, **overrides) -> Memory:
    now = _now()
    memory = Memory(
        user_id=user.user_id,
        content=content,
        category=overrides.pop("category", "preferences"),
        importance=overrides.pop("importance", 0.8),
        confidence=overrides.pop("confidence", 0.9),
        memory_type=overrides.pop("memory_type", "stable"),
        approval_status=overrides.pop("approval_status", "approved"),
        vector_sync_status="synced",
        created_at=overrides.pop("created_at", now),
        updated_at=overrides.pop("updated_at", now),
        expires_at=overrides.pop("expires_at", None),
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


# --- synthetic dataset ---------------------------------------------------------

POSITIVE_UTTERANCES = [
    "Please explain it step by step with practical examples.",
    "I prefer step-by-step explanations in Python.",
    "Give me milestone-based plans with simple steps.",
    "Use Python examples and a milestone plan.",
    "Practical examples help me learn step by step.",
]
NEGATIVE_UTTERANCES = [
    "Python is a programming language.",
    "For this project, give me concise answers.",
    "My password is hunter2 and I prefer concise answers.",
    "What is the capital of Japan?",
]
EXPECTED_PREFERENCES = {
    "learning_style:step_by_step",
    "learning_style:practical_examples",
    "programming:python",
    "project_workflow:milestone_plans",
}

EVOLUTION_CASES = [
    {
        "label": "expired temporary task",
        "content": "Temporary errand due last week",
        "category": "temporary",
        "memory_type": "temporary",
        "importance": 0.2,
        "confidence": 0.5,
        "age_days": 30,
        "expires_in_days": -1,
        "expected": "expired",
    },
    {
        "label": "long-idle low-importance temporary note",
        "content": "Short-term errand from long ago",
        "category": "temporary",
        "memory_type": "temporary",
        "importance": 0.1,
        "confidence": 0.3,
        "age_days": 900,
        "expires_in_days": None,
        "expected": "possibly_outdated",
    },
    {
        "label": "recent temporary task",
        "content": "Temporary errand due next week",
        "category": "temporary",
        "memory_type": "temporary",
        "importance": 0.7,
        "confidence": 0.9,
        "age_days": 1,
        "expires_in_days": 7,
        "expected": "active",
    },
    {
        "label": "stable education fact",
        "content": "User is studying computer science",
        "category": "education",
        "memory_type": "stable",
        "importance": 0.9,
        "confidence": 0.95,
        "age_days": 900,
        "expires_in_days": None,
        "expected": "active",
    },
]

CONFLICT_CASES = [
    (
        "preference change",
        Memory(user_id=uuid4(), content="User prefers Java", category="preferences",
               importance=0.8, confidence=0.9, memory_type="stable", approval_status="approved"),
        "User now prefers Python",
        "preferences",
        True,
    ),
    (
        "drink preference change",
        Memory(user_id=uuid4(), content="User prefers tea", category="preferences",
               importance=0.8, confidence=0.9, memory_type="stable", approval_status="approved"),
        "User prefers coffee",
        "preferences",
        True,
    ),
    (
        "unrelated education facts",
        Memory(user_id=uuid4(), content="User studies computer science", category="education",
               importance=0.8, confidence=0.9, memory_type="stable", approval_status="approved"),
        "User studies mathematics",
        "education",
        False,
    ),
    (
        "different categories",
        Memory(user_id=uuid4(), content="User prefers tea", category="preferences",
               importance=0.8, confidence=0.9, memory_type="stable", approval_status="approved"),
        "User is building a study planner",
        "projects",
        False,
    ),
]

PERSONALIZATION_CASES = [
    ("Explain binary search step by step", {"learning_style:step_by_step", "learning_style:practical_examples"}),
    ("Give me Python code for a linked list", {"programming:python"}),
    ("Plan my project in milestones", {"project_workflow:milestone_plans"}),
    ("What is the capital of Japan?", set()),
]


def _baseline_select(db, user_id, query: str, memories: list[Memory]) -> list[Memory]:
    """Non-adaptive baseline: keyword overlap only, no preference learning."""
    tokens = {token for token in query.casefold().split() if len(token) > 2}
    scored = []
    for memory in memories:
        overlap = len(tokens.intersection(memory.content.casefold().split()))
        if overlap:
            scored.append((overlap, memory.importance, memory))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored[:3]]


def evaluate() -> dict:
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{(Path(directory) / 'adaptive_eval.sqlite3').as_posix()}"
        engine = make_engine(database_url)
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

        try:
            with factory() as db:
                user = _user(db)

                # 1. Preference detection over repeated positive and distractors.
                conversation = _conversation(db, user, 1)
                for index, utterance in enumerate(POSITIVE_UTTERANCES):
                    _message(db, conversation, utterance)
                    preference_learner.learn_from_message(
                        db, user.user_id, utterance,
                        conversation_id=conversation.conversation_id,
                        message_id=uuid4(),
                        confidence_threshold=0.6,
                        evidence_threshold=3,
                        require_user_review=True,
                    )
                for utterance in NEGATIVE_UTTERANCES:
                    preference_learner.learn_from_message(
                        db, user.user_id, utterance,
                        conversation_id=conversation.conversation_id,
                        message_id=uuid4(),
                        confidence_threshold=0.6,
                        evidence_threshold=3,
                        require_user_review=True,
                    )
                predicted = {
                    preference.normalized_key
                    for preference in db.scalars(
                        select(UserPreference).where(
                            UserPreference.user_id == user.user_id,
                            UserPreference.status.in_(("candidate", "confirmed")),
                        )
                    ).all()
                }
                true_positive = len(predicted & EXPECTED_PREFERENCES)
                precision = true_positive / max(1, len(predicted))
                recall = true_positive / max(1, len(EXPECTED_PREFERENCES))
                false_rate = len(predicted - EXPECTED_PREFERENCES) / max(1, len(predicted))

                # Confirm expected preferences for later personalization checks.
                preferences = db.scalars(
                    select(UserPreference).where(UserPreference.user_id == user.user_id)
                ).all()
                for preference in preferences:
                    preference.status = "confirmed" if preference.normalized_key in EXPECTED_PREFERENCES else "candidate"
                db.commit()

                # 2. Lifecycle / outdated handling.
                lifecycle_cases = []
                for case in EVOLUTION_CASES:
                    updated = _now() - timedelta(days=case["age_days"])
                    expires = (
                        _now() + timedelta(days=case["expires_in_days"])
                        if case["expires_in_days"] is not None
                        else None
                    )
                    memory = _memory(
                        db, user, case["content"],
                        category=case["category"], memory_type=case["memory_type"],
                        importance=case["importance"], confidence=case["confidence"],
                        updated_at=updated, expires_at=expires,
                    )
                    lifecycle_cases.append((case, memory))

                archived = _memory(db, user, "User archived this old preference")
                archived.lifecycle_status = "archived"
                db.commit()
                lifecycle_cases.append((
                    {"label": "explicitly archived memory", "expected": "archived"},
                    archived,
                ))

                before_count = db.scalar(
                    select(Memory.memory_id).where(Memory.user_id == user.user_id).limit(1)
                )
                memory_decay.evaluate_user(db, user.user_id, settings_row=None)
                correct = 0
                for case, memory in lifecycle_cases:
                    db.refresh(memory)
                    if memory.lifecycle_status == case["expected"]:
                        correct += 1
                after_count = db.scalar(
                    select(Memory.memory_id).where(Memory.user_id == user.user_id).limit(1)
                )
                total_memories = len(db.scalars(select(Memory).where(Memory.user_id == user.user_id)).all())
                preservation = before_count is not None and after_count == before_count and total_memories == len(lifecycle_cases)

                # 3. Conflict detection on labelled pairs.
                conflict_correct = 0
                for _label, existing, new_content, category, expected in CONFLICT_CASES:
                    assessment = conflict_detector.detect_conflict(existing, new_content, category)
                    if bool(assessment) == expected:
                        conflict_correct += 1

                # 4. Personalization relevance: baseline vs adaptive.
                memory_rows = db.scalars(
                    select(Memory).where(Memory.user_id == user.user_id, Memory.approval_status == "approved")
                ).all()
                baseline_hits = 0
                adaptive_hits = 0
                adaptive_extra = 0
                adaptive_total = 0
                for query, expected_keys in PERSONALIZATION_CASES:
                    baseline = _baseline_select(db, user.user_id, query, memory_rows)
                    baseline_keys = set()
                    if baseline:
                        baseline_keys = {"baseline_memory"}
                    if baseline_keys == expected_keys:
                        baseline_hits += 1

                    selected = personalization_engine.select_preferences(db, user.user_id, query)
                    selected_keys = {preference.normalized_key for preference in selected}
                    adaptive_total += len(selected_keys)
                    adaptive_extra += len(selected_keys - expected_keys)
                    if selected_keys == expected_keys:
                        adaptive_hits += 1

                # 5. Feedback accuracy.
                feedback_memory = _memory(db, user, "User prefers Python for examples", confidence=0.8)
                feedback_preference = next(
                    preference for preference in preferences
                    if preference.normalized_key == "learning_style:step_by_step"
                )
                original_memory = feedback_memory.content
                original_preference = feedback_preference.description
                feedback_processor.submit_feedback(
                    db, user.user_id,
                    FeedbackCreateRequest(target_type="memory", target_id=feedback_memory.memory_id, feedback_type="correct"),
                )
                feedback_processor.submit_feedback(
                    db, user.user_id,
                    FeedbackCreateRequest(
                        target_type="preference", target_id=feedback_preference.preference_id,
                        feedback_type="incorrect_personalization",
                    ),
                )
                feedback_processor.submit_feedback(
                    db, user.user_id,
                    FeedbackCreateRequest(
                        target_type="memory", target_id=feedback_memory.memory_id,
                        feedback_type="outdated_information",
                    ),
                )
                db.refresh(feedback_memory)
                db.refresh(feedback_preference)
                feedback_correct = sum([
                    feedback_memory.content == original_memory,
                    feedback_preference.description == original_preference,
                    feedback_preference.confidence < 0.8,
                    feedback_memory.lifecycle_status == "possibly_outdated",
                    db.scalar(select(MemoryFeedback).where(MemoryFeedback.user_id == user.user_id)) is not None,
                ])

                # 6. Retrieval and adaptive processing latency.
                baseline_latencies = []
                adaptive_latencies = []
                for _ in range(20):
                    started = time.perf_counter()
                    _baseline_select(db, user.user_id, "Explain binary search step by step", memory_rows)
                    baseline_latencies.append((time.perf_counter() - started) * 1000)
                    started = time.perf_counter()
                    personalization_engine.select_preferences(db, user.user_id, "Explain binary search step by step")
                    adaptive_latencies.append((time.perf_counter() - started) * 1000)

                processing_latencies = []
                for index in range(10):
                    conversation_n = _conversation(db, user, 100 + index)
                    user_message = _message(db, conversation_n, "Please explain Python step by step with practical examples.")
                    assistant_message = _message(db, conversation_n, "Here is a step-by-step answer.", role="assistant")
                    started = time.perf_counter()
                    adaptive_engine.observe_turn(
                        db, user.user_id,
                        conversation_id=conversation_n.conversation_id,
                        user_message_id=user_message.message_id,
                        assistant_message_id=assistant_message.message_id,
                    )
                    processing_latencies.append((time.perf_counter() - started) * 1000)

                return {
                    "dataset": {
                        "preference_utterances": len(POSITIVE_UTTERANCES) + len(NEGATIVE_UTTERANCES),
                        "expected_preferences": sorted(EXPECTED_PREFERENCES),
                        "lifecycle_cases": len(lifecycle_cases),
                        "conflict_pairs": len(CONFLICT_CASES),
                        "personalization_queries": len(PERSONALIZATION_CASES),
                        "feedback_events": 3,
                    },
                    "preference_detection": {
                        "predicted": sorted(predicted),
                        "expected": sorted(EXPECTED_PREFERENCES),
                        "precision": round(precision, 4),
                        "recall": round(recall, 4),
                        "false_preference_rate": round(false_rate, 4),
                    },
                    "outdated_memory_handling": {
                        "accuracy": round(correct / len(lifecycle_cases), 4),
                        "memories_preserved": bool(preservation),
                        "cases": len(lifecycle_cases),
                    },
                    "conflict_detection": {
                        "accuracy": round(conflict_correct / len(CONFLICT_CASES), 4),
                        "pairs": len(CONFLICT_CASES),
                    },
                    "personalization_relevance": {
                        "baseline_exact_match_rate": round(baseline_hits / len(PERSONALIZATION_CASES), 4),
                        "adaptive_exact_match_rate": round(adaptive_hits / len(PERSONALIZATION_CASES), 4),
                        "adaptive_irrelevant_preferences": adaptive_extra,
                        "adaptive_preferences_selected": adaptive_total,
                    },
                    "feedback_processing": {
                        "checks_passed": feedback_correct,
                        "checks_total": 5,
                        "accuracy": round(feedback_correct / 5, 4),
                    },
                    "latency_ms": {
                        "baseline_keyword_scan_avg": round(statistics.mean(baseline_latencies), 3),
                        "adaptive_preference_select_avg": round(statistics.mean(adaptive_latencies), 3),
                        "adaptive_turn_processing_avg": round(statistics.mean(processing_latencies), 3),
                    },
                }
        finally:
            engine.dispose()


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2, sort_keys=True))
