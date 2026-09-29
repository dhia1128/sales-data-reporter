import enum
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReportStatus(str, enum.Enum):
    COMPLETED = "completed"      # stats + LLM summary ready
    LLM_FAILED = "llm_failed"    # stats ready, LLM summary missing (can be regenerated)


class Dataset(Base):
    """One uploaded CSV file and what we learned about its structure."""

    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    n_rows: Mapped[int]
    n_columns: Mapped[int]
    # [{"name", "role", "dtype", "missing", "missing_pct", "unique"}, ...]
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    reports: Mapped[list["Report"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class Report(Base):
    """Computed statistics plus the LLM-written summary for a dataset."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default=ReportStatus.COMPLETED.value)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    language: Mapped[str] = mapped_column(String(30))
    llm_model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    dataset: Mapped[Dataset] = relationship(back_populates="reports")
