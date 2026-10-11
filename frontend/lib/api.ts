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

export type Criterion = { key: string; label: string; remaining: number; met: boolean; detail: string };
export type Blocker = { type: "site" | "category"; id: string; delta_p50_days: number; items: number };
export type LockForecast = {
  sim_date: string; p10: string; p50: string; p90: string; n_sims: number; blockers: Blocker[];
  readiness: { criteria: Criterion[]; met: number; total: number; benchmark: { lplv: string; days_lplv_to_p50: number; tufts_days: number };
    enrollment: { enrolled: number; planned: number; remaining: number; rate_per_day: number } | null; items: Record<string, number> };
};
export type ForecastPoint = { day: string; p10: string; p50: string; p90: string; met: string };

export type CheckRow = {
  id: string; type: string; description: string; ctq_category: string; severity: string; source: string; approval_status: string; active: boolean;
  rationale: { quote?: string; chunk_id?: number; dry_run_count?: number; dry_run_sample?: string[]; proposed_by?: string; rejected_reason?: string } | null;
  approved_by: string | null; failures: number; open_failures: number;
};
export type GeneratedCheck = { id: string; status: string; reason: string; description: string; quote: string; chunk_id: number | null; dry_run_count: number | null; sample: string[]; source: string };
export type Effectiveness = { check_id: string; description: string; source: string; approval_status: string; failures: number; open: number; confirmed: number; dismissed: number; dismissed_rate: number | null; recommend_retire: boolean };
export type Digest = { id: string; site_id: string; week_of: string; queries: number; text: string; state: string };
export type LabRecon = {
  today: string; feed: { last_file: string | null; days_since: number | null; stale: boolean }; open_by_type: { value: number; one_sided: number; unit: number };
  items: Array<{ id: number; check_id: string; usubjid: string | null; site_id: string | null; observed: string; expected: string; detected_on: string; resolved_on: string | null; query_state: string | null }>;
};

export type CatalogRow = { table_name: string; description: string; owner: string; refresh: string; sensitivity: string; row_count: number; age_days: number | null };
export type XwalkRow = { system: string; source_id: string; canonical: string | null; confidence: number; method: string; status: string; confirmed_by: string | null };
export type DqRule = { rule: string; table: string; dimension: string; failed_rows: number; sample_pks: string[]; description: string; sim_date: string };
export type DqPayload = { dimensions: string[]; rules: DqRule[]; freshness: Array<{ table: string; age_days: number; refresh: string }> };
export type QuestionResult = {
  id: number; title: string; level: string; columns: string[]; rows: Array<Record<string, unknown>>; note: string; role: string; site_scope: string | null;
  lineage: { sql: string; tables: string[]; row_refs: Array<{ table: string; pk: string }> };
};

export type QAResult = {
  question: string; answer: string; quotes: Array<{ chunk_id: number; section: string; text: string }>; escalate: boolean; confidence: number;
  reason: string; source: string; draft_id: string;
};
export type Trend = { test: string; by: string; unit: string; series: Array<{ key: string; points: Array<{ visit: string; planned_day: number; n: number; mean: number; p90: number }> }> };
export type Draft = {
  id: string; kind: string; subject_ref: string | null; site_id: string | null; state: string; approved_by: string | null; approved_at: string | null; created_at: string;
  body: { text?: string; source?: string; finding_id?: string; verification_status?: string; items?: string[] };
};
export type Escalation = { id: string; usubjid: string | null; finding_id: string | null; reason: string; raised_by: string; raised_at: string; status: string; resolution: string | null };
export type Clusters = {
  ae_clusters: Array<{ site_id: string; term: string; count: number; expected: number; p_value: number }>;
  alt_creep: Array<{ site_id: string; median_slope: number; z: number; n_subjects: number }>;
};

export type CausalityResult = {
  id: string; case_id: string; usubjid: string; category: string; confidence: number; escalate: boolean; why: string[]; alternative_causes: string[];
  verification_status: "verified" | "partial" | "blocked"; finding_id: string | null; source: string;
};
export type InboxRow = { id: number; received_at: string; status: string; source_ae_id: number | null; safetyreportid: string | null; version: number; subject_ref: string; term: string | null; errors: string[] | null };

export type WhatIfResult = {
  description: string; baseline: { p10: string; p50: string; p90: string }; what_if: { p10: string; p50: string; p90: string };
  delta_p50_days: number; delta_p90_days: number; n_sims: number; blockers_after: Array<{ type: string; id: string; delta_p50_days: number }>;
};
export type BacktestRun = {
  id: string; started_at: string; status: string; forecast_day: string | null; p50: string | null; actual_lock: string | null;
  metrics: Record<string, number>; checkpoints: Array<{ forecast_date: string; p10: string; p50: string; p90: string; days_before_lock: number; error_days: number; covered: boolean }>;
};

/** Download a file from the API with the caller's role header (a plain link cannot send it). */
export async function download(path: string, role: Role, filename: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, { headers: { "X-Role": role, "X-User": "demo_user" } });
  if (!res.ok) throw new Error(((await res.json().catch(() => ({ detail: res.statusText }))) as { detail?: string }).detail ?? res.statusText);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export type AgentAction = {
  id: string; site_id: string; state: string; approved_by: string | null; created_at: string;
  body: { action: string; label: string; current_response_days: number; target_response_days: number; est_delta_p50_days: number; open_queries: number; text: string; source: string };
};
export type AskResult = { question: string; sql: string; explanation: string; columns: string[]; rows: Array<Record<string, unknown>>; level: string; note: string; source: string; lineage: { tables: string[] } };
export type EvalSummaryResult = { run_id: string; scenario: string; text: string; source: string; verification_status: "verified" | "partial" | "blocked"; finding_id: string | null };
