"""CrosswalkBuilder (spec §9.9): normalize -> exact -> rapidfuzz (>= 92 proposed, 80-92 Gemini adjudication, < 80 unmatched for a person).
Every mapping starts as `proposed` and becomes `confirmed` only when a person confirms it."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from psycopg import Connection
from rapidfuzz import fuzz

from app.hub.adapters import ADAPTERS, FeedAdapter
from app.hub.normalize import norm_site_name, parse_site_code
from app.llm import prompts
from app.llm.client import LLMClient, get_client
from app.llm.schemas import XwalkDecision

AUTO, REVIEW = 92.0, 80.0
MARGIN = 3.0                 # the best candidate must beat the runner-up by this much to be accepted without a person


@dataclass
class Resolution:
    canonical: str | None
    confidence: float
    method: str
    status: str = "proposed"     # proposed | unmatched
    note: str = ""


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


class CrosswalkBuilder:
    def __init__(self, conn: Connection, client: LLMClient | None = None, allow_llm: bool = False):
        self.conn, self.client, self.allow_llm = conn, client if client is not None else get_client(), allow_llm
        self.subjects: dict[str, list[str]] = {}
        self.sites: dict[str, str] = {}

    def load_edc(self) -> None:
        self.subjects = {}
        for u, s in self.conn.execute("SELECT usubjid, site_id FROM edc.subjects"):
            self.subjects.setdefault(s, []).append(u)
        self.sites = {s: n for s, n in self.conn.execute("SELECT site_id, name FROM edc.sites")}

    # ---- adjudication ------------------------------------------------------------------------------------
    def _adjudicate(self, entity: str, system: str, source_id: str, cands: list[tuple[str, float]]) -> tuple[str | None, float, str]:
        if not (self.allow_llm and self.client):
            return None, 0.0, "needs review: no adjudication available"
        version, prompt = prompts.render("xwalk_decision", entity=entity, system=system, source_id=source_id,
                                         candidates="\n".join(f"- {c} ({s:.0f})" for c, s in cands))
        try:
            res = self.client.structured("xwalk_decision", prompt, XwalkDecision, prompt_version=version, conn=self.conn)
        except Exception as exc:
            return None, 0.0, f"adjudicator unavailable ({type(exc).__name__})"
        if res.parsed is None:
            return None, 0.0, "no cached adjudication (replay miss)"
        d: XwalkDecision = res.parsed
        ids = {c for c, _ in cands}
        return (d.chosen if d.chosen in ids else None), min(1.0, max(0.0, d.confidence)), d.reason

    # ---- subjects ----------------------------------------------------------------------------------------
    def resolve_subject(self, adapter: FeedAdapter, source_id: str) -> Resolution:
        key = adapter.parse(source_id)
        if key and key.site in self.subjects:
            pool = self.subjects[key.site]
            if adapter.full_number:
                if key.usubjid in pool:
                    return Resolution(key.usubjid, 0.97 if key.repaired else 1.0, "repaired" if key.repaired else "normalized")
            else:
                tail = int(key.number) if key.number.isdigit() else None
                cands = [u for u in pool if tail is not None and int(u.split("-")[2]) % 1000 == tail % 1000 and (len(key.number) < 4 or u.endswith(key.number))]
                if len(cands) == 1:
                    return Resolution(cands[0], 0.98, "normalized")
                if len(cands) > 1:
                    return self._pick(adapter, source_id, [(c, 100.0) for c in cands], "ambiguous")
        # fuzzy: compare the digits of the identifier with the digits of every subject (site + number)
        want = _digits(source_id)
        if not want:
            return Resolution(None, 0.0, "unparsed", "unmatched", "no digits to compare")
        scored = []
        for site, pool in self.subjects.items():
            for u in pool:
                num = u.split("-")[2]
                have = site + (num if adapter.full_number else f"{int(num) % 1000:03d}")
                scored.append((u, fuzz.ratio(want, have)))
        scored.sort(key=lambda x: -x[1])
        return self._pick(adapter, source_id, scored[:3], "fuzzy")

    def _pick(self, adapter: FeedAdapter, source_id: str, ranked: list[tuple[str, float]], method: str, entity: str = "subject") -> Resolution:
        if not ranked:
            return Resolution(None, 0.0, method, "unmatched", "no candidates")
        best, second = ranked[0][1], (ranked[1][1] if len(ranked) > 1 else 0.0)
        if method == "fuzzy" and best >= AUTO and best - second >= MARGIN:
            return Resolution(ranked[0][0], best / 100, "fuzzy")
        if best >= REVIEW:
            chosen, conf, why = self._adjudicate(entity, adapter.system, source_id, ranked)
            if chosen:
                return Resolution(chosen, conf, "adjudicated", note=why)
            return Resolution(None, best / 100, method, "unmatched", f"candidates {', '.join(c for c, _ in ranked)}; {why}")
        return Resolution(None, best / 100, method, "unmatched", "no close candidate")

    # ---- sites -------------------------------------------------------------------------------------------
    def resolve_site(self, code: str, name: str | None) -> Resolution:
        parsed = parse_site_code(code)
        if parsed and parsed[0] in self.sites:
            site, suffix = parsed
            return Resolution(site, 0.9 if suffix else 1.0, "duplicate_record" if suffix else "normalized",
                              note="this CTMS record duplicates another record for the same site" if suffix else "")
        want = norm_site_name(name)
        ranked = sorted(((s, fuzz.ratio(want, norm_site_name(n))) for s, n in self.sites.items()), key=lambda x: -x[1])[:3]
        a = ADAPTERS["ctms"]
        r = self._pick(a, code, ranked, "fuzzy", entity="site")
        return r

    # ---- build ---------------------------------------------------------------------------------------------
    def build(self, day: date) -> dict[str, int]:
        """Map every identifier the feeds have shown so far that has no mapping yet (and retry the unmatched ones)."""
        self.load_edc()
        names = dict(self.conn.execute("SELECT site_code, site_name FROM ctms.sites"))
        stats = {"new": 0, "unmatched": 0}
        for system, adapter in ADAPTERS.items():
            table = "hub.site_xwalk" if adapter.entity == "site" else "hub.subject_xwalk"
            col = "canonical_site" if adapter.entity == "site" else "canonical_subject"
            have = dict(self.conn.execute(f"SELECT source_id, status FROM {table} WHERE system = %s", (system,)).fetchall())
            for sid in adapter.source_ids(self.conn, day):
                if have.get(sid) not in (None, "unmatched"):
                    continue
                r = self.resolve_site(sid, names.get(sid)) if adapter.entity == "site" else self.resolve_subject(adapter, sid)
                self.conn.execute(
                    f"INSERT INTO {table} ({col}, system, source_id, confidence, method, status) VALUES (%s,%s,%s,%s,%s,%s) "
                    f"ON CONFLICT (system, source_id) DO UPDATE SET {col} = EXCLUDED.{col}, confidence = EXCLUDED.confidence, method = EXCLUDED.method, "
                    f"status = EXCLUDED.status WHERE {table}.status = 'unmatched'",
                    (r.canonical, system, sid, round(r.confidence, 3), r.method + (f": {r.note}" if r.note and r.status == "unmatched" else ""), r.status))
                stats["unmatched" if r.status == "unmatched" else "new"] += 1
        return stats


class SubjectMap:
    """Read side of the crosswalk for the reconcilers: confirmed or proposed mappings count, rejected ones do not.
    An identifier with no row yet falls back to strict parsing (so a feed is usable before the crosswalk has run)."""

    def __init__(self, conn: Connection):
        self.conn = conn
        self.by_source: dict[tuple[str, str], str] = {}
        self.rejected: set[tuple[str, str]] = set()
        self.known: set[tuple[str, str]] = set()
        for system, sid, canon, status in conn.execute("SELECT system, source_id, canonical_subject, status FROM hub.subject_xwalk"):
            self.known.add((system, sid))
            if status == "rejected":
                self.rejected.add((system, sid))
            elif canon:
                self.by_source[(system, sid)] = canon
        self._reverse: dict[tuple[str, str], list[str]] | None = None

    def get(self, system: str, source_id: str | None) -> str | None:
        if source_id is None or (system, source_id) in self.rejected:
            return None
        if (system, source_id) in self.by_source:
            return self.by_source[(system, source_id)]
        if (system, source_id) in self.known:           # seen and left unmatched: do not guess
            return None
        a = ADAPTERS.get(system)
        k = a.parse(source_id) if a and a.full_number else None
        return k.usubjid if k else None

    def sources_for(self, system: str, usubjid: str) -> list[str]:
        if self._reverse is None:
            self._reverse = {}
            for (sys_, sid), canon in self.by_source.items():
                self._reverse.setdefault((sys_, canon), []).append(sid)
        found = self._reverse.get((system, usubjid), [])
        if found or system != "irt":
            return found
        _, site, num = usubjid.split("-")
        return [f"R-{site}-{int(num) % 1000:03d}", f"R-{site}-{num}"]
