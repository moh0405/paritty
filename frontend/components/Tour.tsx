"use client";
import { usePathname, useRouter } from "next/navigation";
import { useSyncExternalStore } from "react";

// A short guided path through the story the app tells. The current step lives in localStorage so it survives page changes.
const KEY = "lockstep.tour", EVENT = "lockstep-tour";
const STEPS: Array<{ title: string; body: string; href?: string }> = [
  { title: "What this app does", href: "/today",
    body: "LockStep runs a simulated clinical trial at 24 sites and cleans its data every day, so the database can be locked sooner. This page lists what is waiting for a person." },
  { title: "Time moves when you say so",
    body: "Press +7 days in the dark bar at the top. Each simulated day new data arrives, checks run on it, and sites answer the questions they were sent." },
  { title: "A check caught a bad value", href: "/queries",
    body: "Each row is a question to a site about one data point. Click 'verified' or 'EDC row' on a row to see the exact database cell behind it." },
  { title: "Which sites look unusual", href: "/sites",
    body: "Sites are ranked by how far their data sits from the rest of the study. Click a row to see why. A high score is a reason to look, not a conclusion." },
  { title: "Decide what to do about a site", href: "/sites/visit-plan",
    body: "Press Draft agenda on a site, then Approve. Nothing leaves the system until a person approves it, and approving opens tracked issues." },
  { title: "When can the database lock?", href: "/",
    body: "The date at the top left is the most likely lock date, next to what is holding it back. Tick a what-if box and run it to see the date move." },
];

function write(step: number | null) {
  try {
    if (step === null) localStorage.removeItem(KEY); else localStorage.setItem(KEY, String(step));
  } catch { /* storage unavailable: the tour simply does not persist */ }
  window.dispatchEvent(new Event(EVENT));
}
function subscribe(fn: () => void) {
  window.addEventListener(EVENT, fn);
  window.addEventListener("storage", fn);
  return () => { window.removeEventListener(EVENT, fn); window.removeEventListener("storage", fn); };
}
function read(): string | null {
  try { return localStorage.getItem(KEY); } catch { return null; }
}
export const startTour = () => write(0);

export function Tour() {
  const raw = useSyncExternalStore(subscribe, read, () => null);
  const path = usePathname();
  const router = useRouter();
  if (raw === null) return null;
  const n = Math.min(Math.max(Number(raw) || 0, 0), STEPS.length - 1);
  const step = STEPS[n], last = n === STEPS.length - 1, elsewhere = step.href !== undefined && step.href !== path;
  const go = (to: number) => { write(to); const href = STEPS[to].href; if (href && href !== path) router.push(href); };
  return (
    <div role="dialog" aria-label="Guided tour" className="fixed bottom-6 right-6 z-50 w-80 rounded-xl border border-blue-200 bg-white p-4 text-sm shadow-xl">
      <div className="flex items-start justify-between gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-blue-700">Tour, step {n + 1} of {STEPS.length}</p>
        <button className="text-gray-400 hover:text-gray-700" aria-label="Close the tour" onClick={() => write(null)}>×</button>
      </div>
      <p className="mt-1 font-semibold">{step.title}</p>
      <p className="mt-1 text-gray-600">{step.body}</p>
      <div className="mt-3 flex items-center gap-2">
        {n > 0 && <button className="rounded-md border px-3 py-1 hover:bg-gray-100" onClick={() => go(n - 1)}>Back</button>}
        {elsewhere && <button className="rounded-md border px-3 py-1 hover:bg-gray-100" onClick={() => router.push(step.href!)}>Take me there</button>}
        <button className="ml-auto rounded-md bg-blue-600 px-3 py-1 font-medium text-white hover:bg-blue-700" onClick={() => (last ? write(null) : go(n + 1))}>{last ? "Finish" : "Next"}</button>
      </div>
    </div>
  );
}
