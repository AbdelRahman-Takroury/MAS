"""Bounded bilingual assistant contracts."""

from typing import Literal

from pydantic import Field

from .common import StrictModel


class AssistantRequest(StrictModel):
    farm_id: str = Field(min_length=1)
    language: Literal["ar", "en"] = "ar"
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=100)


class CalculatorReference(StrictModel):
    calculator: str
    result_id: str | None = None


class DocumentReference(StrictModel):
    document_id: str
    title: str
    section: str | None = None
    source_url: str


class AssistantResponse(StrictModel):
    answer: str
    language: Literal["ar", "en"]
    used_fallback: bool
    calculator_references: list[CalculatorReference] = Field(default_factory=list)
    document_references: list[DocumentReference] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
