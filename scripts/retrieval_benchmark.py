"""Small deterministic benchmark for retrieval ranking (no database or API keys)."""

from dataclasses import dataclass

from app.retrieval.ranker import reciprocal_rank_fusion


@dataclass(frozen=True)
class Case:
    query: str
    expected: str
    sql_order: tuple[str, ...]
    semantic_order: tuple[str, ...]


CASES = (
    Case("study planner courses", "study", ("study", "job", "hobby", "travel", "finance"), ("study", "hobby", "job", "travel", "finance")),
    Case("python portfolio project", "portfolio", ("job", "portfolio", "travel", "study", "finance"), ("portfolio", "job", "travel", "study", "finance")),
    Case("preferred explanation examples", "preference", ("study", "preference", "project", "travel", "finance"), ("preference", "study", "project", "travel", "finance")),
    Case("upcoming deadline", "deadline", ("deadline", "goal", "study", "travel", "finance"), ("deadline", "goal", "study", "travel", "finance")),
    Case("career interview", "career", ("career", "portfolio", "project", "travel", "finance"), ("portfolio", "career", "project", "travel", "finance")),
)


def main() -> None:
    recalls, reciprocal_ranks = [], []
    for case in CASES:
        fused = reciprocal_rank_fusion([list(case.sql_order), list(case.semantic_order)])
        ranked = sorted(fused, key=fused.get, reverse=True)
        rank = ranked.index(case.expected) + 1 if case.expected in ranked else len(ranked) + 1
        recalls.append(float(case.expected in ranked[:3]))
        reciprocal_ranks.append(1 / rank)
    print(f"cases={len(CASES)}")
    print(f"recall@3={sum(recalls) / len(recalls):.3f}")
    print(f"mrr={sum(reciprocal_ranks) / len(reciprocal_ranks):.3f}")
    print("scope=deterministic synthetic SQL/semantic rankings fused with production RRF")


if __name__ == "__main__":
    main()
