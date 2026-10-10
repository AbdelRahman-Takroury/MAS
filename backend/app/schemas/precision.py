"""Storage-compatible decimal inputs. Reject excess precision rather than round silently."""
from decimal import Decimal
from typing import Annotated
from pydantic import Field

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3, allow_inf_nan=False)]
Liters = Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=3, allow_inf_nan=False)]
Duration = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=3, allow_inf_nan=False)]
Flow = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3, allow_inf_nan=False)]
