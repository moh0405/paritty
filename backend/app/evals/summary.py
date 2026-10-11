"""Natural-language evaluation report (spec §9.12): a plain-English summary of a run whose every claim cites the metric rows it reports."""
from __future__ import annotations

import json
from datetime import date

from psycopg import Connection

from app.domain.enums import Role
from app.llm import prompts
from app.llm.client import LLMClient, get_client
from app.llm.schemas import Citation, Claim, EvalSummary
from app.verification.checks import VerifyContext
from app.verification.store import save_finding
from app.verification.verifier import Verifier

# (module, metric, how to say it, higher_is_better)
HEADLINE = [("checks", "recall", "edit checks found {v} of the planted errors", True), ("checks", "precision", "and {v} of what they flagged was planted", True),
            ("sae_recon", "recall", "serious adverse event reconciliation found {v} of the planted discrepancies", True),
            ("sae_recon", "precision", "with precision {v}", True), ("medical", "hys_law_recall", "the potential Hy's Law patterns were found at a rate of {v}", True),
            ("sites", "rule_recall_at_k_plus_5", "the risk score placed {v} of the planted problem sites near the top", True),
            ("hub", "crosswalk_precision", "identifier matching was correct for {v} of the identifiers it mapped", True),
            ("protocol", "eligibility_accuracy", "the eligibility assistant answered {v} of the answerable questions correctly", True),
            ("lab_recon", "recall", "lab reconciliation found {v} of the planted differences", True),
            ("forecast", "abs_error_days", "the lock forecast was off by {v} days", False), ("system", "grounding_rate", "{v} of AI claims were verified against the data", True)]
WEAK = 0.7


class EvalSummarizer:
    def __init__(self, conn: Connection, client: LLMClient | None = None):
        self.conn = conn
        self.client = client if client is not None else get_client()

    def metrics(self, run_id: str) -> tuple[str, list[dict]]:
        row = self.conn.execute("SELECT scenario FROM eval.scenario_runs WHERE id = %s", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        rows = [{"ref": r[0], "module": r[1], "metric": r[2], "value": r[3]} for r in self.conn.execute(
            "SELECT ref, module, metric, value FROM eval.v_metrics WHERE scenario_run_id = %s ORDER BY module, metric", (run_id,))]
        return row[0], rows

    @staticmethod
    def template(metrics: list[dict]) -> tuple[str, list[Claim]]:
        by = {(m["module"], m["metric"]): m for m in metrics}
        claims, sentences, weak = [], [], []
        for module, metric, phrase, higher in HEADLINE:
            m = by.get((module, metric))
            if m is None:
                continue
            v = f"{m['value']:.2f}"
            text = phrase.format(v=v).capitalize() + "."
            claims.append(Claim(text=text, citations=[Citation(table="eval.v_metrics", pk=m["ref"], column="value", value=str(m["value"]))]))
            sentences.append(text)
            if (higher and m["value"] < WEAK) or (not higher and m["value"] > 30):
                weak.append((module, metric, v, m["ref"], m["value"]))
        if weak:
            text = "Needs attention: " + "; ".join(f"{mod} {met} is {v}" for mod, met, v, _r, _x in weak) + "."
            claims.append(Claim(text=text, citations=[Citation(table="eval.v_metrics", pk=r, column="value", value=str(x)) for _m, _e, _v, r, x in weak]))
            sentences.append(text)
        return " ".join(sentences) or "This run produced no headline metrics.", claims

    def summarize(self, run_id: str, day: date) -> dict:
        scenario, metrics = self.metrics(run_id)
        ctx = VerifyContext(self.conn, Role.STUDY_LEAD, evidence={("eval.v_metrics", m["ref"]) for m in metrics})
        text, claims, source = None, [], "template"
        try:
            version, prompt = prompts.render("eval_summary", scenario=scenario, metrics_json=json.dumps(metrics, default=str, indent=1))
            res = self.client.structured("eval_summary", prompt, EvalSummary, prompt_version=version, conn=self.conn)
            if res.parsed is not None:
                cand: EvalSummary = res.parsed
                allc = [*cand.claims, Claim(text=cand.text, citations=[c for cl in cand.claims for c in cl.citations])]
                gv = Verifier().verify(allc, ctx)
                save_finding(self.conn, module="eval_summary_draft", rule_id="eval_summary", severity="low", usubjid=None, site_id=None, title="Evaluation summary draft",
                             claims=allc, result=gv, sim_date=day, body_extra={"source": "gemini", "run": run_id})
                if gv.status == "verified":
                    text, claims, source = cand.text, allc, "gemini"
        except Exception as exc:
            print(f"warning: evaluation summary fell back to the template ({type(exc).__name__})")
        if text is None:
            text, claims = self.template(metrics)
        result = Verifier().verify(claims, ctx)
        fid = save_finding(self.conn, module="eval_summary", rule_id="eval_summary", severity="low", usubjid=None, site_id=None, title=f"Evaluation summary: {scenario}",
                           claims=claims, result=result, sim_date=day, body_extra={"source": source, "run": run_id, "summary": text})
        return {"run_id": run_id, "scenario": scenario, "text": text, "source": source, "verification_status": result.status, "finding_id": fid, "claims": len(claims)}
