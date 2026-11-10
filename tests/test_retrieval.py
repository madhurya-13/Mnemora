"""Deterministic coverage for Milestone 5 retrieval stages; no provider calls."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.memory import Memory
from app.retrieval import context_builder, query_analyzer, query_expander, ranker, recency


def _memory(content: str, *, category: str = "projects", days_old: int = 0) -> Memory:
    now = datetime.now(timezone.utc)
    memory = Memory(
        memory_id=uuid4(), user_id=uuid4(), content=content, category=category,
        importance=0.8, confidence=0.9, memory_type="stable", approval_status="approved",
        vector_sync_status="synced", created_at=now - timedelta(days=days_old),
        updated_at=now - timedelta(days=days_old),
    )
    return memory


def test_query_analysis_expansion_and_general_knowledge_skip():
    analysis = query_analyzer.analyze_query("Suggest a project for my portfolio")
    assert analysis.requires_memory is True
    assert "career" in analysis.categories
    assert "projects" in analysis.categories
    assert len(query_expander.expand_query("Suggest a project for my portfolio", analysis)) > 1
    factual = query_analyzer.analyze_query("What is the capital of France?")
    assert factual.requires_memory is False


def test_rrf_combines_rankings_and_weights_are_normalized():
    fused = ranker.reciprocal_rank_fusion([["a", "b"], ["b", "a"]])
    assert fused["a"] == fused["b"]
    memory = _memory("Build a portfolio website")
    parts = ranker.score_memory(memory, semantic=0.8, keyword=0.5, category_match=1, usage_count=3)
    assert all(0 <= value <= 1 for value in parts.values())
    assert parts["final"] > 0


def test_category_recency_and_token_budget_exclusions():
    old_goal = _memory("Finish certification next month", category="goals", days_old=400)
    old_temp = _memory("Bring documents tomorrow", category="temporary", days_old=400)
    now = datetime.now(timezone.utc)
    assert recency.recency_score(old_goal.updated_at, "goals", "stable", now=now) > recency.recency_score(old_temp.updated_at, "temporary", "stable", now=now)
    first = _memory("Python developer focused on data tools")
    second = _memory("Python developer focused on data tools")
    third = _memory("I am learning another useful framework")
    built = context_builder.build_context([
        {"memory": first, "eligible": True}, {"memory": second, "eligible": True},
        {"memory": third, "eligible": True},
    ], set(), max_items=1)
    assert built["selected"] == [{"memory": first, "eligible": True}]
    assert built["excluded"][str(second.memory_id)] == "duplicate content"
    assert built["excluded"][str(third.memory_id)] == "memory count budget"


def test_unresolved_conflicts_are_omitted_from_context():
    existing = _memory("I prefer Java")
    changed = _memory("I now prefer Python", category="projects")
    pair = frozenset((str(existing.memory_id), str(changed.memory_id)))
    built = context_builder.build_context([
        {"memory": existing, "eligible": True}, {"memory": changed, "eligible": True},
    ], {pair})
    assert built["selected"] == []
    assert all(reason == "unresolved memory conflict" for reason in built["excluded"].values())
