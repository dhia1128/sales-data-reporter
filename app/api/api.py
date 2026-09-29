from fastapi import APIRouter, Depends, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ReportDetail, ReportOut
from app.services import reports

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.post("", response_model=ReportDetail, status_code=201)
def create_report(file: UploadFile, db: Session = Depends(get_db)):
    """Upload any CSV and get a statistical profile plus an AI-written summary."""
    return reports.create_report(db, file)


@router.get("", response_model=list[ReportOut])
def list_reports(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    return reports.list_reports(db, limit)


@router.get("/{report_id}", response_model=ReportDetail)
def get_report(report_id: int, db: Session = Depends(get_db)):
    return reports.get_report(db, report_id)


@router.post("/{report_id}/summary", response_model=ReportDetail)
def regenerate_summary(report_id: int, db: Session = Depends(get_db)):
    """Re-run the LLM step, e.g. after starting Ollama."""
    return reports.regenerate_summary(db, report_id)


@router.delete("/{report_id}", status_code=204)
def delete_report(report_id: int, db: Session = Depends(get_db)):
    reports.delete_report(db, report_id)
    return Response(status_code=204)
