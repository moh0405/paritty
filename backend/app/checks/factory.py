"""CheckFactory: compile an EditCheckSpec into parameterized SQL. Tables/columns come only from ALLOWED;
anything else is rejected, and all values are bound parameters (spec §9.2, §16)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from psycopg import Connection

from app.checks.base import EditCheckSpec, Failure
from app.sim.schedule import ENTRY_GRACE_DAYS, SCHEDULE, WINDOW

ALLOWED: dict[str, set[str]] = {
    "edc.vitals": {"id", "usubjid", "site_id", "test_code", "value", "unit", "visit", "measured_at", "entered_at"},
    "edc.lab": {"id", "usubjid", "site_id", "test_code", "value", "unit", "uln", "lln", "x_uln", "ctcae_grade", "visit",
                "collected_at", "entered_at", "source_seq"},
    "edc.ae": {"id", "usubjid", "site_id", "source_seq", "term_verbatim", "term_coded", "onset_at", "end_at", "serious",
               "severity", "ctcae_grade", "causality", "outcome", "entered_at"},
    "edc.visits": {"id", "usubjid", "site_id", "visit", "planned_day", "actual_date", "entered_at"},
    "edc.exposure": {"id", "usubjid", "site_id", "dose", "start_at", "end_at", "entered_at"},
    "edc.conmeds": {"id", "usubjid", "site_id", "term", "start_at", "end_at", "entered_at"},
    "edc.subjects": {"usubjid", "site_id", "age", "sex", "consent_at", "first_dose_at", "discontinued_at", "death_at", "status"},
}
SCHEDULED_VISITS = ["SCREENING 1", "SCREENING 2", "BASELINE"] + [v for v, _ in SCHEDULE]


class SpecError(ValueError):
    pass


def _tbl(name: str) -> str:
    if name not in ALLOWED:
        raise SpecError(f"table not allowed: {name}")
    return name


def _col(table: str, col: str) -> str:
    _tbl(table)
    if col not in ALLOWED[table]:
        raise SpecError(f"column not allowed: {table}.{col}")
    return col


def _date(table: str, col: str, alias: str = "t") -> str:
    _col(table, col)
    return f"{alias}.{col}::date" if col.endswith(("collected_at", "measured_at")) else f"{alias}.{col}"


SELECT = "SELECT '{tbl}' AS src_table, {pk}::text AS src_pk, t.usubjid, t.site_id, {obs}::text AS observed, {exp}::text AS expected"


@dataclass
class Compiled:
    spec_id: str
    row_table: str | None                       # short edc table name for incremental runs; None = always full
    build: Callable[[list[int] | None], tuple[str, dict]]

    @property
    def incremental(self) -> bool:
        return self.row_table is not None

    def run(self, conn: Connection, ids: list[int] | None = None) -> list[Failure]:
        sql, params = self.build(ids)
        cur = conn.execute(sql, params)
        return [Failure(src_table=r[0], src_pk=r[1], usubjid=r[2], site_id=r[3], observed=r[4], expected=r[5])
                for r in cur.fetchall()]


def _ids_clause(ids: list[int] | None, alias: str = "t") -> tuple[str, dict]:
    return (f" AND {alias}.id = ANY(%(ids)s)", {"ids": ids}) if ids is not None else ("", {})


class CheckFactory:
    def compile(self, spec: EditCheckSpec) -> Compiled:
        fn = getattr(self, f"_{spec.type}", None)
        if fn is None:
            raise SpecError(f"check type not implemented yet: {spec.type}")
        return fn(spec)

    # ---- range -----------------------------------------------------------------------------
    def _range(self, spec: EditCheckSpec) -> Compiled:
        p = spec.params
        table, col = _tbl(p["table"]), _col(p["table"], p["column"])
        lo, hi = p.get("min"), p.get("max")
        if lo is None and hi is None:
            raise SpecError("range needs min and/or max")

        def build(ids):
            conds, params = [f"t.{col} IS NOT NULL"], {}
            if p.get("test_code"):
                conds.append("t.test_code = %(tc)s")
                params["tc"] = p["test_code"]
            if p.get("visit"):
                _col(table, "visit")
                conds.append("t.visit = %(visit)s")
                params["visit"] = p["visit"]
            bad = []
            if lo is not None:
                bad.append(f"t.{col} < %(lo)s")
                params["lo"] = lo
            if hi is not None:
                bad.append(f"t.{col} > %(hi)s")
                params["hi"] = hi
            frag, extra = _ids_clause(ids)
            exp = f"'between {lo if lo is not None else '-inf'} and {hi if hi is not None else 'inf'}'"
            pk = "t.usubjid" if table == "edc.subjects" else "t.id"
            sql = (SELECT.format(tbl=table, pk=pk, obs=f"t.{col}", exp=exp) + f" FROM {table} t WHERE "
                   + " AND ".join(conds) + " AND (" + " OR ".join(bad) + ")" + (frag if table != "edc.subjects" else ""))
            return sql, {**params, **(extra if table != "edc.subjects" else {})}
        return Compiled(spec.id, None if table == "edc.subjects" else table.split(".")[1], build)

    # ---- unit plausibility (lb entered as kg) -------------------------------------------------
    def _unit_plausibility(self, spec: EditCheckSpec) -> Compiled:
        """Reading is ratio_lo..ratio_hi times the median of the same subject's other readings (pounds entered as kg)."""
        p = spec.params
        table = _tbl(p["table"])
        _col(table, "value")

        def build(ids):
            frag, extra = _ids_clause(ids)
            sql = (SELECT.format(tbl=table, pk="t.id", obs="t.value", exp="'about ' || round(o.m::numeric, 1) || ' (other readings of this subject)'")
                   + f" FROM {table} t CROSS JOIN LATERAL (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY x.value) AS m FROM {table} x "
                   f"WHERE x.usubjid = t.usubjid AND x.test_code = t.test_code AND x.id <> t.id AND x.value IS NOT NULL) o "
                   f"WHERE t.test_code = %(tc)s AND t.value / o.m BETWEEN %(lo)s AND %(hi)s" + frag)
            return sql, {"tc": p["test_code"], "lo": p["ratio_lo"], "hi": p["ratio_hi"], **extra}
        return Compiled(spec.id, table.split(".")[1], build)

    # ---- date order ---------------------------------------------------------------------------
    def _date_order(self, spec: EditCheckSpec) -> Compiled:
        p = spec.params
        mode = p["mode"]
        if mode == "pair":
            table = _tbl(p["table"])
            a, b = _col(table, p["earlier_col"]), _col(table, p["later_col"])

            def build(ids):
                frag, extra = _ids_clause(ids)
                sql = (SELECT.format(tbl=table, pk="t.id", obs=f"t.{b}", exp=f"'on or after ' || t.{a}")
                       + f" FROM {table} t WHERE t.{a} IS NOT NULL AND t.{b} IS NOT NULL AND t.{b} < t.{a}" + frag)
                return sql, extra
            return Compiled(spec.id, table.split(".")[1], build)
        if mode == "sequence":
            table = _tbl(p["table"])
            _col(table, "planned_day"), _col(table, "actual_date")

            def build(ids):
                sql = (SELECT.format(tbl=table, pk="t.id", obs="t.actual_date", exp="'on or after ' || t.prev_d")
                       + f" FROM (SELECT v.*, lag(v.actual_date) OVER (PARTITION BY v.usubjid ORDER BY v.planned_day, v.actual_date) AS prev_d "
                       f"FROM {table} v WHERE v.planned_day IS NOT NULL AND v.visit = ANY(%(visits)s)) t "
                       f"WHERE t.actual_date < t.prev_d")
                return sql, {"visits": SCHEDULED_VISITS}
            return Compiled(spec.id, None, build)
        if mode == "ref":
            op = {"before": "<", "after": ">"}[p["op"]]
            ref_tbl, ref_col = "edc.subjects", _col("edc.subjects", p["ref_col"]) if p.get("ref_col") else None
            targets = [(_tbl(t["table"]), _col(t["table"], t["col"])) for t in p["targets"]]

            def build(ids):
                parts = []
                for table, col in targets:
                    d = _date(table, col)
                    if p.get("ref") == "sim_today":
                        parts.append(SELECT.format(tbl=table, pk="t.id", obs=d, exp="'on or before ' || (SELECT today FROM ops.sim_clock)")
                                     + f" FROM {table} t WHERE t.{col} IS NOT NULL AND {d} {op} (SELECT today FROM ops.sim_clock)")
                    else:
                        parts.append(SELECT.format(tbl=table, pk="t.id", obs=d, exp=f"'on or {'after' if op == '<' else 'before'} ' || s.{ref_col}")
                                     + f" FROM {table} t JOIN {ref_tbl} s USING (usubjid) WHERE t.{col} IS NOT NULL AND s.{ref_col} IS NOT NULL AND {d} {op} s.{ref_col}")
                return " UNION ALL ".join(parts), {}
            return Compiled(spec.id, None, build)
        raise SpecError(f"unknown date_order mode: {mode}")

    # ---- required fields ------------------------------------------------------------------------
    def _required_field(self, spec: EditCheckSpec) -> Compiled:
        p = spec.params
        table = _tbl(p["table"])
        rules = p["rules"]
        cols = sorted({_col(table, c) for r in rules for c in r["columns"]})

        def build(ids):
            params: dict = {}
            ors = []
            for i, r in enumerate(rules):
                conds = []
                for k, v in (r.get("equals") or {}).items():
                    _col(table, k)
                    conds.append(f"t.{k} = %(eq{i}_{k})s")
                    params[f"eq{i}_{k}"] = v
                if r.get("test_codes"):
                    conds.append(f"t.test_code = ANY(%(tc{i})s)")
                    params[f"tc{i}"] = r["test_codes"]
                if r.get("if_usually_present"):
                    # only require the field for tests where >= 90% of rows have it (unitless tests such as pH are exempt)
                    nulls = [f"(t.{_col(table, c)} IS NULL AND t.test_code IN (SELECT test_code FROM {table} GROUP BY test_code "
                             f"HAVING avg(({c} IS NOT NULL)::int) >= 0.9))" for c in r["columns"]]
                    conds.append("(" + " OR ".join(nulls) + ")")
                else:
                    conds.append("(" + " OR ".join(f"t.{_col(table, c)} IS NULL" for c in r["columns"]) + ")")
                ors.append("(" + " AND ".join(conds) + ")")
            missing = "concat_ws(',', " + ", ".join(f"CASE WHEN t.{c} IS NULL THEN '{c}' END" for c in cols) + ")"
            frag, extra = _ids_clause(ids)
            sql = (SELECT.format(tbl=table, pk="t.id", obs=f"'missing: ' || {missing}", exp="'value present'")
                   + f" FROM {table} t WHERE (" + " OR ".join(ors) + ")" + frag)
            return sql, {**params, **extra}
        return Compiled(spec.id, table.split(".")[1], build)

    # ---- visit window -----------------------------------------------------------------------------
    def _visit_window(self, spec: EditCheckSpec) -> Compiled:
        table = _tbl(spec.params["table"])
        names = [v for v, _ in SCHEDULE]

        def build(ids):
            frag, extra = _ids_clause(ids)
            sql = (SELECT.format(tbl=table, pk="t.id", obs="t.actual_date",
                                 exp="'within ' || %(w)s || ' days of ' || (b.actual_date + t.planned_day - 1)")
                   + f" FROM {table} t JOIN {table} b ON b.usubjid = t.usubjid AND b.visit = 'BASELINE' "
                   f"WHERE t.visit = ANY(%(visits)s) AND abs(t.actual_date - (b.actual_date + t.planned_day - 1)) > %(w)s" + frag)
            return sql, {"visits": names, "w": WINDOW, **extra}
        return Compiled(spec.id, "visits", build)

    # ---- missing visit (set based) -----------------------------------------------------------------
    def _missing_visit(self, spec: EditCheckSpec) -> Compiled:
        def build(ids):
            sql = (
                "WITH base AS (SELECT usubjid, site_id, min(actual_date) AS b FROM edc.visits WHERE visit = 'BASELINE' GROUP BY 1, 2), "
                "sched AS (SELECT * FROM unnest(%(names)s::text[], %(days)s::int[]) AS s(visit, planned_day)), "
                "lastv AS (SELECT usubjid, max(planned_day) AS last_pd FROM edc.visits "
                "          WHERE visit = ANY(%(names)s) GROUP BY 1) "
                "SELECT 'edc.visits', n.usubjid || '|' || n.visit, n.usubjid, n.site_id, 'no visit entered', "
                "       'visit due ' || (n.b + n.planned_day - 1)::text "
                "FROM (SELECT b.usubjid, b.site_id, b.b, s.visit, s.planned_day FROM base b CROSS JOIN sched s) n "
                "JOIN edc.subjects su USING (usubjid) LEFT JOIN lastv l USING (usubjid) "
                "WHERE NOT EXISTS (SELECT 1 FROM edc.visits v WHERE v.usubjid = n.usubjid AND v.visit = n.visit) "
                "  AND n.b + n.planned_day - 1 + %(w)s + %(g)s < (SELECT today FROM ops.sim_clock) "
                "  AND (n.planned_day < COALESCE(l.last_pd, -1) OR su.status = 'enrolled') "
                "  AND (su.discontinued_at IS NULL OR n.b + n.planned_day - 1 <= su.discontinued_at) "
                "  AND (su.death_at IS NULL OR n.b + n.planned_day - 1 <= su.death_at)")
            return sql, {"names": [v for v, _ in SCHEDULE], "days": [d for _, d in SCHEDULE],
                         "w": WINDOW, "g": ENTRY_GRACE_DAYS}
        return Compiled(spec.id, None, build)

    # ---- duplicates --------------------------------------------------------------------------------
    def _duplicate(self, spec: EditCheckSpec) -> Compiled:
        p = spec.params
        table = _tbl(p["table"])
        keys = [_col(table, c) for c in p["key_cols"]]

        def build(ids):
            frag, extra = _ids_clause(ids)
            sql = ("SELECT src_table, src_pk, usubjid, site_id, observed, expected FROM ("
                   + SELECT.format(tbl=table, pk="t.id", obs="'duplicate row'", exp=f"'unique ({', '.join(keys)})'")
                   + ", t.id AS rid, row_number() OVER (PARTITION BY " + ", ".join(f"t.{k}" for k in keys) + " ORDER BY t.id) AS rn "
                   f"FROM {table} t) t WHERE rn > 1" + (" AND rid = ANY(%(ids)s)" if ids is not None else ""))
            return sql, extra
        return Compiled(spec.id, table.split(".")[1], build)

    # ---- cross form ----------------------------------------------------------------------------------
    def _cross_form(self, spec: EditCheckSpec) -> Compiled:
        kind = spec.params["kind"]
        if kind == "hepatic_ae":
            def build(ids):
                sql = (SELECT.format(tbl="edc.lab", pk="t.id", obs="t.test_code || ' ' || round(t.x_uln::numeric, 1) || 'x ULN'",
                                     exp="'a hepatic adverse event within 14 days'")
                       + " FROM edc.lab t WHERE t.test_code IN ('ALT','AST') AND t.x_uln >= 3 AND NOT EXISTS ("
                       "SELECT 1 FROM edc.ae a WHERE a.usubjid = t.usubjid AND a.onset_at BETWEEN t.collected_at::date - 14 "
                       "AND t.collected_at::date + 14 AND a.term_coded ~* %(pat)s)")
                return sql, {"pat": "(HEPAT|LIVER|TRANSAMINASE|ALANINE|ASPARTATE|JAUNDICE|BILIRUBIN)"}
            return Compiled(spec.id, None, build)
        if kind == "dose_after_discontinuation":
            def build(ids):
                sql = (SELECT.format(tbl="edc.exposure", pk="t.id", obs="t.start_at", exp="'on or before ' || COALESCE(s.discontinued_at, s.death_at)")
                       + " FROM edc.exposure t JOIN edc.subjects s USING (usubjid) "
                       "WHERE t.start_at > COALESCE(s.discontinued_at, s.death_at)")
                return sql, {}
            return Compiled(spec.id, None, build)
        raise SpecError(f"unknown cross_form kind: {kind}")
