"""Milestone 8 knowledge graph tests: deterministic, provider-free and user-scoped."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.config import settings
from app.knowledge_graph import (
    entity_extractor,
    graph_builder,
    graph_engine,
    graph_merger,
    graph_retriever,
    graph_traversal,
    graph_visualizer,
    relationship_extractor,
)
from app.knowledge_graph.graph_schemas import ENTITY_TYPES, RELATIONSHIP_TYPES
from app.knowledge_graph.graph_workflow import process_pending_graph_sync
from app.main import app
from app.memory import retriever as memory_retriever
from app.memory import service as memory_service
from app.models.conversation import Conversation
from app.models.graph import (
    GraphEntity,
    GraphHistory,
    GraphMergeRecord,
    GraphRelationship,
    GraphSyncRecord,
)
from app.models.memory import Memory
from app.models.message import Message
from app.models.user import User
from app.services import chat_service

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
def clean_graph_cookie():
    _cookies.clear()
    yield
    _cookies.clear()


def _user(db, name: str = "Owner") -> User:
    user = User(username=name, guest_session_hash=f"hash-{uuid4()}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _memory(
    db,
    user: User,
    content: str,
    *,
    category: str = "projects",
    approval_status: str = "approved",
) -> Memory:
    memory = Memory(
        user_id=user.user_id,
        content=content,
        category=category,
        importance=0.8,
        confidence=0.9,
        memory_type="stable",
        approval_status=approval_status,
        vector_sync_status="synced",
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


def _conversation(db, user: User) -> Conversation:
    conversation = Conversation(user_id=user.user_id, title="Graph test")
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def _message(db, conversation: Conversation, content: str) -> Message:
    message = Message(
        conversation_id=conversation.conversation_id,
        role="user",
        content=content,
        status="completed",
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def _entity(db, user: User, name: str) -> GraphEntity:
    return db.scalar(
        select(GraphEntity).where(
            GraphEntity.user_id == user.user_id, GraphEntity.entity_name == name
        )
    )


def _relationship(db, user: User, relationship_type: str, target_name: str) -> GraphRelationship:
    target = _entity(db, user, target_name)
    return db.scalar(
        select(GraphRelationship).where(
            GraphRelationship.user_id == user.user_id,
            GraphRelationship.relationship_type == relationship_type,
            GraphRelationship.target_entity_id == target.entity_id,
        )
    )


# --- extraction ----------------------------------------------------------------


def test_entity_extraction_recognises_the_required_example():
    text = (
        "I am developing MNEMORA using FastAPI and Next.js. "
        "It is an AI assistant with persistent memory."
    )
    entities = entity_extractor.extract_entities(text)
    found = {(entity.entity_type, entity.name) for entity in entities}
    assert ("project", "MNEMORA") in found
    assert ("technology", "FastAPI") in found
    assert ("technology", "Next.js") in found
    assert ("concept", "Persistent Memory") in found
    assert all(entity.entity_type in ENTITY_TYPES for entity in entities)


def test_relationship_extraction_requires_an_explicit_cue():
    text = "MNEMORA and FastAPI are both interesting."
    entities = entity_extractor.extract_entities(text)
    drafts = relationship_extractor.extract_relationships(text, entities)
    assert drafts == []

    explicit = "I am developing MNEMORA using FastAPI and Next.js."
    drafts = relationship_extractor.extract_relationships(
        explicit, entity_extractor.extract_entities(explicit)
    )
    found = {(draft.source_name, draft.relationship_type, draft.target_name) for draft in drafts}
    assert ("User", "DEVELOPS", "MNEMORA") in found
    assert ("MNEMORA", "BUILT_WITH", "FastAPI") in found
    assert ("MNEMORA", "BUILT_WITH", "Next.js") in found


def test_entity_normalisation_matches_spelling_variants():
    assert graph_merger.normalize_entity_name("Next.js", "technology") == graph_merger.normalize_entity_name(
        "NextJS", "technology"
    )
    assert graph_merger.normalize_entity_name("Next JS", "technology") == graph_merger.normalize_entity_name(
        "next.js", "technology"
    )
    assert graph_merger.normalize_entity_name("MNEMORA project", "project") == "mnemora"
    assert graph_merger.normalize_entity_name("Persistent Memory", "concept") == "persistent memory"


def test_supported_categories_are_extensible_and_complete():
    assert len(ENTITY_TYPES) >= 16
    assert {"DEVELOPS", "BUILT_WITH", "LEARNS", "PREFERS", "HAS_FEATURE"}.issubset(RELATIONSHIP_TYPES)


# --- graph construction --------------------------------------------------------


def test_approved_memory_persists_entities_relationships_and_evidence(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        memory = _memory(
            db,
            user,
            "I am developing MNEMORA using FastAPI and Next.js. "
            "It is an AI assistant with persistent memory.",
        )
        graph_builder.sync_memory(db, user.user_id, memory)

        project = _entity(db, user, "MNEMORA")
        fastapi = _entity(db, user, "FastAPI")
        assert project is not None and project.status == "active"
        assert fastapi is not None and fastapi.status == "active"
        assert str(memory.memory_id) in project.source_memory_ids

        develops = _relationship(db, user, "DEVELOPS", "MNEMORA")
        built_with = _relationship(db, user, "BUILT_WITH", "FastAPI")
        feature = _relationship(db, user, "HAS_FEATURE", "Persistent Memory")
        for relationship in (develops, built_with, feature):
            assert relationship is not None
            assert relationship.status == "active"
            assert str(memory.memory_id) in relationship.evidence_memory_ids
            assert relationship.evidence


def test_repeated_sync_is_idempotent(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        memory = _memory(db, user, "I am developing MNEMORA using FastAPI and Next.js.")
        graph_builder.sync_memory(db, user.user_id, memory)
        counts = (
            db.scalar(select(func.count()).select_from(GraphEntity)),
            db.scalar(select(func.count()).select_from(GraphRelationship)),
        )
        graph_builder.sync_memory(db, user.user_id, memory)
        again = (
            db.scalar(select(func.count()).select_from(GraphEntity)),
            db.scalar(select(func.count()).select_from(GraphRelationship)),
        )
        assert counts == again


def test_alias_spellings_do_not_create_duplicate_entities(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        graph_builder.sync_text(db, user.user_id, "I am using Next.js.", approved=True)
        graph_builder.sync_text(db, user.user_id, "I am using NextJS.", approved=True)
        graph_builder.sync_text(db, user.user_id, "I am using Next JS.", approved=True)
        rows = db.scalars(
            select(GraphEntity).where(
                GraphEntity.user_id == user.user_id,
                GraphEntity.entity_type == "technology",
                GraphEntity.normalized_name == "nextjs",
            )
        ).all()
        assert len(rows) == 1


def test_pending_facts_are_not_retrievable_and_approval_activates_them(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        memory = _memory(
            db,
            user,
            "I am developing MNEMORA using FastAPI and Next.js.",
            approval_status="pending",
        )
        graph_builder.sync_memory(db, user.user_id, memory)
        assert graph_retriever.build_context(
            db, user.user_id, "What technologies am I using in MNEMORA?"
        ) is None

        memory.approval_status = "approved"
        db.commit()
        db.refresh(memory)
        graph_builder.sync_memory(db, user.user_id, memory)
        context = graph_retriever.build_context(
            db, user.user_id, "What technologies am I using in MNEMORA?"
        )
        assert context is not None
        assert "FastAPI" in context
        assert "CONNECTED KNOWLEDGE" in context


def test_approving_a_memory_activates_pending_facts_from_its_source_message(temporary_database):
    factory = temporary_database["factory"]
    with factory() as db:
        user = _user(db)
        conversation = _conversation(db, user)
        message = _message(
            db,
            conversation,
            "I am developing MNEMORA using FastAPI and Next.js. "
            "It is an AI assistant with persistent memory.",
        )
        memory = _memory(
            db,
            user,
            "Using FastAPI and Next.js for the MNEMORA project.",
            approval_status="pending",
        )
        memory.source_conversation_id = conversation.conversation_id
        memory.source_message_ids = [str(message.message_id)]
        db.commit()

        graph_builder.sync_message(db, user.user_id, message.message_id)
        pending = _relationship(db, user, "BUILT_WITH", "FastAPI")
        assert pending is not None and pending.status == "pending_review"

        asyncio.run(memory_service.approve_memory(db, user.user_id, memory.memory_id))

        built_with = _relationship(db, user, "BUILT_WITH", "FastAPI")
        develops = _relationship(db, user, "DEVELOPS", "MNEMORA")
        assert built_with.status == "active"
        assert develops.status == "active"
        assert str(memory.memory_id) in built_with.evidence_memory_ids
        context = graph_retriever.build_context(
            db, user.user_id, "What technologies am I using in MNEMORA?"
        )
        assert context is not None
        assert "FastAPI" in context


def test_message_sync_creates_pending_facts_and_post_turn_worker_processes_them(temporary_database):
    factory = temporary_database["factory"]
    with factory() as db:
        user = _user(db)
        conversation = _conversation(db, user)
        prepared = chat_service.prepare_turn(
            db,
            user.user_id,
            conversation.conversation_id,
            "I am developing MNEMORA using FastAPI and Next.js.",
        )
        chat_service.complete_turn(
            db,
            user.user_id,
            conversation.conversation_id,
            prepared.user_message_id,
            "Great project.",
        )
        record = db.scalar(
            select(GraphSyncRecord).where(GraphSyncRecord.user_id == user.user_id)
        )
        assert record is not None and record.status == "pending"
        user_id = user.user_id

    asyncio.run(process_pending_graph_sync(factory, limit=10))

    with factory() as db:
        project = _entity(db, _user_stub(db, user_id), "MNEMORA")
        record = db.scalar(select(GraphSyncRecord).where(GraphSyncRecord.user_id == user_id))
        assert record.status == "completed"
        assert project is not None
        assert project.status == "pending_review"
        develops = db.scalar(
            select(GraphRelationship).where(
                GraphRelationship.user_id == user_id,
                GraphRelationship.relationship_type == "DEVELOPS",
            )
        )
        assert develops is not None and develops.status == "pending_review"


def _user_stub(db, user_id) -> User:
    return db.get(User, user_id)


# --- retrieval -----------------------------------------------------------------


def test_multi_hop_retrieval_traverses_project_to_technologies(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        memory = _memory(
            db,
            user,
            "I am developing MNEMORA using FastAPI and Next.js. "
            "It is an AI assistant with persistent memory.",
        )
        graph_builder.sync_memory(db, user.user_id, memory)
        context = graph_retriever.build_context(
            db, user.user_id, "What technologies am I using in MNEMORA?"
        )
        assert context is not None
        assert "FastAPI" in context and "Next.js" in context
        assert "INFERRED (2 hops)" in context
        assert "approved memory" in context


def test_project_feature_question_retrieves_connected_features(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        memory = _memory(
            db,
            user,
            "I am developing MNEMORA using FastAPI. It is an AI assistant with persistent memory.",
        )
        graph_builder.sync_memory(db, user.user_id, memory)
        context = graph_retriever.build_context(
            db, user.user_id, "Show me the features connected to my current project."
        )
        assert context is not None
        assert "HAS_FEATURE" in context
        assert "Persistent Memory" in context


def test_temporal_replacement_preserves_history_and_prioritises_current(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        first = _memory(db, user, "I am learning Java.", category="education")
        graph_builder.sync_memory(db, user.user_id, first)
        second = _memory(
            db,
            user,
            "I have switched to Python as my primary programming language.",
            category="education",
        )
        graph_builder.sync_memory(db, user.user_id, second)

        java = _relationship(db, user, "LEARNS", "Java")
        python = _relationship(db, user, "PREFERS", "Python")
        assert java.status == "historical"
        assert java.valid_until is not None
        assert java.superseded_by == python.relationship_id
        assert python.status == "active"

        current = graph_retriever.build_context(
            db, user.user_id, "Which programming language am I currently focusing on?"
        )
        assert current is not None
        assert "Python" in current
        assert "LEARNS→ Java" not in current

        history = graph_retriever.build_context(
            db, user.user_id, "Which programming language did I use previously?"
        )
        assert history is not None
        assert "Java" in history
        assert "HISTORICAL" in history


def test_traversal_respects_depth_and_removes_duplicate_paths(temporary_database):
    factory = temporary_database["factory"]
    with factory() as db:
        user = _user(db)
        memory = _memory(db, user, "I am developing MNEMORA using FastAPI and Next.js.")
        graph_builder.sync_memory(db, user.user_id, memory)
        fastapi = _entity(db, user, "FastAPI")
        pydantic = graph_engine.create_entity(
            db, user.user_id, entity_name="Pydantic", entity_type="technology"
        )
        graph_engine.create_relationship(
            db,
            user.user_id,
            source_entity_id=fastapi.entity_id,
            target_entity_id=pydantic.entity_id,
            relationship_type="DEPENDS_ON",
        )
        seed = _entity(db, user, "MNEMORA")

        shallow = graph_traversal.traverse(db, user.user_id, [seed], max_depth=1)
        assert all(path.depth == 1 for path in shallow.paths)
        assert all(len(path.entity_ids) == 2 for path in shallow.paths)
        assert fastapi.entity_id in {path.entity_ids[-1] for path in shallow.paths}
        assert pydantic.entity_id not in {path.entity_ids[-1] for path in shallow.paths}

        deeper = graph_traversal.traverse(db, user.user_id, [seed], max_depth=2)
        assert any(path.entity_ids[-1] == pydantic.entity_id for path in deeper.paths)
        assert all(path.depth <= 2 for path in deeper.paths)
        keys = [(tuple(path.entity_ids), tuple(path.relationship_ids)) for path in deeper.paths]
        assert len(keys) == len(set(keys))
        assert len({row.relationship_id for row in deeper.edges}) == len(deeper.edges)


# --- security ------------------------------------------------------------------


def test_cross_user_access_is_blocked(temporary_database):
    owner = httpx.Cookies()
    other = httpx.Cookies()

    created = request(
        "POST",
        "/api/v1/graph/entities",
        cookies=owner,
        json={"entity_name": "Private Project", "entity_type": "project"},
    )
    assert created.status_code == 201, created.text
    entity_id = created.json()["entity_id"]

    hidden = request("GET", f"/api/v1/graph/entities/{entity_id}", cookies=other)
    assert hidden.status_code == 404
    patched = request(
        "PATCH",
        f"/api/v1/graph/entities/{entity_id}",
        cookies=other,
        json={"description": "hijacked"},
    )
    assert patched.status_code == 404
    deleted = request("DELETE", f"/api/v1/graph/entities/{entity_id}", cookies=other)
    assert deleted.status_code == 404
    traversed = request(
        "POST",
        "/api/v1/graph/traverse",
        cookies=other,
        json={"start_entity_id": entity_id, "max_depth": 1},
    )
    assert traversed.status_code == 404
    relationships = request(
        "GET", f"/api/v1/graph/relationships?source_entity_id={entity_id}", cookies=other
    )
    assert relationships.status_code == 200
    assert relationships.json()["total"] == 0

    owner_view = request("GET", f"/api/v1/graph/entities/{entity_id}", cookies=owner)
    assert owner_view.status_code == 200


def test_relationship_creation_validates_ownership_pair_and_duplicates(temporary_database):
    owner = httpx.Cookies()
    other = httpx.Cookies()
    project = request(
        "POST",
        "/api/v1/graph/entities",
        cookies=owner,
        json={"entity_name": "MNEMORA", "entity_type": "project"},
    ).json()
    tech = request(
        "POST",
        "/api/v1/graph/entities",
        cookies=owner,
        json={"entity_name": "FastAPI", "entity_type": "technology"},
    ).json()
    private = request(
        "POST",
        "/api/v1/graph/entities",
        cookies=other,
        json={"entity_name": "Other Project", "entity_type": "project"},
    ).json()

    payload = {
        "source_entity_id": project["entity_id"],
        "target_entity_id": tech["entity_id"],
        "relationship_type": "BUILT_WITH",
    }
    created = request("POST", "/api/v1/graph/relationships", cookies=owner, json=payload)
    assert created.status_code == 201, created.text
    duplicate = request("POST", "/api/v1/graph/relationships", cookies=owner, json=payload)
    assert duplicate.status_code == 409
    self_loop = request(
        "POST",
        "/api/v1/graph/relationships",
        cookies=owner,
        json={
            "source_entity_id": project["entity_id"],
            "target_entity_id": project["entity_id"],
            "relationship_type": "RELATED_TO",
        },
    )
    assert self_loop.status_code == 422
    invalid_pair = request(
        "POST",
        "/api/v1/graph/relationships",
        cookies=owner,
        json={
            "source_entity_id": tech["entity_id"],
            "target_entity_id": project["entity_id"],
            "relationship_type": "DEVELOPS",
        },
    )
    assert invalid_pair.status_code == 422
    cross_user = request(
        "POST",
        "/api/v1/graph/relationships",
        cookies=owner,
        json={
            "source_entity_id": project["entity_id"],
            "target_entity_id": private["entity_id"],
            "relationship_type": "RELATED_TO",
        },
    )
    assert cross_user.status_code == 404


# --- CRUD, merge and user control ---------------------------------------------


def test_entity_crud_and_delete_archives_relationships_without_deleting_memories(temporary_database):
    factory = temporary_database["factory"]
    with factory() as db:
        user = _user(db)
        memory = _memory(db, user, "I am developing MNEMORA using FastAPI.")
        graph_builder.sync_memory(db, user.user_id, memory)
        project = _entity(db, user, "MNEMORA")
        entity_id = str(project.entity_id)

    owner = httpx.Cookies()
    # Reuse the same owner by creating fresh manual entities through the API.

    updated = request(
        "POST",
        "/api/v1/graph/entities",
        cookies=owner,
        json={"entity_name": "Temp Entity", "entity_type": "concept"},
    )
    assert updated.status_code == 201
    temp_id = updated.json()["entity_id"]
    patched = request(
        "PATCH",
        f"/api/v1/graph/entities/{temp_id}",
        cookies=owner,
        json={"description": "Edited by the user."},
    )
    assert patched.status_code == 200
    assert patched.json()["description"] == "Edited by the user."

    with factory() as db:
        stored_memory = db.scalar(select(Memory).where(Memory.memory_id == memory.memory_id))
        assert stored_memory is not None
        archived = graph_engine_delete(db, user.user_id, project.entity_id)
        assert archived["relationships_archived"] >= 1
        db.expire_all()
        assert _entity(db, user, "MNEMORA").status == "archived"
        assert all(
            row.status == "archived"
            for row in db.scalars(
                select(GraphRelationship).where(
                    GraphRelationship.user_id == user.user_id,
                    GraphRelationship.target_entity_id == project.entity_id,
                )
            ).all()
        )
        assert db.get(Memory, stored_memory.memory_id) is not None


def graph_engine_delete(db, user_id, entity_id):
    from app.knowledge_graph import graph_engine

    return graph_engine.delete_entity(db, user_id, entity_id)


def test_merge_requires_confirmation_preserves_aliases_and_can_be_undone(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        from app.knowledge_graph import graph_engine

        primary = graph_engine.create_entity(
            db, user.user_id, entity_name="MNEMORA", entity_type="project"
        )
        duplicate = graph_engine.create_entity(
            db, user.user_id, entity_name="Mnemora AI", entity_type="project"
        )
        with pytest.raises(PermissionError):
            graph_engine.merge(
                db,
                user.user_id,
                primary_entity_id=primary.entity_id,
                duplicate_entity_id=duplicate.entity_id,
                confirm_similar=False,
            )
        result = graph_engine.merge(
            db,
            user.user_id,
            primary_entity_id=primary.entity_id,
            duplicate_entity_id=duplicate.entity_id,
            confirm_similar=True,
        )
        assert result["merge_id"] is not None
        db.expire_all()
        duplicate_row = db.get(GraphEntity, duplicate.entity_id)
        primary_row = db.get(GraphEntity, primary.entity_id)
        assert duplicate_row.status == "merged"
        assert duplicate_row.merged_into_id == primary.entity_id
        assert "Mnemora AI" in primary_row.aliases
        record = db.scalar(select(GraphMergeRecord).where(GraphMergeRecord.merge_id == result["merge_id"]))
        assert record.status == "active"

        restored = graph_engine.undo_merge(db, user.user_id, result["merge_id"])
        assert restored.entity_id == duplicate.entity_id
        assert restored.status == "active"
        assert restored.merged_into_id is None
        assert db.get(GraphMergeRecord, result["merge_id"]).status == "undone"


# --- visualization and insights ------------------------------------------------


def test_visualization_supports_filters_search_and_connection_expansion(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        memory = _memory(
            db,
            user,
            "I am developing MNEMORA using FastAPI and Next.js. "
            "It is an AI assistant with persistent memory.",
        )
        graph_builder.sync_memory(db, user.user_id, memory)
        project = _entity(db, user, "MNEMORA")

        full = graph_visualizer.visualization(db, user.user_id)
        assert full["total_nodes"] >= 3
        assert any(edge["relationship_type"] == "BUILT_WITH" for edge in full["edges"])

        technologies = graph_visualizer.visualization(
            db, user.user_id, entity_types={"technology"}
        )
        assert {node["entity_type"] for node in technologies["nodes"]} == {"technology"}
        assert technologies["total_edges"] == 0  # project nodes were filtered out

        searched = graph_visualizer.visualization(db, user.user_id, search="fast")
        assert [node["label"] for node in searched["nodes"]] == ["FastAPI"]

        expanded = graph_visualizer.connections(
            db, user.user_id, project.entity_id, depth=1
        )
        labels = {node["label"] for node in expanded["nodes"]}
        assert "FastAPI" in labels and "Next.js" in labels


def test_insights_are_computed_from_stored_rows(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        memory = _memory(db, user, "I am developing MNEMORA using FastAPI and Next.js.")
        graph_builder.sync_memory(db, user.user_id, memory)
        from app.knowledge_graph import graph_insights

        insights = graph_insights.compute_insights(db, user.user_id)
        assert insights["total_entities"] == db.scalar(
            select(func.count()).select_from(GraphEntity).where(GraphEntity.user_id == user.user_id)
        )
        assert insights["total_relationships"] == db.scalar(
            select(func.count())
            .select_from(GraphRelationship)
            .where(GraphRelationship.user_id == user.user_id)
        )
        assert insights["entity_type_counts"].get("project") == 1
        assert insights["relationship_type_counts"].get("BUILT_WITH") == 2
        assert insights["most_connected_entities"]
        assert insights["growth"]
        assert insights["evidence_coverage"] == 1.0


def test_traversal_endpoint_serializes_relationship_types(temporary_database):
    cookies = httpx.Cookies()
    request("GET", "/api/v1/graph/health", cookies=cookies)
    project = request(
        "POST",
        "/api/v1/graph/entities",
        cookies=cookies,
        json={"entity_name": "MNEMORA", "entity_type": "project"},
    ).json()
    fastapi = request(
        "POST",
        "/api/v1/graph/entities",
        cookies=cookies,
        json={"entity_name": "FastAPI", "entity_type": "technology"},
    ).json()
    created = request(
        "POST",
        "/api/v1/graph/relationships",
        cookies=cookies,
        json={
            "source_entity_id": project["entity_id"],
            "target_entity_id": fastapi["entity_id"],
            "relationship_type": "BUILT_WITH",
        },
    )
    assert created.status_code == 201, created.text
    response = request(
        "POST",
        "/api/v1/graph/traverse",
        cookies=cookies,
        json={"start_entity_id": project["entity_id"], "max_depth": 2},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["paths"]
    assert payload["paths"][0]["relationship_types"] == ["BUILT_WITH"]


def test_traversal_depth_is_bounded_by_configuration(temporary_database):
    owner = httpx.Cookies()
    project = request(
        "POST",
        "/api/v1/graph/entities",
        cookies=owner,
        json={"entity_name": "Depth Project", "entity_type": "project"},
    ).json()
    accepted = request(
        "POST",
        "/api/v1/graph/traverse",
        cookies=owner,
        json={"start_entity_id": project["entity_id"], "max_depth": settings.graph_max_depth},
    )
    assert accepted.status_code == 200
    assert accepted.json()["max_depth"] == settings.graph_max_depth
    rejected = request(
        "POST",
        "/api/v1/graph/traverse",
        cookies=owner,
        json={"start_entity_id": project["entity_id"], "max_depth": settings.graph_max_depth + 1},
    )
    assert rejected.status_code == 422


def test_history_activity_and_rebuild_are_exposed(temporary_database):
    factory = temporary_database["factory"]
    with factory() as db:
        user = _user(db)
        memory = _memory(db, user, "I am developing MNEMORA using FastAPI.")
        graph_builder.sync_memory(db, user.user_id, memory)
        first = graph_builder.rebuild(db, user.user_id)
        second = graph_builder.rebuild(db, user.user_id)
        assert first["entities"] == second["entities"]
        assert first["relationships"] == second["relationships"]
        history = db.scalars(
            select(GraphHistory).where(GraphHistory.user_id == user.user_id)
        ).all()
        assert any(row.action == "rebuild" for row in history)


def test_search_returns_relevant_subgraph(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        memory = _memory(
            db,
            user,
            "I am developing MNEMORA using FastAPI and Next.js. "
            "It is an AI assistant with persistent memory.",
        )
        graph_builder.sync_memory(db, user.user_id, memory)
        result = graph_retriever.search(
            db, user.user_id, "Show all technologies connected to MNEMORA."
        )
        labels = {entity.entity_name for entity in result.subgraph.nodes.values()}
        assert "MNEMORA" in labels
        assert {"FastAPI", "Next.js"} & labels


def test_memory_retrieval_appends_graph_context_without_breaking_existing_blocks(temporary_database):
    with temporary_database["factory"]() as db:
        user = _user(db)
        memory = _memory(db, user, "I am developing MNEMORA using FastAPI.")
        graph_builder.sync_memory(db, user.user_id, memory)
        blocks = asyncio.run(
            memory_retriever.retrieve_context(
                db, user.user_id, "What technologies am I using in MNEMORA?"
            )
        )
        assert any(block.startswith("CONNECTED KNOWLEDGE") for block in blocks)
