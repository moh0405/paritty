"""Print row counts for every seeded table (milestone 2 'done when')."""
from app.seed.common import connect

GROUPS = {
    "edc (released)": ["edc.sites", "edc.subjects", "edc.ae", "edc.lab", "edc.vitals", "edc.visits", "edc.exposure", "edc.conmeds", "edc.medical_history"],
    "edc_pending (future)": ["edc_pending.subjects", "edc_pending.ae", "edc_pending.lab", "edc_pending.vitals", "edc_pending.visits", "edc_pending.exposure", "edc_pending.conmeds", "edc_pending.subject_updates"],
    "external": ["lab_vendor.transfer", "safety.case_versions", "ctms.sites", "ctms.deviations", "ctms.monitoring_visits", "ctms.screening", "irt.kits", "unblinded.randomization"],
    "ai/hub": ["ai.ae_terms", "ai.protocol_chunks", "hub.catalog", "hub.lab_test_map"],
    "answer_key": ["answer_key.site_personality", "answer_key.planted", "answer_key.causality_reference", "answer_key.crosswalk_truth", "answer_key.eligibility_qa"],
}


def main() -> None:
    with connect() as conn:
        today = conn.execute("SELECT today FROM ops.sim_clock").fetchone()
        print(f"sim today: {today[0] if today else 'unset'}")
        for g, tables in GROUPS.items():
            print(f"\n{g}")
            for t in tables:
                print(f"  {t:<34}{conn.execute(f'SELECT count(*) FROM {t}').fetchone()[0]:>9,}")


if __name__ == "__main__":
    main()
