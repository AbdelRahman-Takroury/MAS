"""Deterministic, network-free bilingual knowledge retrieval tests."""

import json

import pytest

from backend.app.services.retrieval import (
    KnowledgeLoadError,
    load_knowledge,
    normalize_text,
    retrieve_passages,
)


def test_arabic_water_shortage_question_retrieves_cited_limitations():
    results = retrieve_passages("لماذا يوجد عجز في المياه المتاحة؟", "ar")
    assert results[0].id == "water-shortage-limitations-ar"
    assert results[0].score > 0
    assert results[0].source_url.startswith("https://www.fao.org/")
    assert any("yield" in limitation.lower() for limitation in results[0].limitations)


def test_arabic_tomato_health_question_retrieves_inspection_guidance_without_groq():
    results = retrieve_passages("كيف أفحص البندورة عند وجود أعراض مرضية؟", "ar", limit=2)
    assert results
    assert results[0].id == "tomato-inspection-general-ar"
    assert all(result.title and result.source_url for result in results)
    assert all(result.score > 0 for result in results)


def test_english_break_even_question_retrieves_financial_passage():
    results = retrieve_passages("How is the break-even price per kilogram calculated?", "en")
    assert results[0].id == "financial-break-even-en"
    assert "projected total cost" in results[0].text.lower()


def test_arabic_normalization_handles_diacritics_and_letter_variants():
    assert normalize_text("إِرْشَاداتُ فَحْصِ البَنْدُورَة") == "ارشادات فحص البندوره"


def test_results_are_deterministic_and_limited():
    first = retrieve_passages("tomato disease leaf spots", "en", limit=2)
    second = retrieve_passages("tomato disease leaf spots", "en", limit=2)
    assert first == second
    assert 1 <= len(first) <= 2
    assert [item.score for item in first] == sorted(
        (item.score for item in first), reverse=True
    )


def test_unmatched_question_returns_reviewed_fallback_with_zero_score():
    results = retrieve_passages("quantum telescope", "en")
    assert [result.id for result in results] == ["tomato-inspection-general-ar"]
    assert results[0].score == 0


@pytest.mark.parametrize(
    "question,language,limit",
    [("", "ar", 3), ("   ", "en", 3), ("tomato", "fr", 3), ("tomato", "en", 0),
     ("tomato", "en", 4), ("tomato", "en", True)],
)
def test_invalid_retrieval_request_is_rejected(question, language, limit):
    with pytest.raises(ValueError):
        retrieve_passages(question, language, limit)


def test_knowledge_file_is_strict_and_reviewed():
    passages = load_knowledge()
    assert len(passages) == 6
    assert len({passage.id for passage in passages}) == len(passages)
    assert all(passage.status == "reviewed" for passage in passages)
    assert all(passage.limitations for passage in passages)


@pytest.mark.parametrize("payload", [None, [], [{"id": "incomplete"}]])
def test_invalid_knowledge_file_fails_clearly(tmp_path, payload):
    path = tmp_path / "knowledge.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(KnowledgeLoadError):
        load_knowledge(path)


def test_duplicate_knowledge_ids_are_rejected(tmp_path):
    passage = load_knowledge()[0].model_dump()
    path = tmp_path / "duplicates.json"
    path.write_text(json.dumps([passage, passage]), encoding="utf-8")
    with pytest.raises(KnowledgeLoadError, match="unique"):
        load_knowledge(path)
