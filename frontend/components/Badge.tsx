const COLORS: Record<string, string> = {
  hys_law: "bg-red-100 text-red-800", lab_grade4: "bg-red-100 text-red-800", lab_grade3: "bg-orange-100 text-orange-800",
  site_creep: "bg-amber-100 text-amber-900", ae_cluster: "bg-amber-100 text-amber-900", ae_lab_link: "bg-gray-100 text-gray-700",
};
const LABELS: Record<string, string> = {
  hys_law: "potential Hy's Law pattern", lab_grade4: "lab grade 4", lab_grade3: "lab grade 3", site_creep: "site ALT trend",
  ae_cluster: "AE cluster", ae_lab_link: "AE near lab change",
};

export function TypeBadge({ type }: { type: string }) {
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${COLORS[type] ?? "bg-gray-100"}`}>{LABELS[type] ?? type}</span>;
}
