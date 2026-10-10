"""Load the team's pure calculation/provider modules without copying their code."""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path


def _load_package(name: str, directory: Path) -> None:
    if name in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(
        name, directory / "__init__.py", submodule_search_locations=[str(directory)]
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load internal team package: {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)


_TEAM_ROOT = Path(__file__).resolve().parents[2] / "MAS-Abdel_Rahman" / "backend"
_load_package("sfa_team_engines", _TEAM_ROOT / "engines")
_load_package("sfa_team_services", _TEAM_ROOT / "services")

irrigation = importlib.import_module("sfa_team_engines.irrigation")
water_budget = importlib.import_module("sfa_team_engines.water_budget")
finance = importlib.import_module("sfa_team_engines.finance")
finance_scenarios = importlib.import_module("sfa_team_engines.finance_scenarios")
weather = importlib.import_module("sfa_team_services.weather")
