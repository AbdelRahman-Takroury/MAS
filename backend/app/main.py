"""FastAPI application compatible with the existing SFA_API frontend routes."""
from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import json
import os
import html
import uuid
from urllib.request import Request, urlopen
from decimal import Decimal

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .database import Base, add_weather_coordinates, get_session, make_engine, make_session_factory
from .models import Expense, Farm, GrowingSeason, Harvest, IrrigationRecord, Sale
from .schemas import (
    ExpenseCreate, ExpensePatch, ExpenseRead, FarmCreate, FarmPatch, FarmRead,
    FinancialsRead, HarvestCreate, HarvestPatch, HarvestRead,
    AssistantChat, IrrigationCreate, IrrigationPatch, IrrigationRead, SaleCreate, SalePatch,
    SaleRead, SeasonCreate, SeasonPatch, SeasonRead,
    VoiceRequest,
)
from . import team_engines
from .fertilizers import catalog_response

_CROP_STAGE_MAP = {"initial": "initial", "seedling": "initial", "development": "development",
                   "vegetative": "development", "mid_season": "mid_season", "flowering": "mid_season",
                   "fruiting": "mid_season", "late_season": "late_season", "harvest": "late_season"}


def create_app(database_url: str | None = None, initialize_db: bool = True) -> FastAPI:
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    if initialize_db:
        Base.metadata.create_all(engine)
        add_weather_coordinates(engine)

    @asynccontextmanager
    async def lifespan(_app):
        if not initialize_db:
            Base.metadata.create_all(engine)
            add_weather_coordinates(engine)
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="Smart Farm AI API", version="1.0.0", lifespan=lifespan)
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.voice_audio = {}
    origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500").split(",") if x.strip()]
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

    def db_dep():
        yield from get_session(factory)

    DB = Depends(db_dep)

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(_request, exc):
        return Response(content='{"detail":"Database operation failed"}', status_code=503, media_type="application/json")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "database": "connected"}

    def farm_or_404(db: Session, farm_id: str) -> Farm:
        farm = db.get(Farm, farm_id)
        if farm is None:
            raise HTTPException(404, "Farm not found")
        return farm

    def load_weather(farm: Farm):
        if farm.latitude is None or farm.longitude is None:
            return None
        snapshot = os.getenv("WEATHER_SNAPSHOT_PATH")
        if snapshot is None:
            snapshot = str(team_engines.weather.DEFAULT_SNAPSHOT)
        return team_engines.weather.get_weather(
            float(farm.latitude), float(farm.longitude), snapshot_path=snapshot,
        )

    def weather_for_dashboard(farm: Farm):
        result = load_weather(farm)
        if result is None:
            return {"origin": "sample" if farm.data_origin == "sample" else "api", "date": None, "source": None,
                    "fetched_at": None, "status": "unavailable", "missing_inputs": ["latitude", "longitude"],
                    "warnings": ["Farm coordinates are required to request weather."], "errors": [], "days": []}
        days = []
        for day in result["daily"]:
            code = day.get("weather_code")
            condition = ({0: "sunny", 1: "partly", 2: "partly", 3: "cloudy", 45: "cloudy", 48: "cloudy",
                          51: "rain", 53: "rain", 55: "rain", 56: "rain", 57: "rain", 61: "rain", 63: "rain",
                          65: "rain", 66: "rain", 67: "rain", 80: "rain", 81: "rain", 82: "rain",
                          95: "rain", 96: "rain", 99: "rain"}).get(code)
            days.append({"date": day["date"], "condition": condition or "unknown",
                         "high": day.get("temperature_max_c"), "low": day.get("temperature_min_c"),
                         "rain_mm": day.get("precipitation_mm")})
        return {"origin": "sample" if farm.data_origin == "sample" else "api",
                "date": result.get("forecast_start_date"), "source": result.get("source"),
                "fetched_at": result.get("retrieved_at"), "status": result["status"],
                "summary": result.get("summary"), "warnings": result.get("warnings", []),
                "errors": result.get("errors", []), "missing_inputs": [], "days": days}

    def season_or_404(db: Session, farm_id: str, season_id: str | None) -> None:
        if season_id is None:
            return
        season = db.get(GrowingSeason, season_id)
        if season is None or season.farm_id != farm_id:
            raise HTTPException(422, "season_id must belong to this farm")

    def harvest_or_422(db: Session, farm_id: str, harvest_id: str | None) -> None:
        if harvest_id is None:
            return
        harvest = db.get(Harvest, harvest_id)
        if harvest is None or harvest.farm_id != farm_id:
            raise HTTPException(422, "harvest_id must belong to this farm")

    def request_hash(payload: BaseModel) -> str:
        value = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def idempotent_existing(db: Session, model, farm_id: str, key: str | None, digest: str):
        if not key:
            return None
        old = db.scalar(select(model).where(model.farm_id == farm_id, model.idempotency_key == key))
        if old is not None:
            if old.request_hash != digest:
                raise HTTPException(409, "Idempotency-Key was already used with a different request")
            return old
        return None

    def commit_or_conflict(db: Session):
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "Record conflicts with existing data") from exc

    @app.get("/api/farms")
    def list_farms(db: Session = DB):
        items = db.scalars(select(Farm).order_by(Farm.name, Farm.id)).all()
        origin = "sample" if items and all(x.data_origin == "sample" for x in items) else "api"
        return {"origin": origin, "farms": [FarmRead.model_validate(x).model_dump(mode="json") for x in items]}

    @app.post("/api/farms", response_model=FarmRead, status_code=201)
    def create_farm(payload: FarmCreate, db: Session = DB, idem_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=128)):
        digest = request_hash(payload)
        if idem_key:
            previous = db.scalar(select(Farm).where(Farm.idempotency_key == idem_key))
            if previous is not None:
                if previous.request_hash != digest: raise HTTPException(409, "Idempotency-Key was already used with a different request")
                return previous
        farm = Farm(**payload.model_dump(), data_origin="api", idempotency_key=idem_key, request_hash=digest)
        db.add(farm)
        commit_or_conflict(db)
        db.refresh(farm)
        return farm

    @app.get("/api/farms/{farm_id}", response_model=FarmRead)
    def get_farm(farm_id: str, db: Session = DB):
        return farm_or_404(db, farm_id)

    @app.patch("/api/farms/{farm_id}", response_model=FarmRead)
    def patch_farm(farm_id: str, payload: FarmPatch, db: Session = DB):
        farm = farm_or_404(db, farm_id)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(farm, key, value)
        farm.data_origin = "api"
        commit_or_conflict(db)
        db.refresh(farm)
        return farm

    @app.put("/api/farms/{farm_id}", response_model=FarmRead)
    def put_farm(farm_id: str, payload: FarmCreate, db: Session = DB):
        return patch_farm(farm_id, FarmPatch(**payload.model_dump()), db)

    @app.delete("/api/farms/{farm_id}", status_code=204)
    def delete_farm(farm_id: str, db: Session = DB):
        farm = farm_or_404(db, farm_id)
        db.delete(farm)
        commit_or_conflict(db)
        return Response(status_code=204)

    @app.get("/api/farms/{farm_id}/seasons", response_model=list[SeasonRead])
    def list_seasons(farm_id: str, db: Session = DB):
        farm_or_404(db, farm_id)
        return db.scalars(select(GrowingSeason).where(GrowingSeason.farm_id == farm_id).order_by(GrowingSeason.start_date.desc())).all()

    @app.post("/api/farms/{farm_id}/seasons", response_model=SeasonRead, status_code=201)
    def create_season(farm_id: str, payload: SeasonCreate, db: Session = DB, idem_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=128)):
        farm_or_404(db, farm_id)
        digest = request_hash(payload)
        previous = idempotent_existing(db, GrowingSeason, farm_id, idem_key, digest)
        if previous is not None: return previous
        data = payload.model_dump()
        if data["is_active"]:
            db.query(GrowingSeason).filter_by(farm_id=farm_id, is_active=True).update({"is_active": False})
        season = GrowingSeason(farm_id=farm_id, **data, idempotency_key=idem_key, request_hash=digest)
        db.add(season); commit_or_conflict(db); db.refresh(season)
        return season

    @app.get("/api/farms/{farm_id}/seasons/{season_id}", response_model=SeasonRead)
    def get_season(farm_id: str, season_id: str, db: Session = DB):
        item = db.get(GrowingSeason, season_id)
        if item is None or item.farm_id != farm_id: raise HTTPException(404, "Growing season not found")
        return item

    @app.patch("/api/farms/{farm_id}/seasons/{season_id}", response_model=SeasonRead)
    def patch_season(farm_id: str, season_id: str, payload: SeasonPatch, db: Session = DB):
        item = db.get(GrowingSeason, season_id)
        if item is None or item.farm_id != farm_id: raise HTTPException(404, "Growing season not found")
        data = payload.model_dump(exclude_unset=True)
        start_date = data.get("start_date", item.start_date)
        end_date = data.get("end_date", item.end_date)
        if start_date and end_date and end_date < start_date:
            raise HTTPException(422, "end_date must be on or after start_date")
        if data.get("is_active"):
            db.query(GrowingSeason).filter(GrowingSeason.farm_id == farm_id, GrowingSeason.id != season_id).update({"is_active": False})
        for key, value in data.items(): setattr(item, key, value)
        commit_or_conflict(db); db.refresh(item)
        return item

    @app.delete("/api/farms/{farm_id}/seasons/{season_id}", status_code=204)
    def delete_season(farm_id: str, season_id: str, db: Session = DB):
        item = db.get(GrowingSeason, season_id)
        if item is None or item.farm_id != farm_id: raise HTTPException(404, "Growing season not found")
        db.delete(item); commit_or_conflict(db)
        return Response(status_code=204)

    def register_resource_routes(path: str, model, create_schema, patch_schema, read_schema, collection_key: str, section: str):
        base = f"/api/farms/{{farm_id}}/{path}"

        def list_items(farm_id: str, db: Session = DB):
            farm_or_404(db, farm_id)
            items = db.scalars(select(model).where(model.farm_id == farm_id).order_by(model.date.desc(), model.id)).all()
            result = {"origin": "sample" if db.get(Farm, farm_id).data_origin == "sample" else "api", collection_key: [read_schema.model_validate(x).model_dump(mode="json") for x in items]}
            if path == "irrigation":
                farm = db.get(Farm, farm_id)
                weather_result = load_weather(farm)
                stage = _CROP_STAGE_MAP.get(farm.crop_stage)
                missing = []
                if farm.irrigation_method != "drip": missing.append("supported_drip_method")
                if farm.area_dunum is None or farm.area_dunum <= 0: missing.append("positive_farm_area")
                if stage is None: missing.append("supported_tomato_crop_stage")
                if weather_result is None: missing.extend(["latitude", "longitude"])
                elif weather_result.get("status") not in ("live", "cached"): missing.append("usable_weather_forecast")
                estimate = {"status": "unavailable", "value": None, "unit": "L", "period_days": None,
                            "basis": "FAO-56 ET0-based gross irrigation estimate.",
                            "basis_ar": "تقدير إجمالي للري قائم على ET0 وفق FAO-56.",
                            "missing_inputs": missing, "warnings": [], "warnings_ar": [], "assumptions": []}
                result["estimate"] = estimate
                if not missing:
                    engine_farm = {"crop": "tomato", "area_m2": float(farm.area_dunum) * 1000,
                                   "irrigation_method": farm.irrigation_method, "crop_stage": stage,
                                   "irrigation_efficiency": float(farm.irrigation_efficiency) if farm.irrigation_efficiency is not None else None,
                                   "effective_rain_fraction": float(farm.effective_rain_fraction) if farm.effective_rain_fraction is not None else None,
                                   "system_flow_liters_per_hour": None}
                    irrigation_result = team_engines.irrigation.calculate_irrigation(
                        engine_farm, weather_result,
                    )
                    liters = irrigation_result["summary"].get("total_gross_irrigation_liters")
                    if liters is not None:
                        stage_labels = {"seedling": ("seedling", "شتلة"), "vegetative": ("vegetative growth", "نمو خضري"),
                                        "flowering": ("flowering", "إزهار"), "fruiting": ("fruiting", "إثمار"), "harvest": ("harvest", "حصاد")}
                        mapping_note = ([f"Dashboard crop stage '{stage_labels[farm.crop_stage][0]}' was mapped to engine stage '{stage}'."]
                                        if farm.crop_stage in stage_labels else [])
                        mapping_note_ar = ([f"تمت مواءمة مرحلة المحصول ({stage_labels[farm.crop_stage][1]}) مع مرحلة الحساب ({stage})."]
                                           if farm.crop_stage in stage_labels else [])
                        result["estimate"] = {"value": liters, "unit": "L", "basis": "FAO-56 ET0-based gross irrigation estimate.",
                                               "basis_ar": "تقدير إجمالي احتياج الري اعتماداً على ET0 وفق FAO-56.",
                                               "warnings": mapping_note + irrigation_result["warnings"],
                                               "warnings_ar": mapping_note_ar,
                                               "assumptions": irrigation_result["assumptions"]}
                    result["estimate"].update(status=irrigation_result.get("summary", {}).get("status", "calculated"),
                                              period_days=irrigation_result.get("summary", {}).get("period_days"),
                                              date_range={"start": irrigation_result.get("period_start_date"),
                                                          "end": irrigation_result.get("period_end_date")},
                                              partial_total=(irrigation_result.get("summary", {}).get("partial_totals", {})
                                                             .get("total_gross_irrigation_liters", {}).get("value")),
                                              partial_coverage=(irrigation_result.get("summary", {}).get("partial_totals", {})
                                                                .get("total_gross_irrigation_liters")),
                                              missing_inputs=([] if liters is not None else
                                                  (["irrigation_efficiency"] if farm.irrigation_efficiency is None else []) +
                                                  (["effective_rain_fraction"] if farm.effective_rain_fraction is None and any(
                                                      isinstance(day.get("precipitation_mm"), (int, float)) and day["precipitation_mm"] > 0
                                                      for day in weather_result.get("daily", [])) else []) +
                                                  ["complete_weather_period_or_valid_measurements"]),
                                              weather_status=weather_result.get("status"), weather_source=weather_result.get("source"),
                                              weather_fetched_at=weather_result.get("retrieved_at"),
                                              warnings=result["estimate"].get("warnings", []) + irrigation_result.get("warnings", []),
                                              assumptions=irrigation_result.get("assumptions", []))
                if weather_result is not None:
                    result["estimate"].setdefault("weather_status", weather_result.get("status"))
                    result["estimate"].setdefault("weather_source", weather_result.get("source"))
                    result["estimate"].setdefault("weather_fetched_at", weather_result.get("retrieved_at"))
            return result

        def create_item(farm_id: str, payload, db: Session, idem_key: str | None):
            farm_or_404(db, farm_id)
            data = payload.model_dump()
            season_or_404(db, farm_id, data.get("season_id"))
            if path == "sales": harvest_or_422(db, farm_id, data.get("harvest_id"))
            digest = request_hash(payload)
            old = idempotent_existing(db, model, farm_id, idem_key, digest)
            if old is not None: return old
            values = {k: v for k, v in data.items() if k in model.__table__.columns}
            values.update(farm_id=farm_id, idempotency_key=idem_key, request_hash=digest)
            if path == "sales": values["total_jod"] = Decimal(str(data["quantity_kg"])) * Decimal(str(data["unit_price_jod"]))
            obj = model(**values)
            db.add(obj); commit_or_conflict(db); db.refresh(obj)
            return obj

        def get_item(farm_id: str, item_id: str, db: Session = DB):
            farm_or_404(db, farm_id)
            obj = db.get(model, item_id)
            if obj is None or obj.farm_id != farm_id: raise HTTPException(404, "Record not found")
            return obj

        def patch_item(farm_id: str, item_id: str, payload, db: Session = DB):
            obj = get_item(farm_id, item_id, db)
            data = payload.model_dump(exclude_unset=True)
            if "season_id" in data: season_or_404(db, farm_id, data["season_id"])
            if path == "sales" and "harvest_id" in data: harvest_or_422(db, farm_id, data["harvest_id"])
            for key, value in data.items():
                if key in model.__table__.columns: setattr(obj, key, value)
            if path == "sales": obj.total_jod = Decimal(str(obj.quantity_kg)) * Decimal(str(obj.unit_price_jod))
            commit_or_conflict(db); db.refresh(obj)
            return obj

        def delete_item(farm_id: str, item_id: str, db: Session = DB):
            obj = get_item(farm_id, item_id, db)
            db.delete(obj); commit_or_conflict(db)
            return Response(status_code=204)

        async def create_endpoint(farm_id: str, payload: create_schema, db: Session = DB, idem_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=128)):
            return create_item(farm_id, payload, db, idem_key)
        create_endpoint.__annotations__["payload"] = create_schema

        app.add_api_route(base, list_items, methods=["GET"], response_model=dict, name=f"list_{path}")
        app.add_api_route(base, create_endpoint, methods=["POST"], response_model=read_schema, status_code=201, name=f"create_{path}")
        app.add_api_route(base + "/{item_id}", get_item, methods=["GET"], response_model=read_schema, name=f"get_{path}")

        async def patch_endpoint(farm_id: str, item_id: str, payload: patch_schema, db: Session = DB):
            return patch_item(farm_id, item_id, payload, db)
        patch_endpoint.__annotations__["payload"] = patch_schema
        app.add_api_route(base + "/{item_id}", patch_endpoint, methods=["PATCH"], response_model=read_schema, name=f"patch_{path}")

        async def put_endpoint(farm_id: str, item_id: str, payload: create_schema, db: Session = DB):
            return patch_item(farm_id, item_id, patch_schema(**payload.model_dump()), db)
        put_endpoint.__annotations__["payload"] = create_schema
        app.add_api_route(base + "/{item_id}", put_endpoint, methods=["PUT"], response_model=read_schema, name=f"put_{path}")
        app.add_api_route(base + "/{item_id}", delete_item, methods=["DELETE"], status_code=204, name=f"delete_{path}")
        return create_endpoint, list_items

    register_resource_routes("irrigation", IrrigationRecord, IrrigationCreate, IrrigationPatch, IrrigationRead, "records", "irrigation")
    expense_create, expense_list = register_resource_routes("expenses", Expense, ExpenseCreate, ExpensePatch, ExpenseRead, "expenses", "financials")
    harvest_create, harvest_list = register_resource_routes("harvests", Harvest, HarvestCreate, HarvestPatch, HarvestRead, "harvests", "harvests")
    sale_create, sale_list = register_resource_routes("sales", Sale, SaleCreate, SalePatch, SaleRead, "sales", "sales")

    @app.post("/api/farms/{farm_id}/costs", response_model=ExpenseRead, status_code=201)
    async def create_cost(farm_id: str, payload: ExpenseCreate, db: Session = DB, idem_key: str | None = Header(default=None, alias="Idempotency-Key")):
        return await expense_create(farm_id, payload, db, idem_key)

    @app.get("/api/farms/{farm_id}/financials", response_model=FinancialsRead)
    def financials(farm_id: str, db: Session = DB):
        farm = farm_or_404(db, farm_id)
        season = db.scalar(select(GrowingSeason).where(GrowingSeason.farm_id == farm_id, GrowingSeason.is_active.is_(True)).order_by(GrowingSeason.start_date.desc()))
        recorded = db.scalar(select(func.sum(Expense.amount_jod)).where(Expense.farm_id == farm_id))
        actual_revenue = db.scalar(select(func.sum(Sale.total_jod)).where(Sale.farm_id == farm_id))
        actual_harvest = db.scalar(select(func.sum(Harvest.quantity_kg)).where(Harvest.farm_id == farm_id))
        active_season_harvest = (db.scalar(select(func.sum(Harvest.quantity_kg)).where(
            Harvest.farm_id == farm_id, Harvest.season_id == season.id)) if season else None)
        expense_rows = db.scalars(select(Expense).where(Expense.farm_id == farm_id).order_by(Expense.id)).all()
        sale_rows = db.scalars(select(Sale).where(Sale.farm_id == farm_id).order_by(Sale.id)).all()
        calculated = team_engines.finance.calculate_financials({
            "recorded_costs": [{"id": row.id, "amount_jod": str(row.amount_jod), "description": row.category} for row in expense_rows],
            "projected_costs": [],
            "actual_sales": [{"id": row.id, "quantity_kg": str(row.quantity_kg), "revenue_jod": str(row.total_jod)} for row in sale_rows],
            "future_sales": [],
        })
        return FinancialsRead(
            origin="sample" if farm.data_origin == "sample" else "api",
            recorded_costs_jod=float(recorded) if recorded is not None else None,
            projected_costs_jod=season.projected_costs_jod if season else None,
            actual_revenue_jod=float(actual_revenue) if actual_revenue is not None else None,
            projected_revenue_jod=season.projected_revenue_jod if season else None,
            fertilizer_budget_jod=season.fertilizer_budget_jod if season else None,
            expected_harvest_kg=season.expected_harvest_kg if season else None,
            expected_harvest_source="farmer_entered" if season and season.expected_harvest_kg is not None else None,
            expected_harvest_scope="active_season" if season and season.expected_harvest_kg is not None else None,
            actual_harvest_kg=float(actual_harvest) if actual_harvest is not None else None,
            actual_harvest_source="harvest_records" if actual_harvest is not None else None,
            actual_harvest_scope="all_seasons" if actual_harvest is not None else None,
            actual_harvest_active_season_kg=float(active_season_harvest) if active_season_harvest is not None else None,
            fertilizer_options=[],
            actual_sold_kg=float(calculated["actual_sold_kg"]) if calculated["actual_sold_kg"] is not None else None,
            actual_cost_per_sold_kg_jod=float(calculated["projected_cost_per_kg_jod"]) if calculated["projected_cost_per_kg_jod"] is not None else None,
            actual_break_even_jod_per_kg=float(calculated["break_even_price_jod_per_kg"]) if calculated["break_even_price_jod_per_kg"] is not None else None,
            calculation_warnings=calculated["warnings"],
        )

    @app.get("/api/farms/{farm_id}/fertilizers")
    def fertilizers(farm_id: str, db: Session = DB):
        farm = farm_or_404(db, farm_id)
        result = catalog_response()
        season = db.scalar(select(GrowingSeason).where(
            GrowingSeason.farm_id == farm_id, GrowingSeason.is_active.is_(True)
        ).order_by(GrowingSeason.start_date.desc()))
        budget = float(season.fertilizer_budget_jod) if season and season.fertilizer_budget_jod is not None else None
        for product in result["products"]:
            price = product.get("price_jod")
            product["budget_jod"] = budget
            product["budget_remaining_after_one_pack_jod"] = round(budget - price, 3) if budget is not None and price is not None else None
            product["within_budget_for_one_pack"] = budget >= price if budget is not None and price is not None else None
        result["farm_id"] = farm.id
        result["farm_name"] = farm.name
        result["budget_jod"] = budget
        result["budget_origin"] = "active_season" if budget is not None else None
        return result

    @app.get("/api/farms/{farm_id}/weather")
    def weather(farm_id: str, db: Session = DB):
        farm = farm_or_404(db, farm_id)
        return weather_for_dashboard(farm)

    @app.get("/api/farms/{farm_id}/inspections")
    def inspections(farm_id: str, db: Session = DB):
        farm = farm_or_404(db, farm_id)
        result = load_weather(farm)
        reminders = []
        if result is not None and result["status"] in ("live", "cached"):
            for index, advisory in enumerate(result.get("advisories", [])):
                message = advisory.get("message", "Weather forecast advisory.")
                title = {"rain_irrigation_review": {"en": "Review irrigation after forecast rain", "ar": "راجع الري عند توقع هطول المطر"},
                         "heat_inspection": {"en": "Inspect plants during forecast heat", "ar": "افحص النباتات عند توقع ارتفاع الحرارة"},
                         "wind_inspection": {"en": "Inspect plants during forecast winds", "ar": "افحص النباتات عند توقع الرياح"}}.get(advisory.get("type"), {"en": "Weather-related field check", "ar": "فحص حقلي مرتبط بالطقس"})
                reminders.append({"id": f"weather-{index}", "title": title,
                                  "reason": {"en": message, "ar": "تنبيه مبني على توقعات الطقس؛ تحقّق من ظروف الحقل الفعلية."},
                                  "due_date": advisory.get("date")})
        return {"origin": "sample" if farm.data_origin == "sample" else "api", "reminders": reminders}

    def recommendations_for(farm: Farm):
        missing = []
        for field, label in (("area_dunum", "farm area"), ("crop_stage", "supported crop stage"),
                             ("irrigation_efficiency", "verified irrigation efficiency"),
                             ("effective_rain_fraction", "effective-rain fraction"),
                             ("latitude", "farm coordinates")):
            if getattr(farm, field) is None or (field == "crop_stage" and farm.crop_stage not in _CROP_STAGE_MAP):
                missing.append(label)
        if not missing:
            return []
        return [{
            "id": farm.id + "-complete-profile", "topic": "data",
            "summary": {"en": "Some inputs needed for the supported farm calculations are missing.", "ar": "بعض المدخلات اللازمة للحسابات المتاحة غير مكتملة."},
            "action": {"en": "Review the farm profile and enter verified values for: " + ", ".join(missing) + ".", "ar": "راجع ملف المزرعة وأدخل قيماً موثقة للحقول الناقصة."},
            "why": {"en": "The backend withholds irrigation estimates when required inputs are unknown.", "ar": "يحجب النظام تقدير الري عندما تكون المدخلات المطلوبة غير معروفة."},
            "limitations": [{"en": "This is a data-completeness reminder, not agronomic advice.", "ar": "هذا تذكير باستكمال البيانات وليس توصية زراعية."}],
            "sources": [], "evidence": [{"key": "missing_fields", "unit": "text", "value": {"en": ", ".join(missing), "ar": "مدخلات مطلوبة للحساب"}}],
        }]

    @app.get("/api/farms/{farm_id}/recommendations")
    def recommendations(farm_id: str, db: Session = DB):
        farm = farm_or_404(db, farm_id)
        return {"origin": "sample" if farm.data_origin == "sample" else "api", "recommendations": recommendations_for(farm)}

    @app.post("/api/assistant/chat")
    def assistant_chat(payload: AssistantChat, db: Session = DB):
        farm = farm_or_404(db, payload.farm_id) if payload.farm_id else None
        if farm is None:
            return {"answer": "أرسل رقم المزرعة لأجيب اعتمادًا على بياناتها." if payload.language == "ar" else "Select a farm so I can answer using its current data.", "sources": [], "origin": "fallback"}
        key = os.getenv("GROQ_API_KEY")
        if not key:
            answer = ("لا يوجد مفتاح لمزوّد الذكاء الاصطناعي على الخادم. أستطيع استخدام بيانات المزرعة المسجلة فقط؛ راجع المرشد الزراعي للأسئلة التي تحتاج توصية ميدانية." if payload.language == "ar"
                      else "The server has no configured AI provider. I can only use recorded farm data; ask a local agricultural advisor for field-specific recommendations.")
            return {"answer": answer, "sources": [], "origin": "fallback"}
        farm_data = FarmRead.model_validate(farm).model_dump(mode="json")
        costs = db.scalar(select(func.sum(Expense.amount_jod)).where(Expense.farm_id == farm.id))
        revenue = db.scalar(select(func.sum(Sale.total_jod)).where(Sale.farm_id == farm.id))
        system = ("You are Smart Farm AI, a cautious tomato-farm assistant for Jordan Valley. "
                  "Answer in the requested language. Only use supplied farm facts. Never invent numbers or sources, diagnose disease, "
                  "or recommend pesticide/chemical treatment. State uncertainty and ask for missing inputs. Keep it concise. "
                  "Farm facts (JSON): " + json.dumps({"farm": farm_data, "recorded_costs_jod": float(costs) if costs is not None else None,
                                                       "actual_revenue_jod": float(revenue) if revenue is not None else None,
                                                       "current_recommendations": recommendations_for(farm)}, ensure_ascii=False))
        request_data = json.dumps({"model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), "temperature": 0.1,
                                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": payload.message}],
                                   "max_tokens": 500}, ensure_ascii=False).encode("utf-8")
        try:
            request = Request("https://api.groq.com/openai/v1/chat/completions", data=request_data,
                              headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=12) as response:
                result = json.loads(response.read().decode("utf-8"))
            answer = result["choices"][0]["message"]["content"]
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("Empty assistant response")
            return {"answer": answer.strip(), "sources": [], "origin": "api"}
        except Exception:
            answer = ("تعذر الاتصال بمزوّد الذكاء الاصطناعي. لم تُنشأ توصية؛ تحقّق من إعدادات الخادم وحاول لاحقًا." if payload.language == "ar"
                      else "The AI provider could not be reached. No recommendation was generated; check server configuration and try again.")
            return {"answer": answer, "sources": [], "origin": "fallback"}

    @app.post("/api/assistant/voice")
    def assistant_voice(payload: VoiceRequest, db: Session = DB):
        farm = farm_or_404(db, payload.farm_id) if payload.farm_id else None
        if farm is None:
            raise HTTPException(422, "farm_id is required for farm recommendations")
        match = next((item for item in recommendations_for(farm) if item["id"] == payload.recommendation_id), None)
        if match is None:
            raise HTTPException(404, "Recommendation not found")
        key, region = os.getenv("AZURE_SPEECH_KEY"), os.getenv("AZURE_SPEECH_REGION")
        if not key or not region:
            raise HTTPException(503, "Azure Speech key and region are not configured on the server")
        spoken_text = " ".join(part["ar"] for part in (match["summary"], match["action"], match["why"]) if isinstance(part, dict) and part.get("ar"))
        ssml = ("<speak version='1.0' xml:lang='ar-JO'><voice name='ar-JO-TaimNeural'>" +
                html.escape(spoken_text) + "</voice></speak>").encode("utf-8")
        request = Request(f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1", data=ssml,
                          headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/ssml+xml",
                                   "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3"}, method="POST")
        try:
            with urlopen(request, timeout=20) as response:
                audio_bytes = response.read()
            if not audio_bytes:
                raise ValueError("Azure Speech returned empty audio")
        except Exception as exc:
            raise HTTPException(503, "Azure Speech synthesis failed; verify server credentials and provider availability") from exc
        audio_id = uuid.uuid4().hex
        app.state.voice_audio[audio_id] = audio_bytes
        while len(app.state.voice_audio) > 32:
            app.state.voice_audio.pop(next(iter(app.state.voice_audio)))
        return {"audio_url": f"/api/assistant/voice/audio/{audio_id}", "text": spoken_text,
                "voice_id": "ar-JO-TaimNeural", "demo_mode": False}

    @app.get("/api/assistant/voice/audio/{audio_id}")
    def assistant_voice_audio(audio_id: str):
        audio = app.state.voice_audio.get(audio_id)
        if audio is None:
            raise HTTPException(404, "Audio not found; request synthesis again")
        return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})

    return app


app = create_app(initialize_db=False)
