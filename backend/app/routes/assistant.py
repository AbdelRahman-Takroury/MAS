"""Bilingual source-backed assistant endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.assistant import AssistantRequest, AssistantResponse
from ..services.assistant import answer_question


router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.post("", response_model=AssistantResponse)
def ask_assistant(
    request: AssistantRequest,
    database: Session = Depends(get_db),
) -> AssistantResponse:
    return answer_question(database, request)
