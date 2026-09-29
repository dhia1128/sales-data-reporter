"""Shape-agnostic CSV profiling.

Nothing here assumes column names. Each column is classified as one of:
numeric, date, categorical, text, or id. Then we pick a "primary measure"
(e.g. sales/revenue/amount) and a "primary date" column when they exist and
compute everything else from that.

All output is plain JSON-safe Python (no numpy types) so it can be stored in a
JSON column and sent to the LLM as-is.
"""
from __future__ import annotations

import csv
import re
import warnings
from typing import Any

import numpy as np
import pandas as pd

from app.config import get_settings
from app.exceptions import UnprocessableData

MEASURE_HINTS = (
    "sales", "revenue", "turnover", "income", "profit", "amount",
    "total", "cost", "price", "value", "units", "quantity", "qty",
)
DATE_HINTS = ("date", "quarter", "month", "period", "year", "time", "day")
ID_PATTERN = re.compile(r"(^|[_\s-])id$", re.IGNORECASE)
NUMBER_NOISE = re.compile(r"[,\s$€£¥%]|TND|DT|USD|EUR", re.IGNORECASE)

MAX_CATEGORY_LEVELS = 50
MAX_SERIES_POINTS = 60


# --------------------------------------------------------------------------
# Loading and column typing
# --------------------------------------------------------------------------
def _num(x: Any, nd: int = 2) -> float | None:
    try:
        if x is None or pd.isna(x) or np.isinf(x):
            return None
        return round(float(x), nd)
    except (TypeError, ValueError):
        return None


def _read(path, encoding: str) -> pd.DataFrame:
    with open(path, encoding=encoding, newline="") as fh:
        sample = fh.read(8192)
    try:
        sep = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        sep = ","  # single-column files have nothing to sniff
    return pd.read_csv(path, sep=sep, encoding=encoding, index_col=False)


def load_dataframe(path) -> pd.DataFrame:
    df = None
    for encoding in ("utf-8-sig", "cp1256", "latin-1"):  # latin-1 never fails
        try:
            df = _read(path, encoding)
            break
        except UnicodeDecodeError:
            continue
        except pd.errors.EmptyDataError:
            raise UnprocessableData("The file is empty.") from None
        except pd.errors.ParserError as exc:
            raise UnprocessableData(f"Could not parse the CSV: {exc}") from exc

    if df is None:
        raise UnprocessableData("Could not read the file with a supported encoding.")

    df = df.dropna(how="all").dropna(axis=1, how="all")
    df.columns = [str(c).strip() for c in df.columns]
    if df.empty:
        raise UnprocessableData("The file has no data rows.")
    return df


def _to_datetime(s: pd.Series) -> pd.Series:
    """Parse a column with ONE consistent day/month order.

    Try both orders and keep whichever parses more cells. Ambiguous columns
    (every day <= 12) fall back to DATE_DAYFIRST from the settings.
    """
    prefer = get_settings().date_dayfirst
    best = None
    for dayfirst in (prefer, not prefer):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parsed = pd.to_datetime(s, errors="coerce", dayfirst=dayfirst)
        if best is None or parsed.notna().sum() > best.notna().sum():
            best = parsed
    return best


def infer_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Return a copy of df with converted dtypes, plus per-column metadata."""
    df = df.copy()
    columns: list[dict[str, Any]] = []

    for col in df.columns:
        s = df[col]

        if pd.api.types.is_bool_dtype(s):
            role = "categorical"
        elif pd.api.types.is_numeric_dtype(s):
            role = "id" if ID_PATTERN.search(col) else "numeric"
        elif pd.api.types.is_datetime64_any_dtype(s):
            role = "date"
        else:
            cleaned = s.dropna().astype(str).str.strip()
            cleaned = cleaned[cleaned != ""]
            if cleaned.empty:
                role = "text"
            else:
                as_num = pd.to_numeric(cleaned.str.replace(NUMBER_NOISE, "", regex=True), errors="coerce")
                if as_num.notna().mean() >= 0.9:
                    df[col] = pd.to_numeric(
                        s.astype(str).str.replace(NUMBER_NOISE, "", regex=True).str.strip(),
                        errors="coerce",
                    )
                    role = "numeric"
                else:
                    parsed = _to_datetime(s)
                    if parsed.notna().sum() / max(s.notna().sum(), 1) >= 0.9:
                        df[col] = parsed
                        role = "date"
                    else:
                        nunique, non_null = s.nunique(), max(s.notna().sum(), 1)
                        role = (
                            "categorical"
                            if nunique <= MAX_CATEGORY_LEVELS or nunique / non_null <= 0.5
                            else "text"
                        )

        col_s = df[col]
        columns.append({
            "name": col,
            "role": role,
            "dtype": str(col_s.dtype),
            "missing": int(col_s.isna().sum()),
            "missing_pct": _num(col_s.isna().mean() * 100),
            "unique": int(col_s.nunique(dropna=True)),
        })

    return df, columns


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------
def _pick(names: list[str], hints: tuple[str, ...]) -> str | None:
    for hint in hints:
        for name in names:
            if hint in name.lower():
                return name
    return names[0] if names else None


def _measure_stats(df: pd.DataFrame, names: list[str]) -> list[dict[str, Any]]:
    out = []
    for name in names:
        s = df[name].dropna()
        if s.empty:
            continue
        outliers = 0
        if len(s) >= 8:
            q1, q3 = s.quantile(0.25), s.quantile(0.75)
            iqr = q3 - q1
            outliers = int(((s < q1 - 1.5 * iqr) | (s > q3 + 1.5 * iqr)).sum())
        out.append({
            "name": name,
            "count": int(s.count()),
            "sum": _num(s.sum()),
            "mean": _num(s.mean()),
            "median": _num(s.median()),
            "std": _num(s.std()),
            "min": _num(s.min()),
            "max": _num(s.max()),
            "outliers": outliers,
        })
    return out


def _granularity(dates: pd.Series) -> tuple[str, str]:
    """Pick a period size from the typical gap between distinct dates."""
    if len(dates) < 2:
        return "M", "month"
    gaps = dates.diff().dropna().dt.days
    median_gap = gaps.median()
    span = (dates.max() - dates.min()).days

    if median_gap <= 1.5:
        return ("D", "day") if span <= 90 else ("M", "month")
    if median_gap <= 10:
        return ("W", "week") if span <= 400 else ("M", "month")
    if median_gap <= 45:
        return "M", "month"
    if median_gap <= 120:
        return "Q", "quarter"
    return "Y", "year"


def _pct(old: float, new: float) -> float | None:
    if old is None or pd.isna(old) or old == 0:
        return None
    return _num((new - old) / abs(old) * 100)


def _time_series(df: pd.DataFrame, date_col: str, measure: str) -> dict[str, Any] | None:
    data = df[[date_col, measure]].dropna()
    if len(data) < 2:
        return None

    freq, label = _granularity(data[date_col].drop_duplicates().sort_values())
    series = (
        data.groupby(data[date_col].dt.to_period(freq))[measure]
        .sum()
        .sort_index()
        .astype(float)
    )
    if len(series) < 2:
        return None

    values = series.values
    changes = series.pct_change().replace([np.inf, -np.inf], np.nan).dropna()

    trend = None
    if len(values) >= 3 and values.mean() != 0:
        slope = np.polyfit(np.arange(len(values)), values, 1)[0]
        relative = slope / abs(values.mean())
        trend = "increasing" if relative > 0.02 else "decreasing" if relative < -0.02 else "flat"

    # Rows rolled up into a period that hasn't finished yet make the latest change look worse than it is
    last_period = series.index[-1]
    rows_in_last = int((data[date_col].dt.to_period(freq) == last_period).sum())
    partial = rows_in_last > 1 and data[date_col].max().normalize() < last_period.end_time.normalize()

    points = [{"period": str(p), "value": _num(v)} for p, v in series.items()]
    best, worst = series.idxmax(), series.idxmin()

    return {
        "date_column": date_col,
        "measure": measure,
        "aggregation": "sum",
        "granularity": label,
        "n_periods": len(series),
        "points": points[-MAX_SERIES_POINTS:],
        "previous_period": str(series.index[-2]),
        "last_period": str(series.index[-1]),
        "last_change_pct": _pct(values[-2], values[-1]),
        "total_change_pct": _pct(values[0], values[-1]),
        "avg_growth_pct": _num(changes.mean() * 100) if len(changes) else None,
        "trend": trend,
        "last_period_partial": bool(partial),
        "best_period": {"period": str(best), "value": _num(series[best])},
        "worst_period": {"period": str(worst), "value": _num(series[worst])},
    }


def _breakdowns(df: pd.DataFrame, cats: list[str], measure: str | None, top_n: int) -> list[dict[str, Any]]:
    usable = sorted((c for c in cats if 2 <= df[c].nunique() <= MAX_CATEGORY_LEVELS), key=lambda c: df[c].nunique())
    out = []
    for col in usable[:3]:
        if measure:
            grouped = df.groupby(col, dropna=True)[measure].sum().sort_values(ascending=False)
            metric = f"sum of {measure}"
        else:
            grouped = df[col].value_counts()
            metric = "row count"
        total = grouped.sum()
        items = [
            {
                "value": str(k),
                "amount": _num(v),
                "share_pct": _num(v / total * 100) if total else None,
            }
            for k, v in grouped.head(top_n).items()
        ]
        out.append({"column": col, "metric": metric, "distinct": int(df[col].nunique()), "top": items})
    return out


def _correlations(df: pd.DataFrame, numeric: list[str]) -> list[dict[str, Any]]:
    cols = numeric[:8]
    if len(cols) < 2 or len(df) < 3:
        return []
    corr = df[cols].corr()
    pairs = []
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            r = corr.loc[a, b]
            if pd.notna(r) and abs(r) >= 0.5:
                pairs.append({"a": a, "b": b, "r": _num(r)})
    return sorted(pairs, key=lambda p: abs(p["r"]), reverse=True)[:3]


def _warnings(df, columns, measure, date_col, ts) -> list[str]:
    notes = []
    for c in columns:
        if c["missing_pct"] and c["missing_pct"] > 20:
            notes.append(f"Column '{c['name']}' is {c['missing_pct']}% empty.")
    if (dupes := int(df.duplicated().sum())) > 0:
        notes.append(f"{dupes} duplicate rows found.")
    if measure is None:
        notes.append("No numeric column found, so the report is limited to counts.")
    else:
        if (df[measure] < 0).any():
            notes.append(f"'{measure}' contains negative values (returns or refunds?).")
        if date_col is None:
            notes.append("No date column detected, so trend analysis was skipped.")
        elif ts is None:
            notes.append("Not enough dated rows to compute a trend.")
        elif ts["last_period_partial"]:
            notes.append(
                f"The last {ts['granularity']} ({ts['last_period']}) looks incomplete, "
                "so the latest change may be understated."
            )
        if ts and ts["n_periods"] < 4:
            notes.append(f"Only {ts['n_periods']} {ts['granularity']}s of data; treat the trend with caution.")
    return notes


def build_stats(df: pd.DataFrame, columns: list[dict[str, Any]], top_n: int = 5) -> dict[str, Any]:
    by_role: dict[str, list[str]] = {}
    for c in columns:
        by_role.setdefault(c["role"], []).append(c["name"])

    numeric = by_role.get("numeric", [])
    dates = by_role.get("date", [])
    cats = by_role.get("categorical", [])

    measure = _pick(numeric, MEASURE_HINTS)
    date_col = _pick(dates, DATE_HINTS)
    ts = _time_series(df, date_col, measure) if (measure and date_col) else None

    date_range = None
    if date_col:
        d = df[date_col].dropna()
        if not d.empty:
            date_range = {"start": d.min().date().isoformat(), "end": d.max().date().isoformat()}

    return {
        "overview": {
            "rows": len(df),
            "columns": len(columns),
            "duplicate_rows": int(df.duplicated().sum()),
            "missing_pct": _num(df.isna().sum().sum() / df.size * 100),
            "date_range": date_range,
        },
        "columns": columns,
        "primary_measure": measure,
        "date_column": date_col,
        "measures": _measure_stats(df, numeric[:8]),
        "time_series": ts,
        "breakdowns": _breakdowns(df, cats, measure, top_n),
        "correlations": _correlations(df, numeric),
        "warnings": _warnings(df, columns, measure, date_col, ts),
    }
