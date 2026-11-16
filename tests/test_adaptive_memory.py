"""Milestone 7 adaptive memory tests: deterministic, provider-free and user-scoped."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.main import app
from app.memory import service as memory_service
from app.models.adaptive import (
    AdaptiveProcessingJob,
    AdaptiveSettings,
    MemoryFeedback,
    MemoryPattern,
    UserPreference,
)
from app.models.conversation import Conversation
from app.models.memory import (
    Memory,
    MemoryHistory,
    MemoryRetrievalEvent,
    MemoryRetrievalItem,
)
from app.models.message import Message
from app.models.user import User
from app.schemas.adaptive import FeedbackCreateRequest
from app.services.adaptive_memory import (
    feedback_processor,
    memory_decay,
    memory_evolution,
    pattern_detector,
    personalization_engine,
    preference_learner,
    workflow,
)
from app.services.adaptive_memory.adaptive_settings import get_adaptive_settings

_cookies = httpx.Cookies()


def request(method: str, path: str, *, cookies: httpx.Cookies | None = None, **kwargs):
    jar = cookies if cookies is not None else _cookies

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", cookies=jar
        ) as client:
            response = await client.request(method, path, **kwargs)
            jar.update(response.cookies)
            return response

    return asyncio.run(run())


@pytest.fixture(autouse=True)
def clean_adaptive_cookie():
    _cookies.clear()
    yield
    _cookies.clear()


def _user(db, name: str = "Owner") -> User:
    user = User(username=name, guest_session_hash=f"hash-{uuid4()}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _conversation(db, user: User, title: str = "Test chat") -> Conversation:
    conversation = Conversation(user_id=user.user_id, title=title)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def _message(db, conversation: Conversation, content: str, role: str = "user") -> Message:
    message = Message(
        conversation_id=conversation.conversation_id, role=role, content=content, status="completed"
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def _memory(
    db,
    user: User,
    content: str,
    *,
    category: str = "preferences",
    approval_status: str = "approved",
    importance: float = 0.8,
    confidence: float = 0.9,
    memory_type: str = "stable",
    updated_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> Memory:
    now = datetime.now(timezone.utc)
    memory = Memory(
        user_id=user.user_id,
        content=content,
        category=category,
        importance=importance,
        confidence=confidence,
        memory_type=memory_type,
        approval_status=approval_status,
        vector_sync_status="synced",
        created_at=updated_at or now,
        updated_at=updated_at or now,
        expires_at=expires_at,
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


def _preference(db, user: User, *, key="learning_style:step_by_step", status="candidate", confidence=0.8, evidence=3):
    descriptions = {
        "learning_style:step_by_step": "Prefers step-by-step explanations.",
        "programming:python": "Prefers Python examples and implementations.",
        "content:summaries": "Prefers concise summaries with key points.",
        "ui_ux:interface_quality": "Prefers polished, responsive and accessible interfaces.",
    }
    preference = UserPreference(
        user_id=user.user_id,
        category=key.split(":")[0],
        description=descriptions.get(key, "Prefers step-by-step explanations."),
        normalized_key=key,
        confidence=confidence,
        evidence_count=evidence,
        supporting_memory_ids=[],
        evidence=[{"message_id": None, "conversation_id": None, "excerpt": "step by step", "observed_at": datetime.now(timezone.utc).isoformat()}],
        status=status,
    )
    db.add(preference)
    db.commit()
    db.refresh(preference)
    return preference


# --- preference learning -------------------------------------------------------


def test_single_observation_never_confirms_a_preference(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        updates = preference_learner.learn_from_message(
            db, user.user_id, "I prefer step-by-step explanations.",
            conversation_id=None, message_id=None,
            confidence_threshold=0.6, evidence_threshold=3, require_user_review=True,
        )
        preference = db.scalar(select(UserPreference).where(UserPreference.user_id == user.user_id))
        assert updates == 1
        assert preference is not None
        assert preference.status == "candidate"
        assert preference.evidence_count == 1
        assert preference.confidence < 0.6
        assert len(preference.evidence) == 1


def test_repeated_evidence_raises_confidence_and_can_confirm(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        for _ in range(2):
            preference_learner.learn_from_message(
                db, user.user_id, "Please explain with simple steps and an example.",
                conversation_id=None, message_id=None,
                confidence_threshold=0.6, evidence_threshold=3, require_user_review=True,
            )
        preference = db.scalar(select(UserPreference).where(UserPreference.normalized_key == "learning_style:step_by_step"))
        assert preference.evidence_count == 2
        assert preference.confidence >= 0.5
        assert preference.status == "candidate"

        preference_learner.learn_from_message(
            db, user.user_id, "Keep explanations step by step.",
            conversation_id=None, message_id=None,
            confidence_threshold=0.6, evidence_threshold=3, require_user_review=False,
        )
        db.refresh(preference)
        assert preference.evidence_count == 3
        assert preference.confidence >= 0.6
        assert preference.status == "confirmed"


def test_context_scoped_sensitive_and_bare_mentions_are_ignored():
    assert preference_learner.extract_signals("For this project, give me concise answers.") == []
    assert preference_learner.extract_signals("My password is hunter2 and I prefer concise answers.") == []
    assert preference_learner.extract_signals("Python is a programming language.") == []


def test_conflicting_preference_is_re_evaluated_not_silently_replaced(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        for _ in range(2):
            preference_learner.learn_from_message(
                db, user.user_id, "I prefer concise answers.",
                conversation_id=None, message_id=None,
                confidence_threshold=0.6, evidence_threshold=3, require_user_review=True,
            )
        concise = db.scalar(select(UserPreference).where(UserPreference.normalized_key == "communication_style:concise"))
        assert concise is not None
        before = concise.confidence
        preference_learner.learn_from_message(
            db, user.user_id, "I prefer detailed explanations.",
            conversation_id=None, message_id=None,
            confidence_threshold=0.6, evidence_threshold=3, require_user_review=True,
        )
        detailed = db.scalar(select(UserPreference).where(UserPreference.normalized_key == "communication_style:detailed"))
        db.refresh(concise)
        assert detailed is not None and detailed.status == "candidate"
        assert concise.confidence < before
        assert concise.status == "candidate"
        assert concise.description == "Prefers concise answers with only the necessary steps."


def test_preference_api_confirm_reject_delete_and_user_isolation(temporary_database):
    assert request("GET", "/api/v1/memories/preferences").status_code == 200
    with temporary_database["factory"]() as db:
        user = db.scalar(select(User))
        preference = _preference(db, user)
        preference_id = str(preference.preference_id)

    listed = request("GET", "/api/v1/memories/preferences")
    assert listed.status_code == 200 and listed.json()["total"] == 1

    other = httpx.Cookies()
    assert request("GET", "/api/v1/memories/preferences", cookies=other).json()["total"] == 0
    assert request("POST", f"/api/v1/memories/preferences/{preference_id}/confirm", cookies=other).status_code == 404

    confirmed = request("POST", f"/api/v1/memories/preferences/{preference_id}/confirm", json={"description": "Prefers guided practice."})
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["description"] == "Prefers guided practice."

    edited = request("PUT", f"/api/v1/memories/preferences/{preference_id}", json={"category": "communication_style"})
    assert edited.status_code == 200 and edited.json()["category"] == "communication_style"

    rejected = request("POST", f"/api/v1/memories/preferences/{preference_id}/reject")
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"

    deleted = request("DELETE", f"/api/v1/memories/preferences/{preference_id}")
    assert deleted.status_code == 200 and deleted.json() == {"deleted": True}
    assert request("GET", "/api/v1/memories/preferences").json()["total"] == 0


def test_sensitive_preference_edit_is_rejected(temporary_database):
    assert request("GET", "/api/v1/memories/preferences").status_code == 200
    with temporary_database["factory"]() as db:
        user = db.scalar(select(User))
        preference = _preference(db, user)
        preference_id = str(preference.preference_id)
    response = request(
        "PUT", f"/api/v1/memories/preferences/{preference_id}",
        json={"description": "My password is hunter2"},
    )
    assert response.status_code == 422


# --- memory evolution ----------------------------------------------------------


def test_memory_update_preserves_history_and_exposes_evolution_timeline(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        memory = _memory(db, user, "User prefers Java")
        updated = memory_service.update_memory(
            db, user.user_id, memory.memory_id, {"content": "User now prefers Python"}
        )
        assert updated.content == "User now prefers Python"
        history = db.scalars(select(MemoryHistory).where(MemoryHistory.memory_id == memory.memory_id)).all()
        assert len(history) == 1
        assert history[0].content == "User prefers Java"
        assert history[0].change_type == "preference_modification"
        assert db.get(Memory, memory.memory_id) is not None

        timeline = memory_evolution.evolution_timeline(db, user.user_id, memory_id=memory.memory_id)
        assert len(timeline) == 1
        assert timeline[0]["previous_content"] == "User prefers Java"
        assert timeline[0]["new_content"] == "User now prefers Python"
        assert timeline[0]["change_type"] == "preference_modification"


def test_change_classification_handles_ambiguity_conservatively():
    assert memory_evolution.classify_change("User is learning Java", "I have shifted focus to Python", "education") == "confirmed_replacement"
    assert memory_evolution.classify_change("User likes tea", "User no longer likes tea", "preferences") == "outdated_information"
    assert memory_evolution.classify_change("User goal A", "I have changed my goal to B", "goals") == "goal_modification"
    assert memory_evolution.classify_change("Same", "Same", "preferences") == "user_update"


def test_evolution_api_is_owner_scoped(temporary_database):
    assert request("GET", "/api/v1/memories/evolution").status_code == 200
    with temporary_database["factory"]() as db:
        user = db.scalar(select(User))
        memory = _memory(db, user, "User prefers Java")
        memory_service.update_memory(db, user.user_id, memory.memory_id, {"content": "User now prefers Python"})
    mine = request("GET", "/api/v1/memories/evolution")
    assert mine.status_code == 200 and mine.json()["total"] == 1
    other = httpx.Cookies()
    assert request("GET", "/api/v1/memories/evolution", cookies=other).json()["total"] == 0


# --- decay and health ----------------------------------------------------------


def test_utility_score_is_normalized_and_components_are_documented():
    assert abs(sum(memory_decay.UTILITY_WEIGHTS.values()) - 1.0) < 1e-9
    now = datetime.now(timezone.utc)
    memory = Memory(
        user_id=uuid4(), content="User is learning Python", category="education",
        importance=0.8, confidence=0.9, memory_type="stable", approval_status="approved",
        created_at=now, updated_at=now,
    )
    score = memory_decay.calculate_utility(memory, usage_count=4, positive_feedback=2, negative_feedback=0, now=now)
    assert 0.0 <= score <= 1.0
    assert score > 0.5


def test_decay_expires_and_archives_without_deleting(temporary_database):
    now = datetime.now(timezone.utc)
    with temporary_database["factory"]() as db:
        user = _user(db)
        expired = _memory(
            db, user, "Temporary task due yesterday", category="temporary", memory_type="temporary",
            importance=0.2, confidence=0.5, updated_at=now - timedelta(days=30),
            expires_at=now - timedelta(days=1),
        )
        archived = _memory(db, user, "Old archived preference", category="preferences")
        archived.lifecycle_status = "archived"
        archived.archived_at = now
        db.commit()
        stable = _memory(db, user, "User is studying computer science", category="education")
        stale = _memory(
            db, user, "User has a short-term errand", category="temporary", memory_type="temporary",
            importance=0.1, confidence=0.3, updated_at=now - timedelta(days=900),
        )

        evaluated = memory_decay.evaluate_user(db, user.user_id, settings_row=get_adaptive_settings(db, user.user_id))
        assert evaluated == 4
        assert db.get(Memory, expired.memory_id).lifecycle_status == "expired"
        assert db.get(Memory, archived.memory_id).lifecycle_status == "archived"
        assert db.get(Memory, stable.memory_id).lifecycle_status == "active"
        assert db.get(Memory, stale.memory_id).lifecycle_status in {"possibly_outdated", "active"}
        assert db.scalar(select(func.count(Memory.memory_id)).where(Memory.user_id == user.user_id)) == 4
        assert db.get(Memory, expired.memory_id).utility_score <= 1.0

        health = memory_decay.memory_health(db, user.user_id)
        assert health["total_approved"] == 4
        assert health["expired"] == 1 and health["archived"] == 1
        assert health["last_evaluated_at"] is not None


def test_archiving_a_memory_keeps_it_recoverable(temporary_database):
    assert request("GET", "/api/v1/memories").status_code == 200
    with temporary_database["factory"]() as db:
        user = db.scalar(select(User))
        memory = _memory(db, user, "User prefers dark mode")
        memory_id = str(memory.memory_id)
    archived = request("POST", f"/api/v1/memories/{memory_id}/lifecycle", json={"status": "archived"})
    assert archived.status_code == 200 and archived.json()["lifecycle_status"] == "archived"
    restored = request("POST", f"/api/v1/memories/{memory_id}/lifecycle", json={"status": "active"})
    assert restored.status_code == 200 and restored.json()["lifecycle_status"] == "active"
    assert request("GET", f"/api/v1/memories/{memory_id}").status_code == 200
    other = httpx.Cookies()
    assert request("POST", f"/api/v1/memories/{memory_id}/lifecycle", cookies=other, json={"status": "archived"}).status_code == 404


def test_rejected_and_pending_memories_never_enter_approved_counts(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        _memory(db, user, "Pending fact", approval_status="pending")
        _memory(db, user, "Rejected fact", approval_status="rejected")
        _memory(db, user, "Approved fact")
        memory_decay.evaluate_user(db, user.user_id, settings_row=get_adaptive_settings(db, user.user_id))
        health = memory_decay.memory_health(db, user.user_id)
        assert health["total_approved"] == 1


# --- patterns ------------------------------------------------------------------


def test_pattern_detection_requires_distinct_conversations_and_is_idempotent(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        first = _conversation(db, user, "One")
        second = _conversation(db, user, "Two")
        _message(db, first, "I need help with the MNEMORA project planning milestone.")
        _message(db, second, "The MNEMORA project needs testing and a roadmap.")

        detected = pattern_detector.detect_patterns(db, user.user_id, evidence_threshold=2)
        assert detected >= 1
        patterns = db.scalars(select(MemoryPattern).where(MemoryPattern.user_id == user.user_id)).all()
        assert len(patterns) == detected
        assert all(len(pattern.supporting_conversation_ids) >= 2 for pattern in patterns)
        count_before = len(patterns)

        pattern_detector.detect_patterns(db, user.user_id, evidence_threshold=2)
        assert db.scalar(select(func.count(MemoryPattern.pattern_id)).where(MemoryPattern.user_id == user.user_id)) == count_before


def test_single_conversation_burst_does_not_create_a_pattern(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        conversation = _conversation(db, user)
        for _ in range(4):
            _message(db, conversation, "We are discussing the MNEMORA project today.")
        assert pattern_detector.detect_patterns(db, user.user_id, evidence_threshold=2) == 0


def test_pattern_confirm_and_dismiss_api_is_owner_scoped(temporary_database):
    assert request("GET", "/api/v1/memories/patterns").status_code == 200
    with temporary_database["factory"]() as db:
        user = db.scalar(select(User))
        pattern = MemoryPattern(
            user_id=user.user_id, pattern_type="recurring_interest",
            description="Recurring interest: testing", normalized_key="testing",
            evidence_count=3, confidence=0.6,
            supporting_conversation_ids=[str(uuid4()), str(uuid4())],
            supporting_message_ids=[],
        )
        db.add(pattern)
        db.commit()
        pattern_id = str(pattern.pattern_id)
    confirmed = request("POST", f"/api/v1/memories/patterns/{pattern_id}/confirm")
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
    dismissed = request("POST", f"/api/v1/memories/patterns/{pattern_id}/dismiss")
    assert dismissed.status_code == 200 and dismissed.json()["status"] == "dismissed"
    other = httpx.Cookies()
    assert request("POST", f"/api/v1/memories/patterns/{pattern_id}/confirm", cookies=other).status_code == 404


# --- feedback ------------------------------------------------------------------


def test_feedback_is_recorded_and_does_not_overwrite_memory_content(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        memory = _memory(db, user, "User prefers Python", confidence=0.8)
        original_content = memory.content
        feedback = feedback_processor.submit_feedback(
            db, user.user_id,
            FeedbackCreateRequest(
                target_type="memory", target_id=memory.memory_id, feedback_type="correct",
            ),
        )
        db.refresh(memory)
        assert memory.content == original_content
        assert memory.confidence > 0.8
        assert feedback.memory_ids == [str(memory.memory_id)]
        assert db.scalar(select(func.count(MemoryFeedback.feedback_id))) == 1

        with pytest.raises(feedback_processor.FeedbackConflictError):
            feedback_processor.submit_feedback(
                db, user.user_id,
                FeedbackCreateRequest(
                    target_type="memory", target_id=memory.memory_id, feedback_type="correct",
                ),
            )


def test_incorrect_personalization_feedback_lowers_preference_confidence(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        preference = _preference(db, user, status="confirmed", confidence=0.8)
        feedback_processor.submit_feedback(
            db, user.user_id,
            FeedbackCreateRequest(
                target_type="preference", target_id=preference.preference_id,
                feedback_type="incorrect_personalization",
            ),
        )
        db.refresh(preference)
        assert preference.confidence == 0.75
        assert preference.description == "Prefers step-by-step explanations."


def test_response_feedback_links_latest_retrieval_event(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        conversation = _conversation(db, user)
        assistant = _message(db, conversation, "Here is your answer.", role="assistant")
        memory = _memory(db, user, "User is building MNEMORA")
        event = MemoryRetrievalEvent(
            user_id=user.user_id, intent="project_help", query_type="personal",
            candidate_count=1, selected_count=1, excluded_count=0, latency_ms=4.0,
        )
        db.add(event)
        db.flush()
        db.add(MemoryRetrievalItem(
            event_id=event.event_id, memory_id=memory.memory_id, rank=1, selected=True,
            reason="semantic match",
        ))
        db.commit()

        feedback = feedback_processor.submit_feedback(
            db, user.user_id,
            FeedbackCreateRequest(
                target_type="response", target_id=assistant.message_id,
                feedback_type="helpful", conversation_id=conversation.conversation_id,
            ),
        )
        assert feedback.memory_ids == [str(memory.memory_id)]
        assert feedback.message_id == assistant.message_id


def test_feedback_api_duplicate_and_cross_user_handling(temporary_database):
    assert request("GET", "/api/v1/memories").status_code == 200
    with temporary_database["factory"]() as db:
        user = db.scalar(select(User))
        memory = _memory(db, user, "User prefers Python")
        memory_id = str(memory.memory_id)
    payload = {"target_type": "memory", "target_id": memory_id, "feedback_type": "important"}
    assert request("POST", "/api/v1/memories/feedback", json=payload).status_code == 201
    assert request("POST", "/api/v1/memories/feedback", json=payload).status_code == 409
    insights = request("GET", "/api/v1/memories/feedback/insights").json()
    assert insights["total"] == 1
    other = httpx.Cookies()
    assert request("POST", "/api/v1/memories/feedback", cookies=other, json=payload).status_code == 404


# --- personalization -----------------------------------------------------------


def test_personalization_selects_relevant_confirmed_preferences_only(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        _preference(db, user, key="learning_style:step_by_step", status="confirmed", confidence=0.8)
        _preference(db, user, key="programming:python", status="confirmed", confidence=0.8)
        _preference(db, user, key="content:summaries", status="candidate", confidence=0.8)
        _preference(db, user, key="ui_ux:interface_quality", status="rejected", confidence=0.8)

        selected = personalization_engine.select_preferences(db, user.user_id, "Explain binary search step by step")
        keys = {preference.normalized_key for preference in selected}
        assert "learning_style:step_by_step" in keys
        assert "programming:python" not in keys
        assert "content:summaries" not in keys
        assert "ui_ux:interface_quality" not in keys

        context = personalization_engine.build_personalization_context(db, user.user_id, "Explain binary search step by step")
        assert context is not None and "step-by-step" in context
        assert "RELEVANT USER PREFERENCES" in context

        assert personalization_engine.select_preferences(db, user.user_id, "What is the capital of Japan?") == []
        assert personalization_engine.build_personalization_context(db, user.user_id, "What is the capital of Japan?") is None


def test_disabled_personalization_returns_no_context(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        _preference(db, user, key="learning_style:step_by_step", status="confirmed", confidence=0.8)
        settings_row = get_adaptive_settings(db, user.user_id)
        settings_row.personalization_enabled = False
        db.commit()
        assert personalization_engine.build_personalization_context(db, user.user_id, "Explain binary search step by step") is None


# --- settings, jobs and isolation ---------------------------------------------


def test_adaptive_settings_api_persists_per_user(temporary_database):
    assert request("GET", "/api/v1/memories/adaptive-settings").status_code == 200
    changed = request("PUT", "/api/v1/memories/adaptive-settings", json={
        "preference_learning_enabled": False,
        "personalization_enabled": False,
        "preference_evidence_threshold": 5,
    })
    assert changed.status_code == 200
    body = changed.json()
    assert body["preference_learning_enabled"] is False
    assert body["personalization_enabled"] is False
    assert body["preference_evidence_threshold"] == 5
    assert request("GET", "/api/v1/memories/adaptive-settings").json() == body

    other = httpx.Cookies()
    other_settings = request("GET", "/api/v1/memories/adaptive-settings", cookies=other).json()
    assert other_settings["preference_learning_enabled"] is True


def test_disabled_preference_learning_creates_no_new_preferences(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        conversation = _conversation(db, user)
        user_message = _message(db, conversation, "I prefer concise answers.")
        assistant_message = _message(db, conversation, "Understood.", role="assistant")
        settings_row = get_adaptive_settings(db, user.user_id)
        settings_row.preference_learning_enabled = False
        db.commit()

        from app.services.adaptive_memory import adaptive_engine
        result = adaptive_engine.observe_turn(
            db, user.user_id,
            conversation_id=conversation.conversation_id,
            user_message_id=user_message.message_id,
            assistant_message_id=assistant_message.message_id,
        )
        assert result["preferences"] == 0
        assert db.scalar(select(func.count(UserPreference.preference_id)).where(UserPreference.user_id == user.user_id)) == 0


def test_adaptive_job_processing_is_idempotent(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        conversation = _conversation(db, user)
        user_message = _message(db, conversation, "I prefer concise answers.")
        assistant_message = _message(db, conversation, "Noted.", role="assistant")
        job = AdaptiveProcessingJob(
            user_id=user.user_id, conversation_id=conversation.conversation_id,
            user_message_id=user_message.message_id,
            assistant_message_id=assistant_message.message_id,
            status="pending",
        )
        db.add(job)
        db.commit()
        job_id = job.job_id

    processed = asyncio.run(workflow.process_adaptive_jobs(temporary_database["factory"]))
    assert processed == 1
    with temporary_database["factory"]() as db:
        assert db.get(AdaptiveProcessingJob, job_id).status == "completed"
        assert db.scalar(select(func.count(UserPreference.preference_id))) >= 1
    assert asyncio.run(workflow.process_adaptive_jobs(temporary_database["factory"])) == 0


def test_adaptive_status_and_manual_processing_api(temporary_database):
    assert request("GET", "/api/v1/memories/adaptive/status").status_code == 200
    with temporary_database["factory"]() as db:
        user = db.scalar(select(User))
        _memory(db, user, "User is building a retrieval pipeline", category="projects")
    result = request("POST", "/api/v1/memories/adaptive/process")
    assert result.status_code == 200
    body = result.json()
    assert body["evaluated_memories"] >= 1
    assert set(body) == {"processed_jobs", "evaluated_memories", "detected_patterns"}


def test_health_and_settings_are_isolated_between_users(temporary_database):
    assert request("GET", "/api/v1/memories/health").status_code == 200
    with temporary_database["factory"]() as db:
        owner = db.scalar(select(User))
        _memory(db, owner, "Owner-only insight", category="projects")
    assert request("GET", "/api/v1/memories/health").json()["total_approved"] == 1
    other = httpx.Cookies()
    assert request("GET", "/api/v1/memories/health", cookies=other).json()["total_approved"] == 0
    assert request("GET", "/api/v1/memories/patterns", cookies=other).json()["total"] == 0


def test_feedback_cannot_target_another_users_response(temporary_database):
    assert request("GET", "/api/v1/memories").status_code == 200
    with temporary_database["factory"]() as db:
        owner = db.scalar(select(User))
        conversation = _conversation(db, owner)
        assistant = _message(db, conversation, "Private answer", role="assistant")
        assistant_id = str(assistant.message_id)
    other = httpx.Cookies()
    assert request("GET", "/api/v1/memories", cookies=other).status_code == 200
    response = request("POST", "/api/v1/memories/feedback", cookies=other, json={
        "target_type": "response", "target_id": assistant_id, "feedback_type": "helpful",
    })
    assert response.status_code == 404
