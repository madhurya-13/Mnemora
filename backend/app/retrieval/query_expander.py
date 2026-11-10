"""Small rule-based expansion set; no extra LLM calls or assumed user facts."""

from app.config import settings
from app.schemas.memory import QueryAnalysisResponse

_PROMPTS = {
    "education": "What education or skills has the user explicitly shared?",
    "career": "What career interests or goals has the user shared?",
    "interests": "What interests has the user explicitly mentioned?",
    "preferences": "What preferences has the user explicitly stated?",
    "projects": "What current or past projects has the user described?",
    "goals": "What goals has the user said they are pursuing?",
    "personal": "What relevant personal details has the user chosen to share?",
    "temporary": "What current deadlines or temporary details are relevant?",
}


def expand_query(query: str, analysis: QueryAnalysisResponse) -> list[str]:
    queries = [" ".join(query.split())]
    if not settings.retrieval_query_expansion_enabled or not analysis.requires_memory:
        return queries
    for category in analysis.categories:
        candidate = _PROMPTS.get(category)
        if candidate and candidate.casefold() not in {item.casefold() for item in queries}:
            queries.append(candidate)
        if len(queries) >= settings.retrieval_max_expansions + 1:
            break
    return queries
