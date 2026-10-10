"""Non-persistent farm simulation endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.simulation import SimulationRequest, SimulationResponse
from ..services.simulation import build_simulation


router = APIRouter(prefix="/api/farms", tags=["simulation"])


@router.post("/{farm_id}/simulate", response_model=SimulationResponse)
def simulate_farm(
    farm_id: str,
    request: SimulationRequest,
    database: Session = Depends(get_db),
) -> SimulationResponse:
    return build_simulation(database, farm_id, request)
