# Milestone 8 — Pre-Implementation Audit

Scope: extend MNEMORA with a persistent, user-scoped knowledge graph without
rebuilding the application or replacing Milestones 1–7.

## 1. Existing memory architecture

| Layer | Implementation |
| --- | --- |
| API | `backend/app/api/memories.py`, `adaptive.py`, `chat.py`, `voice.py`, `conversations.py` |
| Services | `app/memory/service.py` (lifecycle), `workflow.py` (durable jobs), `extractor.py` (LLM extraction), `vector_store.py` + `embeddings.py` (Chroma + providers) |
| Retrieval | `app/retrieval/hybrid_retriever.py` (semantic + keyword + RRF), `ranker.py`, `context_builder.py`, `analyzer`, `expander`, `conflict_detector.py`, `recency.py` |
| Adaptive | `app/services/adaptive_memory/*` (preferences, patterns, decay, evolution, feedback, personalization, durable jobs) |
| Chat | `app/api/chat.py` → `chat_service.prepare_turn/complete_turn` → `llm_service` (Gemini), post-turn background jobs |

Memories are relational rows (`memories`) with approval (`pending/approved/rejected`),
lifecycle (`active/possibly_outdated/superseded/expired/archived/pending_review`),
importance, confidence, source conversation/message references, utility score and
vector sync state. Chroma is only an index; SQL is authoritative.

## 2. Existing entity-like structures

There is no entity model, but information is already categorised and referenced:

- `Memory.category` — personal, education, career, interests, preferences, projects, goals, temporary, other.
- `UserPreference` — confirmed/candidate preference statements with evidence and confidence.
- `MemoryPattern` — recurring topics/projects across conversations.
- `Conversation`/`Message` — stable IDs usable as evidence.
- `MemoryHistory` — version trail for memory evolution.

These map directly onto graph node types (preference, project, goal, interest,
subject, concept) and onto evidence links.

## 3. Existing relationship/reference fields

- `Memory.source_conversation_id`, `source_message_ids`, `similar_memory_id`, `superseded_by`.
- `MemoryHistory.source_conversation_id`, `change_type`.
- `UserPreference.supporting_memory_ids`, `evidence[]`.
- `MemoryPattern.supporting_conversation_ids`, `supporting_message_ids`.
- `MemoryFeedback.memory_ids`, `preference_ids`.
- `MemoryConflict` links two memory rows.

All are reusable as graph evidence. No directed entity-to-entity relation exists yet.

## 4. Existing retrieval pipeline

`retrieve_context(db, user_id, query)` calls:

1. `hybrid_retriever.retrieve` — approved + active + synced memories only; semantic
   (Chroma) and SQL keyword candidates; RRF fusion; weighted ranking; conflict-aware,
   token-budgeted context; audit event in `memory_retrieval_events/items`.
2. `personalization_engine.build_personalization_context` — confirmed preferences,
   relevance filtered.

The graph retriever will add a third context block. It will not replace or rescore
the existing memory pipeline (incompatible raw scores are avoided by emitting a
separate, labelled context block).

## 5. Existing adaptive modules

`preference_learner` (per-user, evidence-based, confirmation required),
`pattern_detector`, `memory_decay`, `memory_evolution`, `feedback_processor`,
`adaptive_settings`, `workflow` (durable, retryable jobs). Graph learning reuses the
same settings (personalization/review gates) and the durable-job pattern.

## 6. Existing database schema

`users`, `conversations`, `messages`, `memories`, `memory_vector_outbox`,
`memory_extraction_jobs`, `memory_history`, `memory_conflicts`,
`memory_retrieval_events`, `memory_retrieval_items`, `adaptive_settings`,
`user_preferences`, `memory_patterns`, `memory_feedback`,
`adaptive_processing_jobs`.

Alembic revisions: `0001` … `0004_adaptive_memory`. SQLite locally, PostgreSQL supported.

## 7. Files that can be reused unchanged

- `app/memory/safety.py` (sensitive-content guard).
- `app/database/base.py` (`Base`, `UTCDateTime`).
- `app/services/session_service.py` (owner resolution).
- `app/services/adaptive_memory/adaptive_settings.py`.
- `app/retrieval/query_analyzer.py` (keyword extraction).
- `app/services/llm_service.py` (reasoning via existing chat context).
- `frontend/lib/api.ts`, Tailwind theme, Memory dashboard patterns.

## 8. Files requiring modification

| File | Change |
| --- | --- |
| `backend/app/config.py` | graph enablement, depth/limit/context settings |
| `backend/app/models/__init__.py` | register graph models |
| `backend/app/main.py` | include graph router, start graph retry worker |
| `backend/app/memory/retriever.py` | append graph context block (failure-safe) |
| `backend/app/api/chat.py` | pass `user_id` to post-turn work and run graph sync |
| `backend/app/services/design?` | none |
| `tests/conftest.py` | no-op graph background worker in HTTP tests |
| `frontend/components/ChatSidebar.tsx` | Knowledge Graph navigation |
| `frontend/components/MemoryDashboard.tsx` | Knowledge Graph navigation |
| `README.md` | Milestone 8 architecture, API, setup, troubleshooting |

Milestone 1–7 behaviour is preserved; all edits are additive.

## 9. New files

Backend:

- `app/models/graph.py` — entities, relationships, history, merges, sync records.
- `app/schemas/graph.py` — validated request/response models.
- `app/knowledge_graph/__init__.py`
- `entity_extractor.py`, `relationship_extractor.py`, `graph_schemas.py` (internal drafts),
  `graph_validator.py`, `graph_merger.py`, `graph_updater.py`, `graph_builder.py`,
  `graph_traversal.py`, `graph_ranker.py`, `graph_retriever.py`, `graph_visualizer.py`,
  `graph_insights.py`, `graph_engine.py`, `graph_workflow.py`
- `app/api/graph.py`
- `alembic/versions/0005_knowledge_graph.py`
- `tests/test_knowledge_graph.py`
- `docs/MILESTONE_8_AUDIT.md`

Frontend:

- `app/graph/page.tsx`
- `components/KnowledgeGraphDashboard.tsx`
- `components/graph/GraphCanvas.tsx`
- `components/graph/GraphDetails.tsx`
- `lib/graph.ts`

## 10. Required dependencies

- Backend: none new. Traversal, ranking and extraction are implemented with the
  standard library + SQLAlchemy, so tests remain provider-free and deterministic.
- Frontend: `@xyflow/react` (React Flow 13) for interactive nodes/edges,
  pan/zoom/drag/selection. Evaluated alternatives: Cytoscape.js (canvas, better for
  thousands of nodes, heavier React integration) and hand-written SVG/canvas
  (no dependency, but re-implements pan/zoom/selection). Expected graph size is tens
  to low hundreds of nodes, where React Flow is the better fit.

No Neo4j: a relational adjacency model with indexed `(user_id, source/target, status)`
supports the required multi-hop depth (≤3) and keeps one authoritative database.
A dedicated graph database would add infrastructure without a demonstrated benefit
at this scale. This is documented as a deliberate trade-off.

## 11. Migration requirements

One additive revision `0005_knowledge_graph` creating:

- `graph_entities` (unique identity per user/type/normalised name; evidence JSON; status).
- `graph_relationships` (directed edges, temporal validity, evidence, supersession).
- `graph_history` (immutable audit trail).
- `graph_merge_records` (merge snapshots for undo).
- `graph_sync_records` (idempotent per-memory / per-message build state).

No existing table or column is altered or dropped. Existing data is preserved.

## 12. Design decisions

- **SQLite/SQLAlchemy graph storage**, indexed for owner-scoped traversal.
- **Two-stage evidence** — graph facts from conversations start as `pending_review`;
  approval of a memory activates matching facts. Retrieval additionally verifies that
  a fact is supported by an approved memory (or is user-confirmed), so a stale status
  can never leak pending memory content into answers.
- **Deterministic extraction** requiring an explicit verb/connective, so two entities in
  one sentence never imply a relationship. No LLM is used to invent edges.
- **Temporal updates only on explicit language** (“switched to”, “no longer”); historical
  edges are retained with `valid_until` and `superseded_by`.
- **Conservative resolution** — exact/normalised/alias matches only; uncertain merges
  require an explicit API/UI confirmation and are undoable.
- **Additive retrieval** — graph context is a separate labelled block; the Milestone 5
  ranker is untouched.
