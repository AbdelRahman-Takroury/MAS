"""The committed frontend fixtures must conform to the public API contract."""

from pathlib import Path

import pytest

from backend.app.schemas import (
    AssistantResponse,
    DashboardResponse,
    FarmCreate,
    SimulationRequest,
)


EXAMPLES = Path(__file__).parents[1] / "contracts" / "examples"


@pytest.mark.parametrize(
    ("filename", "model"),
    [
        ("farm-create.json", FarmCreate),
        ("dashboard-complete.json", DashboardResponse),
        ("dashboard-missing-data.json", DashboardResponse),
        ("simulation-request.json", SimulationRequest),
        ("assistant-response.json", AssistantResponse),
    ],
)
def test_contract_example_is_valid(filename, model):
    parsed = model.model_validate_json((EXAMPLES / filename).read_text(encoding="utf-8"))
    assert parsed is not None


def test_simulation_requires_an_override():
    with pytest.raises(ValueError, match="At least one simulation override"):
        SimulationRequest.model_validate({"overrides": {}})


def test_contract_rejects_unknown_fields():
    with pytest.raises(ValueError):
        FarmCreate.model_validate_json(
            (EXAMPLES / "farm-create.json").read_text(encoding="utf-8")[:-2]
            + ', "unexpected": true}'
        )
