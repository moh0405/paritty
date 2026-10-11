"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV: Array<[string, string]> = [
  ["/", "Lock readiness"], ["/queries", "Queries"], ["/checks", "Checks"], ["/recon/labs", "Lab recon"], ["/recon/sae", "SAE recon"],
  ["/medical", "Medical"], ["/medical/liver", "Liver (eDISH)"], ["/medical/trends", "Trends"], ["/sites", "Sites"], ["/sites/visit-plan", "Visit plan"], ["/agent", "Agent"],
  ["/ask", "Ask protocol"], ["/hub", "Data hub"], ["/search", "Term search"], ["/evals", "Evals"],
];

export function Sidebar() {
  const path = usePathname();
  const active = NAV.filter(([h]) => (h === "/" ? path === "/" : path === h || path.startsWith(h + "/"))).sort((a, b) => b[0].length - a[0].length)[0]?.[0];
  return (
    <aside className="sticky top-[56px] hidden h-[calc(100vh-56px)] w-52 shrink-0 flex-col border-r bg-white px-3 py-4 md:flex">
      <nav className="flex flex-col gap-1 text-sm">
        {NAV.map(([href, label]) => (
          <Link key={href} href={href}
            className={`rounded-md px-3 py-2 ${active === href ? "bg-blue-50 font-semibold text-blue-700" : "text-gray-700 hover:bg-gray-100"}`}>{label}</Link>
        ))}
      </nav>
      <p className="mt-auto px-3 text-xs text-gray-500">All numbers click to evidence</p>
    </aside>
  );
}
