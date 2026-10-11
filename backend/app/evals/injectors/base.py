"""Injector framework (spec §12). Injectors plant *additional* errors blindly (seed drawn at run time) into a fork and record
each plant in answer_key.planted. Data is changed on the app connection; the answer key is written on the eval_admin connection."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from psycopg import Connection

from app.seed.common import fetch_df

REGISTRY: dict[str, "Injector"] = {}


def register(cls):
    REGISTRY[cls.kind] = cls()
    return cls


@dataclass
class InjectContext:
    data: Connection
    key: Connection
    rng: np.random.Generator
    run_id: str
    today: date
    horizon: date                                   # rows entering EDC in (today, horizon] are eligible, so they surface during the run
    used: dict[str, set] = field(default_factory=dict)
    planted: int = 0

    def record(self, kind: str, module: str, src_table: str | None, src_pk, field_: str | None, original, injected,
               usubjid: str | None = None, site_id: str | None = None) -> None:
        self.key.execute(
            "INSERT INTO answer_key.planted (scenario_run_id, kind, module, usubjid, site_id, src_table, src_pk, field, original, injected) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (self.run_id, kind, module, usubjid, site_id, src_table, None if src_pk is None else str(src_pk), field_,
             None if original is None else str(original), None if injected is None else str(injected)))
        self.planted += 1

    def window(self, table: str, cols: str, where: str = "true", params: tuple = ()) -> pd.DataFrame:
        """Rows of edc_pending.<table> that will be released inside the run, not yet used by another injector."""
        df = fetch_df(self.data, f"SELECT {cols} FROM edc_pending.{table} WHERE entered_at > %s AND entered_at <= %s AND {where}", (self.today, self.horizon, *params))
        if "id" in df:
            df = df[~df.id.isin(self.used.setdefault(table, set()))]
        return df

    def pick(self, df: pd.DataFrame, n: int, table: str) -> pd.DataFrame:
        n = min(n, len(df))
        out = df.iloc[self.rng.choice(len(df), n, replace=False)] if n else df.iloc[0:0]
        if "id" in out:
            self.used.setdefault(table, set()).update(out.id)
        return out


class Injector(ABC):
    kind: str
    module: str

    @abstractmethod
    def apply(self, ctx: InjectContext, count: int, params: dict) -> int:
        """Plant up to `count` items; return how many were planted."""


def run_injections(ctx: InjectContext, specs) -> dict[str, int]:
    done: dict[str, int] = {}
    for s in specs:
        inj = REGISTRY.get(s.kind)
        if inj is None:
            raise KeyError(f"unknown injector kind: {s.kind}")
        before = ctx.planted
        inj.apply(ctx, s.count, s.params)
        done[s.kind] = done.get(s.kind, 0) + ctx.planted - before
    return done
