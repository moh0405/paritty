"use client";
import { useQuery } from "@tanstack/react-query";
import { api, ROLES, type Role } from "@/lib/api";
import { useRole } from "./Providers";

export function Header() {
  const { role, setRole } = useRole();
  const health = useQuery({
    queryKey: ["health", role],
    queryFn: () => api<{ status: string; db: boolean }>("/health", role),
    refetchInterval: 15000,
  });
  const unblinded = role === "unblinded_statistician";
  return (
    <header className="border-b">
      {unblinded && (
        <div className="bg-red-600 px-4 py-1 text-center text-sm font-medium text-white">
          UNBLINDED VIEW — access is audit-logged
        </div>
      )}
      <div className="flex items-center gap-4 px-4 py-3">
        <span className="font-semibold">LockStep</span>
        <span className="text-sm text-gray-500">
          API: {health.data ? (health.data.db ? "ok" : "no database") : "unreachable"}
        </span>
        <label className="ml-auto text-sm">
          Role{" "}
          <select
            className="rounded border px-2 py-1"
            value={role}
            onChange={(e) => setRole(e.target.value as Role)}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </label>
      </div>
    </header>
  );
}
