export const ROLES = [
  "data_manager",
  "medical_monitor",
  "central_monitor",
  "study_lead",
  "unblinded_statistician",
] as const;
export type Role = (typeof ROLES)[number];

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

export async function api<T>(path: string, role: Role, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", "X-Role": role, "X-User": "demo_user", ...init.headers },
  });
  if (!res.ok) {
    let detail = await res.text();
    try {
      detail = (JSON.parse(detail) as { detail?: string }).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export type Clock = { today: string; study_start: string; study_day: number };
export type Job = { id: string; status: "running" | "done" | "failed"; done: number; total: number; error: string | null; result: unknown };
export type QueryRow = {
  id: string; priority: number; state: string; site_id: string; usubjid: string; text: string; opened_on: string;
  reopen_count: number; age_days: number; check_id: string; check_description: string; ctq_category: string;
  severity: string; approved_by: string | null; closed_reason: string | null; finding_id: string | null;
  verification_status: "verified" | "partial" | "blocked" | null; text_source: string | null;
};
export type Aging = { buckets: string[]; rows: Array<Record<string, number | string>> };
export type Stats = { by_state: Record<string, number>; daily: Array<{ day: string; opened: number; closed: number; reopened: number }> };

export type Citation = { id: number; claim_idx: number; table: string; pk: string; column: string; value: string; quote: string | null };
export type CheckResult = { claim_idx: number; name: string; passed: boolean; detail: string };
export type FindingClaim = { idx: number; text: string; status: string; citations: Citation[]; checks: CheckResult[] };
export type Finding = {
  id: string; module: string; rule_id: string; severity: string; usubjid: string | null; site_id: string | null; title: string;
  verification_status: "verified" | "partial" | "blocked"; review_status: string; reviewer_note: string | null; sim_date: string | null;
  claims: FindingClaim[];
  detail: { rule?: { rule: string; description: string; expected: string | null; observed: string | null; severity: string; ctq: string }; source?: string; model?: string; query_text?: string };
};
export type Source = { table: string; pk: string; column: string; cited_value: string; quote: string | null; row: Record<string, unknown>; cell: unknown; matches: boolean };

export type Discrepancy = { field: string; edc_value: string | null; safety_value: string | null; cls: "acceptable" | "actionable" | "critical"; reason: string };
export type SaePair = {
  ae_id: number; case_id: string; version: number; usubjid: string; site_id: string; overall: "clean" | "acceptable" | "actionable" | "critical";
  score: number; needs_causality: boolean; term_match: { method: string; score: number; reason: string };
  edc: { term: string; onset: string | null; serious: boolean; causality: string | null; outcome: string | null };
  safety: { term: string | null; onset: string | null; serious: boolean; causality: string | null; outcome: string | null; death: boolean; received: string | null };
  discrepancies: Discrepancy[]; open_items: Array<{ check_id: string; query_id: string | null; query_state: string | null }>;
};
export type OneSided = {
  kind: "edc_only" | "safety_only"; class: string; reason: string; pending: boolean;
  ae: { id: number; usubjid: string; site_id: string; term: string; onset: string | null; outcome: string | null; entered_at: string } | null;
  case: { case_id: string; version: number; usubjid: string | null; term: string | null; onset: string | null; outcome: string | null; site_id: string | null } | null;
};
export type SaeSummary = {
  today: string; counts: Record<string, number>; open_by_field: Record<string, number>;
  history: Array<{ day: string; open_discrepancies: number; critical: number; actionable: number }>; term_decisions: { total: number; same_event: number };
};
export type CaseVersions = { case_id: string; versions: Array<Record<string, unknown> & { version: number; changes?: Record<string, { from: unknown; to: unknown }> }> };
export type TermHit = { id: number; term: string; coded_term: string; source: string; rank: number; score: number };
export type TermSearch = { query: string; method: string; bm25: TermHit[]; vector: TermHit[]; fused: TermHit[] };

export type ReviewItem = {
  type: string; score: number; title: string; day: string; usubjid: string | null; site_id: string | null;
  finding_id: string | null; review_status: string | null; rule: { rule: string; threshold: string; comparison_group: string; value: unknown };
};
export type LabRow = { id: number; test_code: string; day: string; value: number; unit: string | null; uln: number | null; x_uln: number | null; ctcae_grade: number | null; visit: string };
export type Profile = {
  subject: { usubjid: string; site_id: string; age: number; sex: string; consent_at: string; first_dose_at: string | null; discontinued_at: string | null; death_at: string | null; status: string };
  dosing: Array<{ id: number; start_at: string; end_at: string | null }>;
  visits: Array<{ id: number; visit: string; planned_day: number | null; actual_date: string }>;
  adverse_events: Array<{ id: number; term_coded: string; onset_at: string; end_at: string | null; serious: boolean; severity: string | null; ctcae_grade: number | null; outcome: string | null }>;
  conmeds: Array<{ id: number; term: string; start_at: string; end_at: string | null }>;
  labs: Record<string, LabRow[]>;
  flags: Array<{ type: string; title: string; day: string }>;
  links: Array<{ lab_id: number; test: string; ae_id: number; ae_term: string; days_apart: number }>;
};
export type EdishPoint = { usubjid: string; site_id: string; peak_alt: number | null; peak_ast: number | null; peak_amino: number; peak_bili: number; quadrant: string; arm?: string | null };

export type KriCell = { value: number | null; comparator: number | null; rag: "red" | "amber" | "green" | "na" };
export type SiteRow = { site_id: string; name: string | null; subjects: number; rule_score: number; model_score: number | null; kris: Record<string, KriCell> };
export type SitesList = { as_of: string | null; kri_defs: Record<string, { label: string; rule: string }>; sites: SiteRow[] };
export type SiteDetail = {
  site_id: string; name: string | null; subjects: number | null; as_of: string; rule_score: number; model_score: number | null;
  kris: Record<string, KriCell>; kri_defs: Record<string, { label: string; rule: string; unit: string }>;
  explanations: Array<{ kind: string; name: string; level: string; text: string }>;
  anomalies: Array<{ test: string; flagged: boolean; p: number | null; statistic: number; detail: Record<string, unknown> }>;
  history: Array<{ day: string; rule_score: number }>;
  open_queries: Record<string, number | string> | null;
};

export type EvalRun = {
  id: string; scenario: string; seed: number; model: string; prompt_version: string; status: string; started_at: string; finished_at: string | null;
  fork_seconds: number | null; headline: Record<string, number>;
};
export type EvalDetail = EvalRun & { planted: Record<string, number>; metrics: Record<string, Array<{ metric: string; value: number; detail: Record<string, unknown> }>> };
export type EvalCompare = { runs: string[]; metrics: Record<string, Record<string, number>> };
