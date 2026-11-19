"""Knowledge-graph tools that reuse the Milestone 8 traversal and evidence rules."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.agents.agent_schemas import ToolContext, ToolResult
from app.agents.tools.base_tool import ToolSpec
from app.agents.tools.registry import registry
from app.config import settings
from app.knowledge_graph import graph_engine


class GraphSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    max_depth: int = Field(default=2, ge=1, le=3)
    include_historical: bool = False


def knowledge_graph_search(context: ToolContext, payload: GraphSearchInput) -> ToolResult:
    try:
        result = graph_engine.search(
            context.db,
            context.user_id,
            payload.query,
            max_depth=min(payload.max_depth, settings.graph_max_depth),
            include_historical=payload.include_historical,
        )
    except Exception as error:  # graph failure must be reported, never invented
        return ToolResult(
            ok=False,
            summary="Knowledge graph retrieval failed.",
            error=f"{type(error).__name__}: graph search unavailable",
            error_kind="transient",
        )

    seeds = result.get("matched_entities", []) if isinstance(result, dict) else []
    paths = result.get("paths", []) if isinstance(result, dict) else []
    nodes = result.get("nodes", []) if isinstance(result, dict) else []
    edges = result.get("edges", []) if isinstance(result, dict) else []
    if not seeds:
        return ToolResult(
            ok=True,
            summary="No stored entities matched this question; no relationship was invented.",
            data={"seeds": [], "paths": [], "nodes": [], "edges": [], "matched": False},
        )
    label_list = [seed.get("label") or seed.get("entity_name") for seed in seeds]
    return ToolResult(
        ok=True,
        summary=(
            f"Matched {', '.join(str(label) for label in label_list[:5])} and found {len(paths)} "
            f"evidence-supported path(s)."
        ),
        data={
            "matched": True,
            "seeds": seeds,
            "paths": paths,
            "nodes": nodes,
            "edges": edges,
            "truncated": bool(result.get("truncated")) if isinstance(result, dict) else False,
            "note": "Only active relationships backed by approved-memory or user-confirmed evidence are traversed.",
        },
        evidence=[str(seed.get("id")) for seed in seeds if seed.get("id")],
    )


registry.register(
    ToolSpec(
        name="knowledge_graph_search",
        description="Search user-owned graph entities and traverse evidence-supported relationships.",
        category="knowledge_graph",
        permission="read_only",
        input_model=GraphSearchInput,
        handler=knowledge_graph_search,
        enabled_check=lambda: settings.knowledge_graph_enabled,
        disabled_reason="KNOWLEDGE_GRAPH_ENABLED is false.",
    )
)
