"""Deterministic bilingual retrieval over the reviewed tomato knowledge file."""

import json
from pathlib import Path
import re
import unicodedata

from pydantic import ValidationError

from ..schemas.knowledge import KnowledgePassage, RetrievedPassage


DEFAULT_KNOWLEDGE_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "knowledge" / "tomato_guidance.json"
)
_ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u0600-\u06ff]+")
_ARABIC_TRANSLATION = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
        "ة": "ه",
        "ـ": "",
    }
)
_STOPWORDS = {
    "a", "an", "and", "are", "for", "how", "is", "of", "the", "to", "what", "why",
    "او", "الى", "ان", "في", "كيف", "ما", "ماذا", "من", "هل", "هو", "هي", "و", "على",
}


class KnowledgeLoadError(ValueError):
    """The server-owned reviewed knowledge file is invalid or unreadable."""


def normalize_text(value: str) -> str:
    """Normalize Arabic variants, diacritics, case, punctuation, and spacing."""
    value = unicodedata.normalize("NFKC", value).lower().translate(_ARABIC_TRANSLATION)
    value = _ARABIC_DIACRITICS.sub("", value)
    return " ".join(_TOKEN_PATTERN.findall(value))


def _tokens(value: str) -> set[str]:
    return {token for token in normalize_text(value).split() if token not in _STOPWORDS}


def load_knowledge(path: str | Path = DEFAULT_KNOWLEDGE_PATH) -> list[KnowledgePassage]:
    """Load and validate reviewed passages; reject duplicates and draft material."""
    knowledge_path = Path(path)
    try:
        payload = json.loads(knowledge_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KnowledgeLoadError(f"Knowledge file is unavailable or invalid: {knowledge_path}") from exc
    if not isinstance(payload, list) or not payload:
        raise KnowledgeLoadError("Knowledge file must contain a non-empty JSON array")
    try:
        passages = [KnowledgePassage.model_validate(item) for item in payload]
    except ValidationError as exc:
        raise KnowledgeLoadError("Knowledge file contains an invalid passage") from exc
    identifiers = [passage.id for passage in passages]
    if len(identifiers) != len(set(identifiers)):
        raise KnowledgeLoadError("Knowledge passage IDs must be unique")
    return passages


def _score(question: str, question_tokens: set[str], passage: KnowledgePassage) -> int:
    score = 0
    keywords = passage.keywords_ar + passage.keywords_en
    for keyword in keywords:
        normalized_keyword = normalize_text(keyword)
        if not normalized_keyword:
            continue
        keyword_tokens = _tokens(normalized_keyword)
        if normalized_keyword in question:
            score += 8 if len(keyword_tokens) > 1 else 5
        score += 2 * len(question_tokens & keyword_tokens)

    title_section_tokens = _tokens(f"{passage.title} {passage.section}")
    body_tokens = _tokens(passage.text)
    score += 3 * len(question_tokens & title_section_tokens)
    score += len(question_tokens & body_tokens)
    return score


def retrieve_passages(
    question: str,
    language: str,
    limit: int = 3,
    *,
    knowledge_path: str | Path = DEFAULT_KNOWLEDGE_PATH,
) -> list[RetrievedPassage]:
    """Return the best two or three passages without network or model calls."""
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")
    if language not in {"ar", "en"}:
        raise ValueError("language must be 'ar' or 'en'")
    if type(limit) is not int or not 1 <= limit <= 3:
        raise ValueError("limit must be an integer from 1 to 3")

    normalized_question = normalize_text(question)
    question_tokens = _tokens(normalized_question)
    ranked = [
        (_score(normalized_question, question_tokens, passage), passage)
        for passage in load_knowledge(knowledge_path)
    ]
    ranked.sort(
        key=lambda item: (
            -item[0],
            item[1].language != language,
            item[1].id,
        )
    )
    matches = [item for item in ranked if item[0] > 0]
    if not matches:
        # A general reviewed passage is safer than fabricating an answer. The
        # zero score lets the assistant explicitly describe this as fallback context.
        matches = [item for item in ranked if item[1].id == "tomato-inspection-general-ar"]

    return [
        RetrievedPassage(
            id=passage.id,
            title=passage.title,
            source_url=passage.source_url,
            section=passage.section,
            language=passage.language,
            text=passage.text,
            limitations=list(passage.limitations),
            score=score,
        )
        for score, passage in matches[:limit]
    ]
