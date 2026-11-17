"""Deterministic entity extraction from user text.

Only names that are explicitly present in the text are returned. Known technology
and concept names are matched from a curated lexicon; projects, goals, locations,
organisations and people additionally require an explicit grammatical cue such as
"developing X", "my goal is to X" or "I live in X". No LLM is involved, so the same
text always produces the same entities and tests never need a provider.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.knowledge_graph.graph_schemas import EntityMention

# variant (lower-case) -> (canonical display name, entity type)
_KNOWN: dict[str, tuple[str, str]] = {
    # technologies / frameworks / tools
    "fastapi": ("FastAPI", "technology"),
    "next.js": ("Next.js", "technology"),
    "nextjs": ("Next.js", "technology"),
    "next js": ("Next.js", "technology"),
    "react": ("React", "technology"),
    "react flow": ("React Flow", "technology"),
    "vue": ("Vue", "technology"),
    "angular": ("Angular", "technology"),
    "tailwind css": ("Tailwind CSS", "technology"),
    "tailwind": ("Tailwind CSS", "technology"),
    "node.js": ("Node.js", "technology"),
    "nodejs": ("Node.js", "technology"),
    "express": ("Express", "technology"),
    "django": ("Django", "technology"),
    "flask": ("Flask", "technology"),
    "spring boot": ("Spring Boot", "technology"),
    "spring": ("Spring", "technology"),
    "sqlalchemy": ("SQLAlchemy", "technology"),
    "alembic": ("Alembic", "technology"),
    "chromadb": ("ChromaDB", "technology"),
    "chroma": ("ChromaDB", "technology"),
    "postgresql": ("PostgreSQL", "technology"),
    "postgres": ("PostgreSQL", "technology"),
    "sqlite": ("SQLite", "technology"),
    "mongodb": ("MongoDB", "technology"),
    "redis": ("Redis", "technology"),
    "neo4j": ("Neo4j", "technology"),
    "cypher": ("Cypher", "technology"),
    "docker": ("Docker", "technology"),
    "kubernetes": ("Kubernetes", "technology"),
    "aws": ("AWS", "technology"),
    "azure": ("Azure", "technology"),
    "google cloud": ("Google Cloud", "technology"),
    "gemini": ("Gemini", "technology"),
    "openai": ("OpenAI", "organization"),
    "langchain": ("LangChain", "technology"),
    "tensorflow": ("TensorFlow", "technology"),
    "pytorch": ("PyTorch", "technology"),
    "hugging face": ("Hugging Face", "technology"),
    "vitest": ("Vitest", "tool"),
    "pytest": ("pytest", "tool"),
    "playwright": ("Playwright", "tool"),
    "react testing library": ("React Testing Library", "tool"),
    "git": ("Git", "tool"),
    "github": ("GitHub", "tool"),
    "vs code": ("VS Code", "tool"),
    "visual studio code": ("VS Code", "tool"),
    "figma": ("Figma", "tool"),
    "jira": ("Jira", "tool"),
    "notion": ("Notion", "tool"),
    # programming languages
    "python": ("Python", "programming_language"),
    "java": ("Java", "programming_language"),
    "javascript": ("JavaScript", "programming_language"),
    "typescript": ("TypeScript", "programming_language"),
    "c++": ("C++", "programming_language"),
    "c#": ("C#", "programming_language"),
    "golang": ("Go", "programming_language"),
    "rust": ("Rust", "programming_language"),
    "sql": ("SQL", "programming_language"),
    "html": ("HTML", "programming_language"),
    "css": ("CSS", "programming_language"),
    "kotlin": ("Kotlin", "programming_language"),
    "swift": ("Swift", "programming_language"),
    # concepts
    "persistent memory": ("Persistent Memory", "concept"),
    "semantic memory": ("Semantic Memory", "concept"),
    "knowledge graph": ("Knowledge Graph", "concept"),
    "artificial intelligence": ("Artificial Intelligence", "concept"),
    "ai": ("Artificial Intelligence", "concept"),
    "machine learning": ("Machine Learning", "concept"),
    "deep learning": ("Deep Learning", "concept"),
    "natural language processing": ("Natural Language Processing", "concept"),
    "retrieval augmented generation": ("Retrieval Augmented Generation", "concept"),
    "rag": ("Retrieval Augmented Generation", "concept"),
    "vector database": ("Vector Database", "concept"),
    "vector store": ("Vector Store", "concept"),
    "computer science": ("Computer Science", "subject"),
    "data structures": ("Data Structures", "subject"),
    "algorithms": ("Algorithms", "subject"),
    "mathematics": ("Mathematics", "subject"),
    "physics": ("Physics", "subject"),
    "software engineering": ("Software Engineering", "subject"),
}

# Known variants that are too short or ambiguous to match case-insensitively.
_AMBIGUOUS: set[str] = set()

_STOPWORDS = {
    "using", "with", "in", "for", "to", "and", "that", "which", "as", "because",
    "so", "from", "on", "at", "by", "is", "are", "was", "were", "it", "its",
    "my", "our", "the", "a", "an", "this", "these", "those", "but", "or",
}

_FEATURE_WORDS = {
    "the", "a", "an", "my", "our", "their", "his", "her", "this", "that",
    "it", "and", "or", "for", "to", "of", "in", "on",
}

_ENTITY_TYPE_LABELS = {
    "person": "person",
    "organization": "organization",
    "project": "project",
    "technology": "technology",
    "programming_language": "programming language",
    "skill": "skill",
    "educational_institution": "educational institution",
    "subject": "subject",
    "goal": "goal",
    "preference": "preference",
    "interest": "interest",
    "location": "location",
    "event": "event",
    "concept": "concept",
    "tool": "tool",
    "product": "product",
}


@dataclass(frozen=True)
class _Match:
    start: int
    end: int
    mention: EntityMention


def _clean_name(value: str) -> str:
    text = " ".join(value.split()).strip(" \t\n.,;:!?\"'“”‘’()[]{}")
    for word in ("my", "our", "the", "a", "an"):
        if text.casefold().startswith(word + " "):
            text = text[len(word) + 1 :]
    return text.strip()


def _trim_phrase(value: str, *, max_words: int = 6) -> str:
    words: list[str] = []
    for raw in value.strip().split():
        word = raw.strip(".,;:!?\"'“”‘’()[]{}")
        if not word or word.casefold() in _STOPWORDS:
            break
        words.append(word)
        if len(words) >= max_words:
            break
    return " ".join(words)


def _variant_pattern(variant: str) -> re.Pattern[str]:
    escaped = re.escape(variant)
    # Allow "Next JS" and "Next.js" to match each other's spelling.
    escaped = escaped.replace(r"\ ", r"\s*")
    escaped = escaped.replace(r"\.", r"\.?\s*")
    flags = 0 if variant in _AMBIGUOUS else re.IGNORECASE
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", flags)


_KNOWN_PATTERNS = sorted(
    ((variant, data, _variant_pattern(variant)) for variant, data in _KNOWN.items()),
    key=lambda item: len(item[0]),
    reverse=True,
)

_PROJECT_CUE = re.compile(
    r"\b(?:developing|building|creating|working\s+on|launching)\s+"
    r"(?:an?\s+|the\s+|my\s+|our\s+)?"
    r"([A-Z][A-Za-z0-9.+#_-]*(?:\s+[A-Z][A-Za-z0-9.+#_-]*){0,2})"
)
_PROJECT_NAMED = re.compile(
    r"\b(?:my|our)\s+project\s+(?:called|named)\s+([A-Z][A-Za-z0-9.+#_-]*(?:\s+[A-Z][A-Za-z0-9.+#_-]*){0,2})"
)
_PROJECT_CALLED = re.compile(
    r"\bproject\s+(?:called|named)\s+([A-Z][A-Za-z0-9.+#_-]*(?:\s+[A-Z][A-Za-z0-9.+#_-]*){0,2})"
)
_GOAL_CUE = re.compile(
    r"\b(?:my\s+goal\s+is\s+to|i\s+want\s+to|i\s+aim\s+to|i\s+plan\s+to|i\s+hope\s+to)\s+([^.!?;\n]{3,120})",
    re.IGNORECASE,
)
_INTEREST_CUE = re.compile(
    r"\b(?:interested\s+in|passionate\s+about|fascinated\s+by|curious\s+about)\s+([^.!?;,\n]{2,80})",
    re.IGNORECASE,
)
_LIKE_CUE = re.compile(
    r"\b(?:i\s+like|i\s+love|i\s+enjoy)\s+([^.!?;,\n]{2,80})", re.IGNORECASE
)
_INSTITUTION_CUE = re.compile(
    r"\b(?:study|studying|studied|studies)\s+at\s+([A-Z][A-Za-z0-9.&'’-]*(?:\s+[A-Z][A-Za-z0-9.&'’-]*){0,3})"
)
_ORGANIZATION_CUE = re.compile(
    r"\b(?:work|working|worked|works)\s+(?:at|for)\s+([A-Z][A-Za-z0-9.&'’-]*(?:\s+[A-Z][A-Za-z0-9.&'’-]*){0,3})"
)
_LOCATION_CUE = re.compile(
    r"\b(?:live|living|lived|based|located)\s+in\s+([A-Z][A-Za-z0-9.’'-]*(?:\s+[A-Z][A-Za-z0-9.’'-]*){0,2})"
)
_PERSON_CUE = re.compile(
    r"\bmy\s+(?:friend|colleague|manager|professor|teacher|mentor|brother|sister|partner|teammate)\s+([A-Z][A-Za-z'’-]+)"
)
_EVENT_CUE = re.compile(
    r"\b(?:attending|attended|going\s+to|presenting\s+at)\s+([A-Z][A-Za-z0-9.'’-]*(?:\s+[A-Z][A-Za-z0-9.'’-]*){0,2})"
)
_LEARNING_CUE = re.compile(
    r"\b(?:learning|learn|studying|study|learning\s+about|reading\s+about)\s+([A-Za-z][A-Za-z0-9.+#_-]*(?:\s+[A-Za-z][A-Za-z0-9.+#_-]*){0,2})",
    re.IGNORECASE,
)


def _overlaps(match: _Match, taken: list[tuple[int, int]]) -> bool:
    return any(match.start < end and match.end > start for start, end in taken)


def _add(
    found: list[_Match],
    taken: list[tuple[int, int]],
    *,
    name: str,
    entity_type: str,
    start: int,
    end: int,
    confidence: float,
    aliases: tuple[str, ...] = (),
) -> None:
    cleaned = _clean_name(name)
    if len(cleaned) < 1:
        return
    candidate = _Match(
        start=start,
        end=end,
        mention=EntityMention(
            name=cleaned,
            entity_type=entity_type,
            confidence=confidence,
            description=f"{cleaned} is a {_ENTITY_TYPE_LABELS.get(entity_type, entity_type)} "
            f"mentioned in the user's conversations.",
            start=start,
            aliases=aliases,
        ),
    )
    if _overlaps(candidate, taken):
        return
    found.append(candidate)
    taken.append((start, end))


def extract_entities(text: str) -> list[EntityMention]:
    """Return explicit entity mentions ordered by their position in the text."""
    if not text or not text.strip():
        return []
    found: list[_Match] = []
    taken: list[tuple[int, int]] = []

    for variant, (canonical, entity_type) in sorted(
        _KNOWN.items(), key=lambda item: len(item[0]), reverse=True
    ):
        pattern = _variant_pattern(variant)
        for match in pattern.finditer(text):
            _add(
                found,
                taken,
                name=canonical,
                entity_type=entity_type,
                start=match.start(),
                end=match.end(),
                confidence=0.8,
                aliases=(variant,) if variant.casefold() != canonical.casefold() else (),
            )

    for pattern in (_PROJECT_NAMED, _PROJECT_CALLED, _PROJECT_CUE):
        for match in pattern.finditer(text):
            name = _trim_phrase(match.group(1))
            if not name or name.casefold() in _STOPWORDS:
                continue
            # A bare generic noun is not a project name.
            if name.casefold() in {"assistant", "app", "application", "project", "memory"}:
                continue
            _add(
                found,
                taken,
                name=name,
                entity_type="project",
                start=match.start(1),
                end=match.start(1) + len(match.group(1)),
                confidence=0.78,
            )

    for match in _GOAL_CUE.finditer(text):
        phrase = _trim_phrase(match.group(1), max_words=14)
        if len(phrase) >= 3:
            _add(
                found,
                taken,
                name=phrase,
                entity_type="goal",
                start=match.start(1),
                end=match.start(1) + len(match.group(1)),
                confidence=0.7,
            )

    for pattern in (_INTEREST_CUE, _LIKE_CUE):
        for match in pattern.finditer(text):
            phrase = _trim_phrase(match.group(1), max_words=8)
            if len(phrase) < 2:
                continue
            # Known concepts keep their richer category; the relationship still
            # records that the user is interested in them.
            known = _known_for(phrase)
            _add(
                found,
                taken,
                name=known[0] if known else phrase,
                entity_type=known[1] if known else "interest",
                start=match.start(1),
                end=match.start(1) + len(match.group(1)),
                confidence=0.68,
            )

    for match in _INSTITUTION_CUE.finditer(text):
        _add(
            found,
            taken,
            name=match.group(1),
            entity_type="educational_institution",
            start=match.start(1),
            end=match.end(1),
            confidence=0.7,
        )

    for match in _ORGANIZATION_CUE.finditer(text):
        _add(
            found,
            taken,
            name=match.group(1),
            entity_type="organization",
            start=match.start(1),
            end=match.end(1),
            confidence=0.7,
        )

    for match in _LOCATION_CUE.finditer(text):
        _add(
            found,
            taken,
            name=match.group(1),
            entity_type="location",
            start=match.start(1),
            end=match.end(1),
            confidence=0.65,
        )

    for match in _PERSON_CUE.finditer(text):
        _add(
            found,
            taken,
            name=match.group(1),
            entity_type="person",
            start=match.start(1),
            end=match.end(1),
            confidence=0.6,
        )

    for match in _EVENT_CUE.finditer(text):
        name = _trim_phrase(match.group(1))
        if name:
            _add(
                found,
                taken,
                name=name,
                entity_type="event",
                start=match.start(1),
                end=match.end(1),
                confidence=0.6,
            )

    for match in _LEARNING_CUE.finditer(text):
        phrase = _trim_phrase(match.group(1), max_words=4)
        if not phrase or phrase.casefold() in _FEATURE_WORDS:
            continue
        known = _known_for(phrase)
        if known is not None:
            continue  # already captured by the curated lexicon
        entity_type = "skill" if len(phrase.split()) == 1 else "subject"
        _add(
            found,
            taken,
            name=phrase,
            entity_type=entity_type,
            start=match.start(1),
            end=match.start(1) + len(match.group(1)),
            confidence=0.6,
        )

    found.sort(key=lambda item: item.start)
    return [item.mention for item in found]


def _known_for(name: str) -> tuple[str, str] | None:
    key = " ".join(name.casefold().split())
    if key in _KNOWN:
        return _KNOWN[key]
    # Prefer the longest known phrase that occurs inside the name.
    for variant, data in sorted(_KNOWN.items(), key=lambda item: len(item[0]), reverse=True):
        if len(variant) >= 3 and re.search(rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])", key):
            return data
    return None
