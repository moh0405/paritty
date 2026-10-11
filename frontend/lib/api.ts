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
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}
