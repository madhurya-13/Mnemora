"""Importing this package registers every allowlisted agent tool exactly once."""

from app.agents.tools.registry import registry

from app.agents.tools import (  # noqa: F401  (registration side effects)
    calculator_tool,
    file_analysis_tool,
    knowledge_graph_tool,
    memory_proposal_tool,
    memory_tool,
    planning_tool,
    project_analysis_tool,
    report_generation_tool,
    search_tool,
)

__all__ = ["registry"]
