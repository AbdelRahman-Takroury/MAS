"""Strict contracts for reviewed local knowledge and retrieval results."""

from typing import Literal

from pydantic import Field

from .common import StrictModel


class KnowledgePassage(StrictModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    section: str = Field(min_length=1)
    language: Literal["ar", "en"]
    text: str = Field(min_length=1)
    keywords_ar: list[str] = Field(min_length=1)
    keywords_en: list[str] = Field(min_length=1)
    status: Literal["reviewed"]
    limitations: list[str] = Field(default_factory=list)


class RetrievedPassage(StrictModel):
    id: str
    title: str
    source_url: str
    section: str
    language: Literal["ar", "en"]
    text: str
    limitations: list[str] = Field(default_factory=list)
    score: int = Field(ge=0)
