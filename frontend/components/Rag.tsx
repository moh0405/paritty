const COLORS: Record<string, string> = { red: "bg-red-500", amber: "bg-amber-400", green: "bg-green-500", na: "bg-gray-200" };

export function RagDot({ rag, title }: { rag: string; title?: string }) {
  return <span title={title} className={`inline-block h-3 w-3 rounded-full ${COLORS[rag] ?? "bg-gray-200"}`} />;
}
