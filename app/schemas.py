from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_filename: str
    n_rows: int
    n_columns: int
    created_at: datetime


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    language: str
    llm_model: str
    created_at: datetime
    dataset: DatasetOut


class ReportDetail(ReportOut):
    summary: str | None
    error: str | None
    stats: dict[str, Any]
