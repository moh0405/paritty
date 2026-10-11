"""Database-backed medical review: signals, ranked review list, patient profile, eDISH, rule findings (spec §9.6)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from psycopg import Connection

from app.medical.signals import (AeLabLink, ClusterResult, CreepResult, HysResult, LabPoint, ReviewItem, ae_lab_links, edish_row, hys_law,
                                 rank, rare_ae_clusters, site_creep, subject_slope)
from app.verification.builders import ClaimSpec, rule_finding

LIVER_TESTS = ("ALT", "AST", "BILI", "ALP")
GRADED_ALERT_TESTS = ("ALT", "AST", "ALP", "BILI", "CREAT", "HGB", "PLAT")
LAB_FMT = "{test_code} was {x_uln:.2f}x ULN on {collected_at:.10}."


class MedicalService:
    def __init__(self, conn: Connection):
        self.conn = conn
        self._labs: dict[str, list[LabPoint]] | None = None
        self.site_of: dict[str, str] = {}

    # ---- data ------------------------------------------------------------------------------------
    def labs(self) -> dict[str, list[LabPoint]]:
        if self._labs is None:
            self._labs = defaultdict(list)
            for i, u, site, test, day, x, g in self.conn.execute(
                    "SELECT id, usubjid, site_id, test_code, collected_at::date, x_uln, ctcae_grade FROM edc.lab "
                    "WHERE x_uln IS NOT NULL AND test_code = ANY(%s) ORDER BY collected_at", (list(GRADED_ALERT_TESTS),)):
                self._labs[u].append(LabPoint(i, test, day, float(x), g))
                self.site_of[u] = site
        return self._labs

    # ---- signals ---------------------------------------------------------------------------------
    def hys_cases(self) -> list[HysResult]:
        return [r for u, pts in self.labs().items() if (r := hys_law(u, [p for p in pts if p.test in LIVER_TESTS]))]

    def edish(self) -> list[dict]:
        rows = []
        for u, pts in self.labs().items():
            r = edish_row(u, self.site_of[u], [p for p in pts if p.test in LIVER_TESTS])
            if r:
                rows.append(r)
        return rows

    def creep(self) -> list[CreepResult]:
        by_site: dict[str, list[float]] = defaultdict(list)
        for u, pts in self.labs().items():
            alt = [p for p in pts if p.test == "ALT"]
            if len(alt) >= 4:
                d0 = alt[0].day
                s = subject_slope([(p.day - d0).days for p in alt], [p.x_uln for p in alt])
                if s is not None:
                    by_site[self.site_of[u]].append(s)
        return site_creep(by_site)

    def clusters(self) -> list[ClusterResult]:
        subjects = dict(self.conn.execute("SELECT site_id, count(*) FROM edc.subjects GROUP BY 1").fetchall())
        counts = {(s, t): n for s, t, n in self.conn.execute("SELECT site_id, term_coded, count(DISTINCT usubjid) FROM edc.ae GROUP BY 1, 2")}
        return rare_ae_clusters(counts, subjects)

    def links(self) -> list[AeLabLink]:
        aes: dict[str, list] = defaultdict(list)
        for i, u, term, onset in self.conn.execute("SELECT id, usubjid, term_coded, onset_at FROM edc.ae WHERE onset_at IS NOT NULL"):
            aes[u].append((i, term, onset))
        out = []
        for u, pts in self.labs().items():
            if aes.get(u):
                out += ae_lab_links(u, pts, aes[u])
        return out

    # ---- ranked review list --------------------------------------------------------------------------
    def review_items(self, today: date) -> list[ReviewItem]:
        items: list[ReviewItem] = []
        for h in self.hys_cases():
            a, b = h.aminotransferase, h.bilirubin
            items.append(ReviewItem("hys_law", 0, f"{h.wording}: {a.test} {a.x_uln:.1f}x ULN with bilirubin {b.x_uln:.1f}x ULN", max(a.day, b.day),
                                    usubjid=h.usubjid, site_id=self.site_of[h.usubjid], finding_key=f"hys:{h.usubjid}",
                                    detail={"alt_ast_lab": a.id, "bili_lab": b.id, "alp_x_uln": h.alp_x_uln, "days_apart": h.days_apart,
                                            "claims": [ClaimSpec("edc.lab", str(a.id), ["test_code", "x_uln", "collected_at"], LAB_FMT),
                                                       ClaimSpec("edc.lab", str(b.id), ["test_code", "x_uln", "collected_at"], LAB_FMT)],
                                            "rule": {"rule": "hys_law", "threshold": "ALT or AST >= 3x ULN and total bilirubin >= 2x ULN within 30 days",
                                                     "comparison_group": "ULN", "value": f"{a.x_uln:.2f} / {b.x_uln:.2f}"}}))
        graded: dict[tuple[str, str], LabPoint] = {}
        for u, pts in self.labs().items():
            for p in pts:
                if (p.grade or 0) >= 3 and ((u, p.test) not in graded or (p.grade or 0) >= (graded[(u, p.test)].grade or 0)):
                    graded[(u, p.test)] = p
        for (u, test), p in graded.items():
            t = "lab_grade4" if (p.grade or 0) >= 4 else "lab_grade3"
            items.append(ReviewItem(t, 0, f"{test} grade {p.grade} ({p.x_uln:.1f}x ULN)", p.day, usubjid=u, site_id=self.site_of[u], finding_key=f"grade:{u}:{test}",
                                    detail={"lab": p.id, "claims": [ClaimSpec("edc.lab", str(p.id), ["test_code", "x_uln", "ctcae_grade", "collected_at"],
                                                                              LAB_FMT.replace("ULN on", "ULN (CTCAE grade {ctcae_grade}) on"))],
                                            "rule": {"rule": "ctcae_grade", "threshold": "CTCAE grade >= 3", "comparison_group": "reference range", "value": p.grade}}))
        for c in self.creep():
            subs = [(u, [p for p in pts if p.test == "ALT"][-1]) for u, pts in self.labs().items()
                    if self.site_of[u] == c.site_id and any(p.test == "ALT" for p in pts)]
            subs = sorted(subs, key=lambda x: -x[1].x_uln)[:3]
            items.append(ReviewItem("site_creep", 0, f"Site {c.site_id}: ALT rising across subjects (robust z {c.z:.1f})", max(p.day for _, p in subs),
                                    site_id=c.site_id, finding_key=f"creep:{c.site_id}",
                                    detail={"claims": [ClaimSpec("edc.lab", str(p.id), ["test_code", "x_uln", "collected_at"], LAB_FMT) for _, p in subs],
                                            "rule": {"rule": "site_alt_creep", "threshold": "robust z of site median ALT slope > 3", "comparison_group": "other sites",
                                                     "value": f"z={c.z:.2f}, median slope {c.median_slope:.5f}/day, {c.n_subjects} subjects"}}))
        for c in self.clusters():
            rows = self.conn.execute("SELECT id, onset_at FROM edc.ae WHERE site_id = %s AND term_coded = %s ORDER BY onset_at", (c.site_id, c.term)).fetchall()
            items.append(ReviewItem("ae_cluster", 0, f"Site {c.site_id}: {c.count} subjects with {c.term.lower()} (expected {c.expected:.2f})", rows[-1][1],
                                    site_id=c.site_id, finding_key=f"cluster:{c.site_id}:{c.term}",
                                    detail={"claims": [ClaimSpec("edc.ae", str(i), ["term_coded", "onset_at"], "Adverse event {term_coded} with onset {onset_at}.") for i, _ in rows[:4]],
                                            "rule": {"rule": "rare_ae_cluster", "threshold": "p < 0.001 and >= 3 subjects; study rate elsewhere < 1%",
                                                     "comparison_group": "other sites", "value": f"p={c.p_value:.2e}"}}))
        for l in self.links():
            items.append(ReviewItem("ae_lab_link", 0, f"{l.ae_term.lower()} {abs(l.days_apart)} days {'after' if l.days_apart >= 0 else 'before'} {l.lab.test} grade {l.lab.grade}",
                                    max(l.lab.day, l.ae_onset), usubjid=l.usubjid, site_id=self.site_of.get(l.usubjid), finding_key=f"link:{l.lab.id}:{l.ae_id}",
                                    detail={"claims": [ClaimSpec("edc.lab", str(l.lab.id), ["test_code", "x_uln", "ctcae_grade", "collected_at"],
                                                                 LAB_FMT.replace("ULN on", "ULN (CTCAE grade {ctcae_grade}) on")),
                                                       ClaimSpec("edc.ae", str(l.ae_id), ["term_coded", "onset_at"], "Adverse event {term_coded} with onset {onset_at}.")],
                                            "rule": {"rule": "ae_lab_link", "threshold": "AE onset within 7 days of a lab grade increase", "comparison_group": "same subject",
                                                     "value": f"{l.days_apart} days"}}))
        return rank(items, today)

    def persist_findings(self, items: list[ReviewItem], day: date) -> dict[str, str]:
        """Create one verified finding per review item (idempotent). Returns finding_key -> finding id."""
        out = {}
        for it in items:
            fid = rule_finding(self.conn, module="medical", rule_id=it.detail["rule"]["rule"], severity="critical" if it.type == "hys_law" else "high" if it.score >= 60 else "medium",
                               usubjid=it.usubjid, site_id=it.site_id, title=it.title, claims=it.detail["claims"], rule=it.detail["rule"], day=day,
                               key=it.finding_key, rule_numbers={3.0, 2.0, 30.0, 7.0, 1.0, 0.001})
            if fid:
                out[it.finding_key] = fid
        return out

    def run(self, day: date) -> int:
        items = self.review_items(day)
        return len(self.persist_findings(items, day))

    # ---- patient profile ---------------------------------------------------------------------------------
    def profile(self, usubjid: str) -> dict | None:
        c = self.conn
        subj = c.execute("SELECT usubjid, site_id, age, sex, consent_at, first_dose_at, discontinued_at, death_at, status FROM edc.subjects WHERE usubjid = %s", (usubjid,)).fetchone()
        if subj is None:
            return None
        rows = lambda q: [dict(zip([d.name for d in cur.description], r)) for cur in [c.execute(q, (usubjid,))] for r in cur.fetchall()]  # noqa: E731
        labs: dict[str, list[dict]] = defaultdict(list)
        for r in rows("SELECT id, test_code, collected_at::date AS day, value, unit, uln, x_uln, ctcae_grade, visit FROM edc.lab WHERE usubjid = %s "
                      "AND test_code IN ('ALT','AST','ALP','BILI','CREAT','HGB','PLAT','GLUC','WBC') ORDER BY collected_at"):
            labs[r["test_code"]].append(r)
        today_items = [i for i in self.review_items(date.max) if i.usubjid == usubjid]
        return {
            "subject": dict(zip(("usubjid", "site_id", "age", "sex", "consent_at", "first_dose_at", "discontinued_at", "death_at", "status"), subj)),
            "dosing": rows("SELECT id, dose, start_at, end_at FROM edc.exposure WHERE usubjid = %s ORDER BY start_at"),
            "visits": rows("SELECT id, visit, planned_day, actual_date FROM edc.visits WHERE usubjid = %s ORDER BY actual_date"),
            "adverse_events": rows("SELECT id, term_coded, onset_at, end_at, serious, severity, ctcae_grade, causality, outcome FROM edc.ae WHERE usubjid = %s ORDER BY onset_at"),
            "conmeds": rows("SELECT id, term, start_at, end_at FROM edc.conmeds WHERE usubjid = %s ORDER BY start_at"),
            "labs": labs,
            "flags": [{"type": i.type, "title": i.title, "day": i.event_day} for i in today_items],
            "links": [{"lab_id": l.lab.id, "test": l.lab.test, "ae_id": l.ae_id, "ae_term": l.ae_term, "days_apart": l.days_apart} for l in self.links() if l.usubjid == usubjid],
        }
