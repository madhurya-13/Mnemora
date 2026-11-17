"""MNEMORA knowledge graph: deterministic extraction, storage, retrieval and API.

The relational database stays authoritative. Graph facts always keep references to
their source memories and are never used to replace Milestone 1–7 memory logic.
Modules are imported directly (``app.knowledge_graph.graph_builder`` etc.) to keep
the dependency graph acyclic.
"""
