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
