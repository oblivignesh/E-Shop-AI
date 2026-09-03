"""Ingest raw CSVs from data/raw/ into a SQLite database at data/aura.db.

Schema-tolerant: uses pandas to sniff columns, normalizes column names to
snake_case, and creates one table per CSV. Adds indexes on obvious join keys
(*_id) after load. Prints a summary table of row counts.

Run:
    python scripts/ingest.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from aura.config import settings  # noqa: E402

console = Console()

EXPECTED_TABLES = [
    "customers",
    "orders",
    "order_items",
    "shipments",
    "refund_cases",
    "approval_requests",
]


def _snake(name: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip())
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower().strip("_")


def _find_csv(raw_dir: Path, table: str) -> Path | None:
    for p in raw_dir.iterdir():
        if p.suffix.lower() != ".csv":
            continue
        stem = _snake(p.stem)
        if stem == table:
            return p
    return None


def _load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [_snake(c) for c in df.columns]
    # Attempt to parse ISO-like date columns; leave unparseable columns alone.
    for col in df.columns:
        if any(tok in col for tok in ("_at", "_date", "date_")):
            try:
                df[col] = pd.to_datetime(df[col], errors="coerce", utc=False)
            except (ValueError, TypeError):
                pass
    return df


def _index_id_columns(engine, table: str, df: pd.DataFrame) -> list[str]:
    created = []
    with engine.begin() as conn:
        for col in df.columns:
            if col.endswith("_id") or col == "id":
                idx = f"idx_{table}_{col}"
                conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{idx}" ON "{table}" ("{col}")'))
                created.append(col)
    return created


def main() -> int:
    raw_dir = settings.raw_data_dir
    if not raw_dir.exists():
        console.print(f"[red]Raw data dir not found: {raw_dir}[/red]")
        return 1

    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.db_url, future=True)

    summary = Table(title="AURA ingest summary")
    summary.add_column("Table")
    summary.add_column("Source CSV")
    summary.add_column("Rows", justify="right")
    summary.add_column("Cols", justify="right")
    summary.add_column("Indexed keys")

    missing: list[str] = []
    for table in EXPECTED_TABLES:
        csv = _find_csv(raw_dir, table)
        if not csv:
            missing.append(table)
            summary.add_row(table, "-- MISSING --", "0", "0", "")
            continue
        df = _load_csv(csv)
        df.to_sql(table, engine, if_exists="replace", index=False)
        idx_cols = _index_id_columns(engine, table, df)
        summary.add_row(
            table, csv.name, str(len(df)), str(len(df.columns)), ", ".join(idx_cols) or "-"
        )

    console.print(summary)
    console.print(f"[green]SQLite DB written to:[/green] {settings.db_path}")

    if missing:
        console.print(
            f"[yellow]Warning:[/yellow] the following expected tables had no CSV: "
            f"{', '.join(missing)}"
        )
        console.print(
            "[yellow]Agent tools depending on those tables will return empty results.[/yellow]"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
