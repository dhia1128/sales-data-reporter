from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from markupsafe import Markup
from sqlalchemy.orm import Session

from app.config import BASE_DIR, get_settings
from app.database import get_db
from app.services import reports

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
summary_markdown = MarkdownIt("commonmark", {"html": False})
templates.env.filters["summary_markdown"] = lambda value: Markup(summary_markdown.render(value or ""))
templates.env.filters["fmt"] = lambda v: "n/a" if v is None else f"{v:,.2f}"
templates.env.filters["pct"] = lambda v: "n/a" if v is None else f"{v:+.2f}%"
templates.env.globals["app_name"] = get_settings().app_name

router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "index.html", {"reports": reports.list_reports(db, 10), "error": None}
    )


@router.post("/analyze")
def analyze(file: UploadFile, db: Session = Depends(get_db)):
    report = reports.create_report(db, file)
    return RedirectResponse(f"/reports/{report.id}", status_code=303)


@router.get("/reports/{report_id}", response_class=HTMLResponse)
def show_report(report_id: int, request: Request, db: Session = Depends(get_db)):
    report = reports.get_report(db, report_id)
    return templates.TemplateResponse(request, "report.html", {"report": report, "stats": report.stats})


@router.post("/reports/{report_id}/regenerate")
def regenerate(report_id: int, db: Session = Depends(get_db)):
    reports.regenerate_summary(db, report_id)
    return RedirectResponse(f"/reports/{report_id}", status_code=303)
