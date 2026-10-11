const STYLE: Record<string, string> = {
  clean: "bg-gray-100 text-gray-700", acceptable: "bg-green-100 text-green-800",
  actionable: "bg-amber-100 text-amber-900", critical: "bg-red-100 text-red-800",
};

export function ClassBadge({ cls }: { cls: string }) {
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${STYLE[cls] ?? "bg-gray-100"}`}>{cls}</span>;
}
