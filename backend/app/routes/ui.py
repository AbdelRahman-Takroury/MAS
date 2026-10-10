"""Mo3taz dashboard adapter over the canonical database and calculator services."""
import hashlib
import json
from datetime import datetime, time, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Response
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.engines.finance import calculate_financials
from ..config import settings
from ..database import get_db
from ..models import CropSeason, Expense, Farm, Harvest, IrrigationEvent, Plot, Sale, User, WriteReceipt
from ..schemas import ui as schema
from ..schemas.assistant import AssistantRequest
from ..schemas.simulation import SimulationRequest
from ..services.simulation import build_simulation
from ..services.assistant import answer_question
from ..services.dashboard import _active_farm, _calculation_context, _finance_module, build_dashboard
from ..services.fertilizers import catalog_response
from .dependencies import owned_farm

router = APIRouter(prefix="/api/ui", tags=["dashboard adapter"])
DB = Depends(get_db)
IDEM = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=150)


@router.post("/farms/{farm_id}/simulate")
def simulate(farm_id: str, payload: SimulationRequest, db: Session = DB):
    return build_simulation(db, farm_id, payload)


def validate(model, value):
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        raise HTTPException(422, jsonable_encoder(exc.errors(include_context=False))) from exc


def replay(db, scope, key, payload):
    digest = hashlib.sha256(json.dumps(jsonable_encoder(payload), sort_keys=True).encode()).hexdigest()
    prior = db.get(WriteReceipt, (scope, key)) if key else None
    if prior and prior.digest != digest:
        raise HTTPException(409, "Idempotency-Key already used with another request")
    return (json.loads(prior.response_json) if prior else None), digest


def commit(db, value, scope=None, key=None, digest=None):
    data = jsonable_encoder(value)
    if key:
        db.add(WriteReceipt(scope=scope, key=key, digest=digest, response_json=json.dumps(data)))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        previous = db.get(WriteReceipt, (scope, key)) if key else None
        if previous and previous.digest == digest:
            return json.loads(previous.response_json)
        raise HTTPException(409, "Record conflicts with existing data") from exc
    return data


def origin(farm):
    return "sample" if farm.is_sample else "api"


def farm_json(farm, plot=None, season=None):
    plot = plot or next(iter(farm.plots), None)
    season = season or (next((s for s in plot.crop_seasons if s.is_active), None) if plot else None)
    return {"id": farm.id, "name": farm.name or farm.location_name, "location": farm.location_name,
            "latitude": float(farm.latitude), "longitude": float(farm.longitude),
            "area_dunum": float(plot.area_m2 / 1000) if plot else None, "origin": origin(farm), "data_origin": origin(farm),
            "planting_date": season.establishment_date if season else None,
            "crop_stage": season.crop_stage if season else None, "irrigation_method": "drip",
            "establishment_method": season.establishment_method if season else "unknown",
            "irrigation_efficiency": float(season.irrigation_efficiency) if season and season.irrigation_efficiency is not None else None,
            "effective_rain_fraction": float(season.effective_rain_fraction) if season and season.effective_rain_fraction is not None else None,
            "system_flow_liters_per_hour": float(season.system_flow_liters_per_hour) if season and season.system_flow_liters_per_hour is not None else None}


@router.get("/farms")
def farms(db: Session = DB):
    items = db.scalars(select(Farm).where(Farm.owner_id == settings.demo_user_id).order_by(Farm.id)).all()
    return {"origin": "sample" if items and all(f.is_sample for f in items) else "api",
            "farms": [farm_json(f) for f in items]}


def set_profile(farm, plot, season, payload):
    farm.name, farm.location_name = payload.name, payload.location
    farm.latitude, farm.longitude = payload.latitude, payload.longitude
    plot.area_m2 = payload.area_dunum * 1000
    season.establishment_date = payload.planting_date
    for name in ("crop_stage", "irrigation_method", "establishment_method", "irrigation_efficiency",
                 "effective_rain_fraction", "system_flow_liters_per_hour"):
        setattr(season, name, getattr(payload, name))


@router.post("/farms", status_code=201)
def create_farm(payload: schema.FarmInput, db: Session = DB, key: str | None = IDEM):
    scope = settings.demo_user_id + "/farms"
    old, digest = replay(db, scope, key, payload)
    if old is not None:
        return old
    owner = db.get(User, settings.demo_user_id)
    if owner is None:
        owner = User(id=settings.demo_user_id, preferred_language="ar")
        db.add(owner)
    farm = Farm(id=str(uuid4()), owner=owner, timezone="Asia/Amman", is_sample=False)
    plot = Plot(id=str(uuid4()), farm=farm, name="Tomato plot")
    season = CropSeason(id=str(uuid4()), plot=plot, crop="tomato", is_active=True)
    set_profile(farm, plot, season, payload)
    db.add(farm)
    return commit(db, farm_json(farm, plot, season), scope, key, digest)


@router.get("/farms/{farm_id}")
def get_farm(farm_id: str, db: Session = DB):
    return farm_json(owned_farm(db, farm_id))


@router.put("/farms/{farm_id}")
@router.patch("/farms/{farm_id}")
def update_farm(farm_id: str, payload: dict = Body(...), db: Session = DB):
    farm, plot, season = _active_farm(db, farm_id)
    existing = {k: v for k, v in farm_json(farm, plot, season).items() if k in schema.FarmInput.model_fields}
    merged = validate(schema.FarmInput, {**existing, **payload})
    set_profile(farm, plot, season, merged)
    return commit(db, farm_json(farm, plot, season))


@router.delete("/farms/{farm_id}", status_code=204)
def delete_farm(farm_id: str, db: Session = DB):
    db.delete(owned_farm(db, farm_id))
    commit(db, None)
    return Response(status_code=204)


def season_for(db, farm_id, season_id=None):
    farm = owned_farm(db, farm_id)
    if not season_id:
        return _active_farm(db, farm_id)[2]
    season = db.get(CropSeason, season_id)
    if season is None or season.plot.farm_id != farm.id:
        raise HTTPException(422, "season_id must belong to this farm")
    return season


def season_json(s):
    return {"id": s.id, "farm_id": s.plot.farm_id, "name": s.name or "Tomato season", "crop": s.crop,
            "start_date": s.establishment_date, "end_date": s.end_date, "is_active": s.is_active,
            "expected_harvest_kg": s.expected_marketable_kg, "projected_costs_jod": s.projected_costs_jod,
            "fertilizer_budget_jod": s.fertilizer_budget_jod,
            "assumed_sale_price_jod_per_kg": s.assumed_sale_price_jod_per_kg}


def set_season(db, farm, season, payload):
    if season.is_active and not payload.is_active:
        raise HTTPException(409, "Activate another season before deactivating the current season")
    if payload.is_active:
        # Serialize active-season changes for this farm on PostgreSQL.
        db.execute(select(Farm).where(Farm.id == farm.id).with_for_update())
        for plot in farm.plots:
            for other in plot.crop_seasons:
                other.is_active = False
    for name, value in payload.model_dump().items():
        setattr(season, {"start_date": "establishment_date", "expected_harvest_kg": "expected_marketable_kg"}.get(name, name), value)


@router.get("/farms/{farm_id}/seasons")
def seasons(farm_id: str, db: Session = DB):
    farm = owned_farm(db, farm_id)
    return {"seasons": [season_json(s) for p in farm.plots for s in p.crop_seasons]}


@router.post("/farms/{farm_id}/seasons", status_code=201)
def create_season(farm_id: str, payload: schema.SeasonInput, db: Session = DB, key: str | None = IDEM):
    farm = owned_farm(db, farm_id)
    scope = farm_id + "/seasons"
    old, digest = replay(db, scope, key, payload)
    if old is not None:
        return old
    plot = farm.plots[0]
    template = next((s for s in plot.crop_seasons if s.is_active), plot.crop_seasons[0])
    season = CropSeason(id=str(uuid4()), plot=plot, crop_stage="initial", irrigation_method="drip",
                        establishment_method="unknown", irrigation_efficiency=template.irrigation_efficiency,
                        effective_rain_fraction=template.effective_rain_fraction,
                        system_flow_liters_per_hour=template.system_flow_liters_per_hour)
    with db.no_autoflush:
        set_season(db, farm, season, payload)
    db.add(season)
    return commit(db, season_json(season), scope, key, digest)


@router.patch("/farms/{farm_id}/seasons/{season_id}")
def patch_season(farm_id: str, season_id: str, payload: dict = Body(...), db: Session = DB):
    s = season_for(db, farm_id, season_id)
    existing = {k: v for k, v in season_json(s).items() if k in schema.SeasonInput.model_fields}
    validated = validate(schema.SeasonInput, {**existing, **payload})
    set_season(db, s.plot.farm, s, validated)
    return commit(db, season_json(s))


@router.delete("/farms/{farm_id}/seasons/{season_id}", status_code=204)
def delete_season(farm_id: str, season_id: str, db: Session = DB):
    s = season_for(db, farm_id, season_id)
    if s.is_active or s.expenses or s.irrigation_events or s.harvests or s.sales:
        raise HTTPException(409, "Only empty inactive seasons can be deleted; historical records are retained")
    db.delete(s)
    commit(db, None)
    return Response(status_code=204)


def record_json(row):
    s = row.crop_season
    common = {"id": row.id, "farm_id": s.plot.farm_id, "season_id": s.id}
    if isinstance(row, Expense):
        return {**common, "date": row.incurred_at.date(), "amount_jod": row.amount_jod,
                "description": row.description, "category": row.category}
    if isinstance(row, IrrigationEvent):
        return {**common, "date": row.occurred_at.date(), "confirmed": True,
                "volume_m3": row.amount_liters / 1000, "amount_mm": row.amount_liters / s.plot.area_m2,
                "notes": row.notes}
    data = {**common, "date": row.date, "quantity_kg": row.quantity_kg, "notes": row.notes}
    if isinstance(row, Harvest):
        return {**data, "grade": row.grade}
    return {**data, "harvest_id": row.harvest_id, "unit_price_jod": row.unit_price_jod,
            "total_jod": row.quantity_kg * row.unit_price_jod, "buyer": row.buyer}


def assign_record(db, farm_id, row, payload):
    s = season_for(db, farm_id, payload.season_id)
    row.crop_season = s
    if isinstance(row, Expense):
        row.incurred_at = datetime.combine(payload.date, time(), timezone.utc)
        row.amount_jod, row.category, row.description = payload.amount_jod, payload.category, payload.description
        row.cost_view = "cash"
    elif isinstance(row, IrrigationEvent):
        liters = payload.volume_m3 * 1000 if payload.volume_m3 is not None else payload.amount_mm * s.plot.area_m2
        if payload.volume_m3 is not None and payload.amount_mm is not None and abs(liters - payload.amount_mm * s.plot.area_m2) > Decimal("0.001"):
            raise HTTPException(422, "volume_m3 and amount_mm disagree for this plot area")
        row.occurred_at = datetime.combine(payload.date, time(), timezone.utc)
        row.amount_liters, row.measurement_basis, row.status, row.notes = liters.quantize(Decimal("0.001")), "estimated", "confirmed", payload.notes
    else:
        for name, value in payload.model_dump(exclude={"season_id"}).items():
            setattr(row, name, value)
        if isinstance(row, Sale) and payload.harvest_id:
            harvest = db.get(Harvest, payload.harvest_id)
            if harvest is None or harvest.crop_season_id != s.id:
                raise HTTPException(422, "harvest_id must belong to the same season")


def register_records(path, model, input_schema):
    def listing(farm_id: str, db: Session = DB):
        farm = owned_farm(db, farm_id)
        rows = db.scalars(select(model).join(CropSeason).join(Plot).where(Plot.farm_id == farm.id).order_by(model.id)).all()
        data = {"origin": origin(farm), path: [record_json(row) for row in rows]}
        if path == "irrigation":
            dashboard = build_dashboard(db, farm_id)
            irr = dashboard.irrigation
            data = {"origin": origin(farm), "records": data[path], "estimate": {
                "value": irr.water_required_liters / 1000 if irr.water_required_liters is not None else None,
                "unit": "m³", "status": {"estimated": "calculated", "missing_data": "partial"}.get(irr.status, irr.status),
                "period_days": irr.period_days, "missing_inputs": irr.missing_inputs,
                "basis": "FAO-56 demonstration baseline; not a validated irrigation schedule.",
                "basis_ar": "تقدير تجريبي وليس جدول ري معتمداً.", "warnings": irr.warnings,
                "assumptions": irr.assumptions, "weather_status": dashboard.weather.data_kind,
                "weather_source": "Open-Meteo", "weather_fetched_at": dashboard.weather.forecast_generated_at}}
        return data

    def create(farm_id: str, payload, db: Session = DB, key: str | None = IDEM):
        owned_farm(db, farm_id)
        scope = farm_id + "/" + path
        old, digest = replay(db, scope, key, payload)
        if old is not None:
            return old
        row = model(id=str(uuid4()))
        if model in (Expense, IrrigationEvent):
            row.idempotency_key = str(uuid4())
        with db.no_autoflush:
            assign_record(db, farm_id, row, payload)
        db.add(row)
        return commit(db, record_json(row), scope, key, digest)

    def owned_record(db, farm_id, record_id):
        owned_farm(db, farm_id)
        row = db.get(model, record_id)
        if row is None or row.crop_season.plot.farm_id != farm_id:
            raise HTTPException(404, "Record not found")
        return row

    def update(farm_id: str, record_id: str, payload: dict = Body(...), db: Session = DB):
        row = owned_record(db, farm_id, record_id)
        existing = {k: v for k, v in record_json(row).items() if k in input_schema.model_fields}
        if model is IrrigationEvent:
            if "volume_m3" in payload:
                existing.pop("amount_mm", None)
            elif "amount_mm" in payload:
                existing.pop("volume_m3", None)
        validated = validate(input_schema, {**existing, **payload})
        if model is Harvest and validated.season_id != row.crop_season_id:
            if db.scalar(select(Sale.id).where(Sale.harvest_id == row.id)):
                raise HTTPException(409, "Cannot move a harvest linked to a sale to another season")
        assign_record(db, farm_id, row, validated)
        return commit(db, record_json(row))

    def delete(farm_id: str, record_id: str, db: Session = DB):
        row = owned_record(db, farm_id, record_id)
        if model is Harvest and db.scalar(select(Sale.id).where(Sale.harvest_id == row.id)):
            raise HTTPException(409, "Remove the sale's harvest reference before deleting this harvest")
        db.delete(row)
        commit(db, None)
        return Response(status_code=204)

    create.__annotations__["payload"] = input_schema
    url = "/farms/{farm_id}/" + path
    router.add_api_route(url, listing, methods=["GET"], name="list_" + path)
    router.add_api_route(url, create, methods=["POST"], status_code=201, name="create_" + path)
    router.add_api_route(url + "/{record_id}", update, methods=["PATCH"], name="update_" + path)
    router.add_api_route(url + "/{record_id}", delete, methods=["DELETE"], status_code=204, name="delete_" + path)
    if path == "expenses":
        router.add_api_route("/farms/{farm_id}/costs", create, methods=["POST"], status_code=201, include_in_schema=False)


for _path, _model, _schema in [("expenses", Expense, schema.ExpenseInput), ("irrigation", IrrigationEvent, schema.IrrigationInput),
                               ("harvests", Harvest, schema.HarvestInput), ("sales", Sale, schema.SaleInput)]:
    register_records(_path, _model, _schema)


@router.get("/farms/{farm_id}/financials")
def financials(farm_id: str, db: Session = DB):
    farm, _, s = _active_farm(db, farm_id)
    projected = _finance_module(s, datetime.now(timezone.utc))
    actual = calculate_financials({"recorded_costs": [{"id": x.id, "description": x.description, "amount_jod": str(x.amount_jod)} for x in s.expenses],
                                  "projected_costs": [], "future_sales": [],
                                  "actual_sales": [{"id": x.id, "description": "Recorded sale", "quantity_kg": str(x.quantity_kg), "revenue_jod": str(x.quantity_kg * x.unit_price_jod)} for x in s.sales]})
    def number(key):
        return float(Decimal(actual[key])) if actual.get(key) is not None else None
    harvest = sum((x.quantity_kg for x in s.harvests), Decimal(0))
    costs = sum((x.amount_jod for x in s.expenses), Decimal(0))
    sold = sum((x.quantity_kg for x in s.sales), Decimal(0))
    return {"origin": origin(farm), "season_id": s.id, "recorded_costs_jod": float(costs),
            "projected_costs_jod": projected["projected_total_cost_jod"],
            "actual_revenue_jod": number("actual_revenue_jod"), "projected_revenue_jod": projected["projected_revenue_jod"],
            "projected_profit_jod": projected["projected_profit_jod"], "actual_profit_jod": number("projected_profit_jod"),
            "break_even_price_jod": projected["break_even_jod_per_kg"],
            "cost_per_kg_jod": projected["break_even_jod_per_kg"],
            "cost_per_kg_recorded_jod": float(costs / harvest) if harvest else None,
            "actual_cost_per_sold_kg_jod": number("projected_cost_per_kg_jod"),
            "actual_break_even_jod_per_kg": number("break_even_price_jod_per_kg"),
            "actual_sold_kg": float(sold), "fertilizer_budget_jod": s.fertilizer_budget_jod,
            "expected_harvest_kg": s.expected_marketable_kg, "expected_harvest_source": "farmer_estimate",
            "expected_harvest_scope": "active season; remaining marketable quantity",
            "actual_harvest_kg": float(harvest), "actual_harvest_active_season_kg": float(harvest),
            "actual_harvest_source": "recorded", "actual_harvest_scope": "active season",
            "calculation_warnings": projected["warnings"] + projected["assumptions"], "fertilizer_options": [],
            "server_calculated": True}


@router.get("/farms/{farm_id}/fertilizers")
def fertilizers(farm_id: str, db: Session = DB):
    farm, _, season = _active_farm(db, farm_id)
    result = catalog_response()
    budget = float(season.fertilizer_budget_jod) if season.fertilizer_budget_jod is not None else None
    result.update(farm_id=farm_id, farm_name=farm.name or farm.location_name, budget_jod=budget, budget_origin="user_entered")
    for product in result["products"]:
        product.update(budget_jod=budget, within_budget_for_one_pack=budget >= product["price_jod"] if budget is not None else None,
                       budget_remaining_after_one_pack_jod=round(budget - product["price_jod"], 3) if budget is not None else None)
    return result


@router.get("/farms/{farm_id}/weather")
def weather(farm_id: str, db: Session = DB):
    farm, _, _, result, _ = _calculation_context(db, farm_id)
    return {"origin": origin(farm), "date": result.get("forecast_start_date"), "source": result.get("source"),
            "fetched_at": result.get("retrieved_at"), "status": result["status"], "warnings": result.get("warnings", []),
            "days": [{"date": day["date"], "condition": weather_condition(day.get("weather_code")), "high": day.get("temperature_max_c"),
                      "low": day.get("temperature_min_c"), "rain_mm": day.get("precipitation_mm")} for day in result.get("daily", [])]}


def weather_condition(code):
    if code == 0:
        return "sunny"
    if code in (1, 2):
        return "partly"
    if code in (3, 45, 48):
        return "cloudy"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99):
        return "rain"
    return "unknown"


@router.get("/farms/{farm_id}/inspections")
def inspections(farm_id: str, db: Session = DB):
    dashboard = build_dashboard(db, farm_id)
    inspection = dashboard.inspection
    title = {"en": "Routine field inspection", "ar": "فحص حقلي دوري"}
    reason = {"en": "Weather cannot be fully assessed. Continue visual inspection; no disease diagnosis is available.",
              "ar": "لا يمكن تقييم الطقس بالكامل. واصل الفحص البصري؛ هذا ليس تشخيصاً لمرض."}
    reminders = [{"id": "inspection-" + str(i), "title": title, "due_date": None,
                  "reason": {"en": message, "ar": "تنبيه طقس تجريبي؛ تحقق من ظروف الحقل، وليس تشخيصاً لمرض."}}
                 for i, message in enumerate(inspection.alerts)]
    if inspection.assessment == "cannot_assess":
        reminders.append({"id": "cannot-assess", "title": title, "due_date": None, "reason": reason})
    return {"origin": "sample" if dashboard.is_sample else "api", "reminders": reminders,
            "assessment": inspection.assessment, "limitations": inspection.limitations}


@router.get("/farms/{farm_id}/recommendations")
def recommendations(farm_id: str, db: Session = DB):
    dashboard = build_dashboard(db, farm_id)
    missing = dashboard.irrigation.missing_inputs + dashboard.finance.missing_inputs
    # Deterministic, bilingual reminders; no unreviewed treatment prescriptions.
    item = {"id": farm_id + "-review", "topic": "data",
            "summary": {"en": "Review the current farm calculations and their limitations.", "ar": "راجع حسابات المزرعة الحالية وحدودها."},
            "action": {"en": "Verify missing inputs: " + ", ".join(missing) if missing else "Compare the forecast estimate with field observations before acting.",
                       "ar": "تحقق من المدخلات الناقصة وقارن التقديرات بملاحظات الحقل قبل اتخاذ قرار."},
            "why": {"en": "These are demonstration estimates, not a disease diagnosis or a validated irrigation schedule.",
                    "ar": "هذه تقديرات تجريبية وليست تشخيصاً لمرض أو جدول ري معتمداً."},
            "limitations": [{"en": "Consult a local agricultural advisor for field-specific decisions.", "ar": "استشر مرشداً زراعياً للقرارات الخاصة بالحقل."}],
            "sources": [], "evidence": []}
    return {"origin": "sample" if dashboard.is_sample else "api", "recommendations": [item]}


@router.post("/assistant/chat")
def chat(payload: schema.ChatInput, db: Session = DB):
    result = answer_question(db, AssistantRequest(farm_id=payload.farm_id, question=payload.message, language=payload.language))
    return {"answer": result.answer, "sources": [{"title": r.title, "url": r.source_url} for r in result.document_references],
            "origin": "fallback" if result.used_fallback else "api", "limitations": result.limitations}
