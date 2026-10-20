from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"]


@router.get("/health")
def get_health() -> HealthResponse:
    return HealthResponse(status="ok")


# 確認用（#54、マージしない）：CodeQL の py/path-injection が指摘することを確かめる。
@router.get("/debug-file")
def get_debug_file(path: str) -> str:
    return Path(path).read_text()
