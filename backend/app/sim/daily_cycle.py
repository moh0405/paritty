"""One simulated day (spec §9.1). Steps 4-7 (reconcile, signals, forecast, agent) arrive in later milestones."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from psycopg import Connection

from app.audit.logger import audit
from app.checks.runner import CheckRunner, sync_library
from app.queries import lifecycle as lc
from app.queries.digest import MINOR_PRIORITY, MinorIssueDigest
from app.queries.drafting import draft_new_queries
from app.sites import risk as site_risk
from app.queries.prioritizer import reprioritize_open
from app.forecast.service import ForecastService
from app.medical.service import MedicalService
from app.recon.labs import LabReconciler
from app.recon.sae.reconciler import SaeReconciler
from app.sim.clock import TrialClock
from app.sim.ingestor import ChangeSet, release_through
from app.sim.site_responder import SiteResponder
from app.sim.world import WorldModel

AUTO = "sim:auto"


@dataclass
class DayReport:
    day: date
    released: dict = field(default_factory=dict)
    new_failures: int = 0
    opened: int = 0
    approved: int = 0
    sent: int = 0
    answered: int = 0
    closed: int = 0
    reopened: int = 0
    explained: int = 0
    sae_open: int = 0
    medical_findings: int = 0
    p50: str = ""

    def as_dict(self) -> dict:
        return {k: (str(v) if isinstance(v, date) else v) for k, v in self.__dict__.items()}


class DailyCycle:
    def __init__(self, conn: Connection, world: WorldModel | None = None):
        self.conn = conn
        self.clock = TrialClock(conn)
        self.world = world or WorldModel()
        seed = conn.execute("SELECT value FROM ops.sim_state WHERE key = 'sim_seed'").fetchone()
        from app.config import get_settings
        self.responder = SiteResponder(conn, self.world, int(seed[0]) if seed else get_settings().seed)
        self.runner = CheckRunner(conn)

    def first_run(self) -> bool:
        return self.conn.execute("SELECT NOT EXISTS (SELECT 1 FROM ops.sim_state WHERE key = 'checks_initialized')").fetchone()[0]

    def first_site_risk(self, day: date) -> bool:
        return not self.conn.execute("SELECT EXISTS (SELECT 1 FROM ops.site_risk)").fetchone()[0]

    def run(self, auto_approve: bool = True) -> DayReport:
        c = self.conn
        sync_library(c)
        day = self.clock.advance_one()
        rep = DayReport(day)
        # 1. ingest + deliver due site responses
        rep.released, changes = release_through(c, day)
        if self.first_run():
            changes.full = True
            c.execute("INSERT INTO ops.sim_state (key, value) VALUES ('checks_initialized', 'true'::jsonb)")
        delivered = self.responder.deliver(day, changes)
        for qid, kind in delivered:
            lc.transition(lc.Ctx(c, qid, day, "site"), "answer", {"closed_reason": None})
            rep.answered += 1
        # 2. checks
        rep.new_failures = sum(self.runner.run_all(changes, day).values())
        # 4. reconcile serious AEs between EDC and the safety database (lab reconciliation joins in milestone 10)
        sae = SaeReconciler(c).run(day)
        rep.new_failures += sae["new_failures"]
        rep.sae_open = sae["open_discrepancies"]
        lab = LabReconciler(c).run(day, changes.touched("lab"), full=changes.full)
        rep.new_failures += lab["new_failures"]
        # 5. medical signals (the review list itself is computed on demand; this keeps verified findings in step)
        rep.medical_findings = MedicalService(c).run(day)
        # 5b. site risk: KRIs, anomaly tests and scores, weekly (and on the first day) to keep a 330-day run fast
        if day.weekday() == 0 or self.first_site_risk(day):
            site_risk.store(c, day, site_risk.compute_all(c, day))
        # 3. queries
        self._evaluate_answers(day, delivered, auto_approve, rep)
        self._auto_close_resolved(day, rep)
        rep.opened = len(draft_new_queries(c, day))
        digest = MinorIssueDigest(c)
        if day.weekday() == 0:
            digest.build_weekly(day)
        if auto_approve:
            for (qid,) in c.execute("SELECT id FROM ops.queries WHERE state = 'Draft' AND priority >= %s ORDER BY failure_id", (MINOR_PRIORITY,)).fetchall():
                lc.transition(lc.Ctx(c, str(qid), day, AUTO), "approve")
                rep.approved += 1
            for (did,) in c.execute("SELECT id FROM ops.digests WHERE state = 'Draft' ORDER BY week_of, site_id").fetchall():
                rep.approved += digest.approve(str(did), AUTO, day)       # minor issues go out together, once a week
        self._send_approved(day, rep)
        reprioritize_open(c, day)
        # 6. lock forecast
        rep.p50 = str(ForecastService(c).run_and_store(day)["p50"])
        audit(c, day, "system", "sim.day", "sim_clock", str(day), rep.as_dict())
        return rep

    def _evaluate_answers(self, day: date, delivered, auto: bool, rep: DayReport) -> None:
        c = self.conn
        kinds = dict(delivered)
        for qid in kinds:
            resolved = c.execute("SELECT f.resolved_on IS NOT NULL FROM ops.queries q JOIN ops.check_failures f ON f.id = q.failure_id "
                                 "WHERE q.id = %s", (qid,)).fetchone()[0]
            ctx = lc.Ctx(c, qid, day, AUTO if auto else "system", {"response": kinds[qid]})
            if resolved:
                lc.transition(ctx, "close", {"closed_reason": "resolved: check passes after site response"})
                rep.closed += 1
            elif kinds[qid] == "explain":
                if auto:   # simulated data manager accepts the explanation
                    lc.transition(ctx, "close_with_explanation", {"closed_reason": "site explanation accepted"})
                    rep.explained += 1
            else:
                lc.transition(ctx, "reopen")
                rep.reopened += 1

    def _auto_close_resolved(self, day: date, rep: DayReport) -> None:
        """Open queries whose source row no longer fails (changed by anyone) close automatically."""
        c = self.conn
        rows = c.execute("SELECT q.id FROM ops.queries q JOIN ops.check_failures f ON f.id = q.failure_id "
                         "WHERE q.state IN ('Draft','Approved','Sent','Answered') AND f.resolved_on IS NOT NULL").fetchall()
        for (qid,) in rows:
            lc.transition(lc.Ctx(c, str(qid), day, "system", {"auto": True}), "close", {"closed_reason": "auto: source row corrected"})
            rep.closed += 1

    def _send_approved(self, day: date, rep: DayReport) -> None:
        c = self.conn
        for qid, site, check_id, state, tbl, pk, reopens in c.execute(
                "SELECT q.id, q.site_id, f.check_id, q.state, f.src_table, f.src_pk, q.reopen_count FROM ops.queries q "
                "JOIN ops.check_failures f ON f.id = q.failure_id WHERE q.state IN ('Approved','Reopened') ORDER BY f.id").fetchall():
            lc.transition(lc.Ctx(c, str(qid), day, "system", {"resend": state == "Reopened"}), "send")
            self.responder.schedule(str(qid), site, check_id, day, self.responder.key(check_id, tbl, pk, reopens))
            rep.sent += 1
