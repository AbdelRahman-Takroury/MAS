"""A period-specific allocation; missing amount and dates must remain null together."""
from datetime import date
from decimal import Decimal
from pydantic import Field, model_validator
from .common import StrictModel


class WaterAllocationFields(StrictModel):
    water_available_liters: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=3, allow_inf_nan=False)
    water_period_start: date | None = None
    water_period_end: date | None = None

    @model_validator(mode='after')
    def allocation_period(self):
        values = (self.water_available_liters, self.water_period_start, self.water_period_end)
        if any(v is not None for v in values):
            if any(v is None for v in values):
                raise ValueError('Water amount and both inclusive period dates must be supplied together')
            if self.water_period_end < self.water_period_start:
                raise ValueError('Water period end must be on or after its start')
            season_start = getattr(self, 'establishment_date', getattr(self, 'start_date', None))
            season_end = getattr(self, 'end_date', None)
            if season_start and self.water_period_start < season_start:
                raise ValueError('Water period cannot start before crop establishment')
            if season_end and self.water_period_end > season_end:
                raise ValueError('Water period cannot end after the crop season')
        return self
