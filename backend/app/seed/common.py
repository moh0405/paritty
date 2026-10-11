"""Shared helpers for the seed scripts (spec §6-7)."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import psycopg

from app.config import get_settings

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw"
PROTOCOL = ROOT / "data" / "protocol"


def connect() -> psycopg.Connection:
    return psycopg.connect(get_settings().database_url)


def rng(salt: int = 0) -> np.random.Generator:
    return np.random.default_rng(get_settings().seed * 1000 + salt)


def fetch_df(conn: psycopg.Connection, query: str, params: Iterable | None = None) -> pd.DataFrame:
    cur = conn.execute(query, params)
    cols = [d.name for d in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=cols)


def copy_df(conn: psycopg.Connection, table: str, df: pd.DataFrame) -> int:
    """COPY a dataframe into schema.table using its column names. NaN/NaT become NULL."""
    if df.empty:
        return 0
    cols = list(df.columns)
    clean = df.astype(object).where(df.notna(), None)
    with conn.cursor() as cur:
        with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
            for row in clean.itertuples(index=False, name=None):
                cp.write_row(row)
    return len(df)


def subj_num(usubjid: str) -> str:
    """'01-701-1015' -> '1015'"""
    return usubjid.split("-")[-1]


def site_of(usubjid: str) -> str:
    return usubjid.split("-")[1]


SEEDED_TABLES = [
    "lab_vendor.transfer", "safety.case_versions", "mock_safety.inbox", "ctms.sites", "ctms.deviations",
    "ctms.monitoring_visits", "ctms.screening", "irt.kits", "unblinded.randomization",
    "hub.site_xwalk", "hub.subject_xwalk", "hub.catalog", "hub.dq_results", "hub.lab_test_map",
    "ai.ae_terms", "ai.protocol_chunks", "answer_key.site_personality", "answer_key.planted",
    "answer_key.causality_reference", "answer_key.crosswalk_truth", "answer_key.eligibility_qa",
]


def reset_seeded(conn: psycopg.Connection) -> None:
    """Start-of-seed reset: every table any seed script fills (spec §15 'seed' is re-runnable)."""
    conn.execute("TRUNCATE " + ", ".join(SEEDED_TABLES) + " RESTART IDENTITY")
