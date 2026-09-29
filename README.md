# Data Report Analyzer

Upload any CSV. The app detects what each column is, computes statistics, asks a
local LLM (Ollama) to write the narrative, and stores everything in a database.

## Run

### Windows PowerShell

```bash
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env     # optional
ollama pull llama3.2:latest
uvicorn app.main:app --reload
```

Ollama must be running while generating summaries. If it is not already running, start it in a separate terminal with `ollama serve`.

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional
ollama pull llama3.2:latest
uvicorn app.main:app --reload
```

- Web UI: http://127.0.0.1:8000
- API docs: http://127.0.0.1:8000/docs

## Summaries

- The default Ollama model is `llama3.2:latest`.
- Summaries are written in French by default. Set `REPORT_LANGUAGE` in `.env` to choose another language.
- Summary Markdown is rendered with headings, paragraphs, emphasis, and lists in the report page.
- Use **Regenerate summary** on a report page to create a fresh summary with the current model and language settings. The API equivalent is `POST /api/reports/{id}/summary`.

## Structure

```
app/
  main.py          app factory, lifespan (creates tables), error handler
  config.py        Settings from env / .env (pydantic-settings)
  database.py      engine, session, get_db dependency, init_db
  models.py        Dataset, Report (SQLAlchemy 2.0)
  schemas.py       Pydantic response models
  exceptions.py    user-facing errors (400/404/422)
  api/api.py       JSON endpoints under /api/reports
  api/web.py       HTML pages
  services/
    profiler.py    column typing + statistics (pure pandas, no I/O besides reading the CSV)
    llm.py         prompt + Ollama call (LangChain LCEL)
    reports.py     upload -> profile -> LLM -> DB
  templates/       base, index, report
```

## Database

| datasets | reports |
|---|---|
| id, original_filename, stored_path | id, dataset_id (FK, cascade) |
| n_rows, n_columns | status (`completed` / `llm_failed`) |
| columns (JSON: name, role, dtype, missing, unique) | stats (JSON), summary, error |
| created_at | language, llm_model, created_at |

SQLite by default; set `DATABASE_URL` for Postgres (`postgresql+psycopg://...`).

## API

```bash
curl -F "file=@sales_data.csv" http://127.0.0.1:8000/api/reports      # create
curl http://127.0.0.1:8000/api/reports                                  # list
curl http://127.0.0.1:8000/api/reports/1                                # detail
curl -X POST http://127.0.0.1:8000/api/reports/1/summary                # re-run the LLM
curl -X DELETE http://127.0.0.1:8000/api/reports/1
```

## How it generalizes

- Column roles: `numeric`, `date`, `categorical`, `text`, `id`. Text like `"1,200 DT"` is
  converted to numbers and date strings to dates.
- Primary measure: prefers names containing sales, revenue, amount, total, price...
  otherwise the first numeric column. Primary date: date, quarter, month, period...
- Time series: period size (day/week/month/quarter/year) is chosen from the gaps between dates.
  Values are summed per period.
- Breakdowns (top categories by share), correlations, outliers and data-quality warnings
  are computed only when the columns exist.
- Ambiguous dates like `05/03/2024` follow `DATE_DAYFIRST`.

## Known limits / next steps

- Decimal commas (`1,5`) are read as thousands separators.
- Analysis runs inside the request. For big files or slow models, move it to a background task queue.
- Replace `create_all` with Alembic before changing the schema in production.
- No authentication; add it before exposing the app.
