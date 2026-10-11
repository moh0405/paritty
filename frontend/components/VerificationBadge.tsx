const STYLE: Record<string, string> = {
  verified: "bg-green-100 text-green-800",
  partial: "bg-amber-100 text-amber-900",
  blocked: "bg-red-100 text-red-800",
  unsupported: "bg-amber-100 text-amber-900",
  contradicted: "bg-red-100 text-red-800",
};

export function VerificationBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${STYLE[status] ?? "bg-gray-100"}`}>{status}</span>;
}
