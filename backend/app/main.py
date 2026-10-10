from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from pathlib import Path
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import get_db
from .routes.assistant import router as assistant_router
from .routes.dashboard import router as dashboard_router
from .routes.expenses import router as expenses_router
from .routes.farms import router as farms_router
from .routes.irrigations import router as irrigations_router
from .routes.simulations import router as simulations_router
from .routes.ui import router as ui_router
from .routes.voice import router as voice_router


app = FastAPI(
    title="Smart Farm AI – Tomato Farm Assistant",
    version="0.1.0",
    description=(
        "Arabic-first agricultural decision-support demonstration. "
        "Sample outputs are not validated agronomic advice."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(farms_router)
app.include_router(dashboard_router)
app.include_router(expenses_router)
app.include_router(irrigations_router)
app.include_router(simulations_router)
app.include_router(assistant_router)
app.include_router(ui_router)
app.include_router(voice_router)


@app.exception_handler(SQLAlchemyError)
async def database_error(_request, _exc):
    return JSONResponse(status_code=503, content={"detail": "Database operation failed; check server configuration and migrations"})


PUBLIC = Path(__file__).resolve().parents[2] / "public"
# Explicit allowlist: .env, source code, database files and .git are never served.
for directory in ("css", "js", "assets"):
    app.mount("/" + directory, StaticFiles(directory=PUBLIC / directory), name=directory)


@app.get("/", include_in_schema=False)
def landing():
    return FileResponse(PUBLIC / "index.html")


@app.get("/dashboard.html", include_in_schema=False)
def dashboard_page():
    return FileResponse(PUBLIC / "dashboard.html")


@app.get("/health/live", tags=["health"])
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def ready(database: Session = Depends(get_db)) -> dict[str, str]:
    try:
        database.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from exc

    return {
        "status": "ok",
        "database": "available",
    }
