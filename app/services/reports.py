"""Orchestrates upload -> profile -> LLM -> database."""
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.exceptions import AppError, InvalidUpload, NotFound, UnprocessableData
from app.models import Dataset, Report, ReportStatus
from app.services import llm, profiler

logger = logging.getLogger(__name__)


def _save_upload(upload: UploadFile) -> Path:
    settings = get_settings()
    name = upload.filename or ""
    if not name.lower().endswith(".csv"):
        raise InvalidUpload("Upload a .csv file.")

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.upload_dir / f"{uuid4().hex}.csv"
    limit = settings.max_upload_mb * 1024 * 1024
    size, too_big = 0, False

    with dest.open("wb") as out:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                too_big = True
                break
            out.write(chunk)

    if too_big:
        dest.unlink(missing_ok=True)
        raise InvalidUpload(f"File is larger than {settings.max_upload_mb} MB.")
    return dest


def _fill_summary(report: Report) -> None:
    """Ask the LLM for the narrative. A failure downgrades the report, it doesn't lose it."""
    try:
        report.summary = llm.generate_summary(report.stats, report.language, report.llm_model)
        report.status = ReportStatus.COMPLETED.value
        report.error = None
    except Exception as exc:  # Ollama down, model missing, timeout...
        logger.warning("LLM summary failed: %s", exc)
        report.status = ReportStatus.LLM_FAILED.value
        report.error = f"The AI summary could not be generated: {exc}"


def create_report(db: Session, upload: UploadFile) -> Report:
    settings = get_settings()
    path = _save_upload(upload)

    try:
        df = profiler.load_dataframe(path)
        df, columns = profiler.infer_columns(df)
        stats = profiler.build_stats(df, columns, settings.top_n)
    except AppError:
        path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        path.unlink(missing_ok=True)
        logger.exception("Profiling failed")
        raise UnprocessableData(f"Could not analyze this file: {exc}") from exc

    report = Report(
        dataset=Dataset(
            original_filename=(upload.filename or "upload.csv")[:255],
            stored_path=str(path),
            n_rows=len(df),
            n_columns=len(df.columns),
            columns=columns,
        ),
        stats=stats,
        language=settings.report_language,
        llm_model=settings.ollama_model,
    )
    _fill_summary(report)

    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def get_report(db: Session, report_id: int) -> Report:
    report = db.scalar(
        select(Report).options(selectinload(Report.dataset)).where(Report.id == report_id)
    )
    if report is None:
        raise NotFound(f"Report {report_id} was not found.")
    return report


def list_reports(db: Session, limit: int = 20) -> list[Report]:
    stmt = (
        select(Report)
        .options(selectinload(Report.dataset))
        .order_by(Report.created_at.desc(), Report.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def regenerate_summary(db: Session, report_id: int) -> Report:
    report = get_report(db, report_id)
    settings = get_settings()
    report.llm_model = settings.ollama_model
    report.language = settings.report_language
    _fill_summary(report)
    db.commit()
    db.refresh(report)
    return report


def delete_report(db: Session, report_id: int) -> None:
    report = get_report(db, report_id)
    path = Path(report.dataset.stored_path)
    db.delete(report.dataset)  # cascades to the report
    db.commit()
    path.unlink(missing_ok=True)
