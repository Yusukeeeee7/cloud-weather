import datetime as dt
import re
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BeforeValidator

from app.cities import City
from app.date_range import MAX_DATE, MIN_DATE
from app.routers.weather import get_clock
from app.schemas import DaylightResponse, ErrorResponse
from app.services import daylight as daylight_service
from app.services.weather import Clock

router = APIRouter()

# 半角数字の YYYY-MM-DD だけ（pydantic の日付の解釈は、数字だけの文字列なども受け付けるため）。
_DATE_FORMAT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _parse_date(value: object) -> dt.date:
    if not isinstance(value, str) or _DATE_FORMAT.fullmatch(value) is None:
        raise ValueError("date must be YYYY-MM-DD")
    day = dt.date.fromisoformat(value)
    if not MIN_DATE <= day <= MAX_DATE:
        raise ValueError("date is out of range")
    return day


DateQuery = Annotated[dt.date, BeforeValidator(_parse_date)]


@router.get(
    "/daylight",
    responses={422: {"model": ErrorResponse, "description": "invalid_city / invalid_date"}},
)
async def get_daylight(
    clock: Annotated[Clock, Depends(get_clock)],
    city: City = City.TOKYO,
    date: DateQuery | None = None,
) -> DaylightResponse:
    return daylight_service.get_daylight(city, date, clock)
