"""Combined farm dashboard endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.dashboard import DashboardResponse
from ..services.dashboard import build_dashboard


router = APIRouter(prefix="/api/farms", tags=["dashboard"])


@router.get("/{farm_id}/dashboard", response_model=DashboardResponse)
def get_dashboard(farm_id: str, database: Session = Depends(get_db)) -> DashboardResponse:
    return build_dashboard(database, farm_id)
