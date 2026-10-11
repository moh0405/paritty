"""Seed ai.ae_terms (BM25 + vectors) and hub.catalog (spec §7.6)."""
import csv

import pandas as pd

from app.llm.embed import embed_texts, to_pgvector
from app.seed.common import PROTOCOL, connect, copy_df, fetch_df

DESCRIPTIONS = {
    "edc.sites": ("Study sites in the EDC with fictional names.", "Data Management", "daily", "low"),
    "edc.subjects": ("Enrolled subjects: site, age, sex, consent, first dose, discontinuation and death dates, status. No treatment arm.", "Data Management", "daily", "high"),
    "edc.ae": ("Adverse events reported in the EDC: verbatim and coded term, onset, end, seriousness, severity, causality, outcome.", "Data Management", "daily", "high"),
    "edc.lab": ("Local laboratory results in the EDC with units, normal ranges, multiples of ULN and CTCAE grade.", "Data Management", "daily", "high"),
    "edc.vitals": ("Vital signs: blood pressure, pulse, temperature, weight, height.", "Data Management", "daily", "high"),
    "edc.visits": ("Actual subject visit dates against planned study day.", "Data Management", "daily", "medium"),
    "edc.exposure": ("Study treatment exposure periods per subject.", "Data Management", "daily", "medium"),
    "edc.conmeds": ("Concomitant medications with start and end dates.", "Data Management", "daily", "medium"),
    "edc.medical_history": ("Subject medical history terms.", "Data Management", "once", "high"),
    "lab_vendor.transfer": ("Central laboratory transfer files: patient reference, spelled-out test name, result, unit, collection date as DD/MM/YYYY.", "Central Lab Vendor", "daily", "high"),
    "safety.case_versions": ("Safety database serious adverse event cases, versioned, E2B/openFDA-shaped payload and narrative.", "Drug Safety", "daily", "high"),
    "mock_safety.inbox": ("Messages received by the mock safety API from EDC serious adverse events.", "Drug Safety", "event", "high"),
    "ctms.sites": ("Clinical trial management system site records, with name variants and one duplicate.", "Clinical Operations", "weekly", "low"),
    "ctms.deviations": ("Protocol deviations per patient reference and category.", "Clinical Operations", "weekly", "medium"),
    "ctms.monitoring_visits": ("Monitoring visit dates and types per site.", "Clinical Operations", "weekly", "low"),
    "ctms.screening": ("Screening outcomes and failure reasons per site.", "Clinical Operations", "weekly", "medium"),
    "irt.kits": ("Study kit dispensing records per patient reference.", "Supply Management", "daily", "medium"),
    "unblinded.randomization": ("Randomization and treatment arm. Visible only to the unblinded statistician.", "Unblinded Statistics", "once", "restricted"),
    "ops.queries": ("Data queries and their lifecycle state, priority and aging.", "Data Management", "daily", "medium"),
    "ops.check_failures": ("Edit check failures with the failing source row.", "Data Management", "daily", "medium"),
    "ops.lock_forecasts": ("Daily database lock forecast with P10, P50 and P90 dates and blockers.", "Study Lead", "daily", "low"),
    "ops.kri_values": ("Key risk indicator values per site and day with red/amber/green status.", "Central Monitoring", "daily", "low"),
    "ops.site_risk": ("Site risk scores per day from rules and the trained model.", "Central Monitoring", "daily", "low"),
    "ai.findings": ("Findings from detectors and AI drafts with verification status.", "Data Management", "daily", "medium"),
}


def main() -> None:
    terms: dict[tuple[str, str], str] = {}
    with connect() as conn:
        ae = fetch_df(conn, "SELECT DISTINCT term_coded, term_verbatim FROM edc_pending.ae UNION SELECT DISTINCT term_coded, term_verbatim FROM edc.ae")
    for coded, verbatim in zip(ae.term_coded, ae.term_verbatim):
        terms[(coded, coded)] = "coded"
        terms.setdefault((verbatim, coded), "verbatim")
    with open(PROTOCOL / "ae_synonyms.csv") as f:
        for row in csv.DictReader(f):
            terms[(row["term_a"], row["term_a"])] = terms.get((row["term_a"], row["term_a"]), "synonym_canonical")
            terms[(row["term_b"], row["term_a"])] = "synonym"
    df = pd.DataFrame([dict(term=t, coded_term=c, source=s) for (t, c), s in sorted(terms.items())])
    vecs = embed_texts(list(df.term))
    df["embedding"] = [to_pgvector(v) if v else None for v in vecs]
    with connect() as conn:
        conn.execute("TRUNCATE ai.ae_terms RESTART IDENTITY")
        copy_df(conn, "ai.ae_terms", df)
        conn.execute("TRUNCATE hub.catalog")
        tables = [r[0] for r in conn.execute(
            "SELECT table_schema || '.' || table_name FROM information_schema.tables WHERE table_type='BASE TABLE' "
            "AND table_schema IN ('edc','lab_vendor','safety','mock_safety','ctms','irt','unblinded','ops','ai','hub') ORDER BY 1")]
        rows = []
        for t in tables:
            desc, owner, refresh, sens = DESCRIPTIONS.get(t, (f"Internal table {t}.", "Data Management", "daily", "low"))
            n = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            rows.append(dict(table_name=t, description=desc, owner=owner, refresh=refresh, sensitivity=sens, row_count=n))
        copy_df(conn, "hub.catalog", pd.DataFrame(rows))
        conn.execute("UPDATE hub.catalog SET last_loaded = now()")
        conn.commit()
    print(f"ai.ae_terms: {len(df)} terms ({df.embedding.notna().sum()} embedded); hub.catalog: {len(rows)} tables")


if __name__ == "__main__":
    main()
