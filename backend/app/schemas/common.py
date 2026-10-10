"""Shared public API contract types.

These models describe the stable application contract. Salah's engine responses
remain unchanged and are translated into these types by the dashboard service.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApiStatus(StrEnum):
    OK = "ok"
    ESTIMATED = "estimated"
    MISSING_DATA = "missing_data"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class DataKind(StrEnum):
    LIVE = "live"
    CACHED = "cached"
    SIMULATED = "simulated"
    CALCULATED = "calculated"
    USER_ENTERED = "user_entered"


class SourceMetadata(StrictModel):
    name: str = Field(min_length=1)
    reference: str | None = None
    retrieved_at: datetime | None = None


class ModuleMetadata(StrictModel):
    status: ApiStatus
    data_kind: DataKind
    source: SourceMetadata | None = None
    generated_at: datetime
    missing_inputs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
