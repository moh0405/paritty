"""Build the mock external systems from the clean EDC staging data (spec §7.3).

Runs before plant_baseline so that every mismatch between systems is a *planted* one.
Safety narratives are deterministic templates for now; the Gemini layer (milestone 4) can regenerate them.
"""
import json
import re
from datetime import timedelta

import pandas as pd

from app.seed.common import RAW, connect, copy_df, fetch_df, rng, site_of, subj_num
from app.sim.constants import STUDY_START
from app.sim.personalities import Personality

TARGET_MIN_SERIOUS = 40
BILI_UMOL = 17.1
OUTCOME_E2B = {"RECOVERED/RESOLVED": "1", "RECOVERING/RESOLVING": "2", "NOT RECOVERED/NOT RESOLVED": "3",
               "RECOVERED/RESOLVED WITH SEQUELAE": "4", "FATAL": "5", "UNKNOWN": "6"}
CAUSALITY_E2B = {"PROBABLE": "Related", "POSSIBLE": "Related", "REMOTE": "Not related", "NONE": "Not related"}
CRITERIA = ["seriousnesshospitalization", "seriousnesslifethreatening", "seriousnessdisabling", "seriousnessother"]
FAIL_REASONS = ["MMSE outside eligible range", "Prior anticholinesterase use", "Abnormal screening ECG",
                "Unreliable caregiver", "Withdrew consent before baseline", "Screening labs out of range"]
DEV_CATEGORIES = ["Visit out of window", "Missed procedure", "Eligibility deviation", "Informed consent process", "Dosing error"]


def patient_ref(u: str) -> str:
    return f"PT{site_of(u)}-{subj_num(u)}"


def subject_ref(u: str) -> str:
    return f"SUBJ {subj_num(u)} / SITE {site_of(u)}"


def irt_ref(u: str, taken: set[str]) -> str:
    ref = f"R-{site_of(u)}-{int(subj_num(u)) % 1000:03d}"
    return ref if ref not in taken else f"R-{site_of(u)}-{subj_num(u)}"


def e2b_date(d) -> str | None:
    return None if pd.isna(d) else pd.Timestamp(d).strftime("%Y%m%d")


def narrative(row: pd.Series, subj: pd.Series, criteria: list[str], followup: str | None = None) -> str:
    sex = {"M": "male", "F": "female"}.get(subj.sex, "unspecified-sex")
    text = (f"A {int(subj.age)}-year-old {sex} subject (site {subj.site_id}) in a placebo-controlled Alzheimer's disease trial "
            f"reported '{row.term_verbatim.lower()}' with onset on {row.onset_at:%Y-%m-%d}. "
            f"Seriousness criteria: {', '.join(c.replace('seriousness', '') for c in criteria) or 'not specified'}. "
            f"Outcome at report: {(row.outcome or 'unknown').lower()}. Investigator causality: "
            f"{(row.causality or 'not assessed').lower()}.")
    return text + (f" Follow-up: {followup}" if followup else "")


def who_umc(ae: pd.Series, subj: pd.Series, expo: pd.DataFrame, cmed: pd.DataFrame, mh: pd.DataFrame) -> dict:
    """Deterministic simplified WHO-UMC label with a rule trace (spec §7.3). 'certain' needs a rechallenge, which
    the data never contains, so it is never produced."""
    onset = pd.Timestamp(ae.onset_at)
    first = pd.Timestamp(subj.first_dose_at) if pd.notna(subj.first_dose_at) else None
    ends = expo.end_at.dropna()
    last_end = pd.Timestamp(ends.max()) if len(ends) else None
    trace: dict = {"onset": str(onset.date()), "first_dose": str(first.date()) if first is not None else None,
                   "last_dose_end": str(last_end.date()) if last_end is not None else None}
    after_first = first is not None and onset >= first
    plausible = after_first and (last_end is None or onset <= last_end + timedelta(days=30))
    trace.update(onset_after_first_dose=after_first, plausible_time_to_onset=plausible)
    aend = pd.Timestamp(ae.end_at) if pd.notna(ae.end_at) else None
    if last_end is not None and aend is not None and onset <= last_end:
        dechallenge = "positive" if timedelta(0) < aend - last_end <= timedelta(days=30) else (
            "negative" if aend <= last_end else "unknown")
    else:
        dechallenge = "unknown"
    words = {w for w in re.findall(r"[A-Z]{5,}", str(ae.term_coded).upper())}
    mh_overlap = any(words & set(re.findall(r"[A-Z]{5,}", str(t).upper())) for t in mh.term)
    cm_near = bool(((cmed.start_at.map(pd.Timestamp) - onset).abs() <= timedelta(days=7)).any()) if len(cmed) else False
    alt = mh_overlap or cm_near
    trace.update(dechallenge=dechallenge, alternative_cause=alt, mh_overlap=mh_overlap, conmed_started_near_onset=cm_near)
    if not plausible or dechallenge == "negative":
        cat = "unlikely"
    elif dechallenge == "positive" and not alt:
        cat = "probable"
    else:
        cat = "possible"
    return {"category": cat, "trace": trace}


def main() -> None:
    r = rng(3)
    clone_map = json.loads((RAW / "clone_map.json").read_text())
    arm_by_src = pd.read_parquet(RAW / "dm.parquet").set_index("USUBJID").ARM
    with connect() as conn:
        for t in ("lab_vendor.transfer", "safety.case_versions", "ctms.sites", "ctms.deviations", "ctms.monitoring_visits",
                  "ctms.screening", "irt.kits", "unblinded.randomization", "hub.site_xwalk", "hub.subject_xwalk",
                  "answer_key.crosswalk_truth", "answer_key.causality_reference"):
            conn.execute(f"TRUNCATE {t}")
        subj = fetch_df(conn, "SELECT * FROM edc_pending.subjects").set_index("usubjid")
        sites = fetch_df(conn, "SELECT * FROM edc_pending.sites")
        pers = fetch_df(conn, "SELECT * FROM answer_key.site_personality").set_index("site_id").personality

        # ---- 1. serious-AE set: promote severe AEs if needed ----------------------------------
        n_serious = conn.execute("SELECT count(*) FROM edc_pending.ae WHERE serious").fetchone()[0]
        if n_serious < TARGET_MIN_SERIOUS:
            ids = [x[0] for x in conn.execute(
                "SELECT id FROM edc_pending.ae WHERE severity='SEVERE' AND NOT serious ORDER BY id").fetchall()]
            promote = list(r.permutation(ids))
            conn.execute("UPDATE edc_pending.ae SET serious = true, augmented = true WHERE id = ANY(%s)", (promote,))
        ae = fetch_df(conn, "SELECT * FROM edc_pending.ae WHERE serious ORDER BY id")
        expo = fetch_df(conn, "SELECT * FROM edc_pending.exposure")
        cmed = fetch_df(conn, "SELECT * FROM edc_pending.conmeds")
        mh = fetch_df(conn, "SELECT * FROM edc_pending.medical_history")
        print(f"serious AEs: {len(ae)} (augmented: {int(ae.augmented.sum())})")

        # ---- 2. safety.case_versions + causality reference -----------------------------------
        cases, refs, used = [], [], set()
        for _, row in ae.iterrows():
            s = subj.loc[row.usubjid]
            rid = f"LS{int(r.integers(10_000_000, 99_999_999))}"
            while rid in used:
                rid = f"LS{int(r.integers(10_000_000, 99_999_999))}"
            used.add(rid)
            crit = [c for c in CRITERIA if r.random() < {"seriousnesshospitalization": .6, "seriousnesslifethreatening": .2,
                                                         "seriousnessdisabling": .1, "seriousnessother": .3}[c]] or ["seriousnessother"]
            fatal = row.outcome == "FATAL"
            received = pd.Timestamp(row.entered_at) + timedelta(days=int(r.integers(1, 3)))
            payload = {
                "safetyreportid": rid, "receivedate": e2b_date(received), "serious": "1",
                "seriousnessdeath": "1" if fatal else None,
                **{c: "1" for c in crit},
                "patient": {
                    "patientonsetage": str(int(s.age)), "patientsex": {"M": "1", "F": "2"}.get(s.sex, "0"),
                    "reaction": [{"reactionmeddrapt": row.term_coded, "reactionmeddraversionpt": "27.0",
                                  "reactionstartdate": e2b_date(row.onset_at), "reactionenddate": e2b_date(row.end_at),
                                  "reactionoutcome": OUTCOME_E2B.get(row.outcome, "6")}],
                    "drug": [{"medicinalproduct": "STUDY PATCH", "drugcharacterization": "1",
                              "drugstartdate": e2b_date(s.first_dose_at)}]},
            }
            payload = {k: v for k, v in payload.items() if v is not None}
            caus = CAUSALITY_E2B.get(row.causality or "")
            common = dict(safetyreportid=rid, subject_ref=subject_ref(row.usubjid), causality=caus)
            cases.append(dict(**common, version=1, receivedate=payload["receivedate"], payload=json.dumps(payload),
                              narrative=narrative(row, s, crit), available_on=received.date()))
            if r.random() < 0.2 and not fatal:  # follow-up with outcome update / added detail
                v2 = json.loads(json.dumps(payload))
                rx = v2["patient"]["reaction"][0]
                rx["reactionoutcome"] = "1"
                rx["reactionenddate"] = e2b_date(pd.Timestamp(row.onset_at) + timedelta(days=int(r.integers(3, 30))))
                rcv = received + timedelta(days=int(r.integers(4, 11)))
                v2["receivedate"] = e2b_date(rcv)
                cases.append(dict(**common, version=2, receivedate=v2["receivedate"], payload=json.dumps(v2),
                                  narrative=narrative(row, s, crit, "event resolved with no sequelae."),
                                  available_on=rcv.date()))
            res = who_umc(row, s, expo[expo.usubjid == row.usubjid], cmed[cmed.usubjid == row.usubjid],
                          mh[mh.usubjid == row.usubjid])
            refs.append(dict(case_id=rid, category=res["category"], rule_trace=json.dumps(res["trace"])))
        copy_df(conn, "safety.case_versions", pd.DataFrame(cases))
        copy_df(conn, "answer_key.causality_reference", pd.DataFrame(refs))
        print(f"safety.case_versions: {len(cases)} rows ({len(refs)} cases); "
              f"causality reference: {pd.DataFrame(refs).category.value_counts().to_dict()}")

        # ---- 3. central lab vendor transfer ---------------------------------------------------
        lab = fetch_df(conn, "SELECT id, usubjid, test_code, value, unit, collected_at FROM edc_pending.lab WHERE value IS NOT NULL")
        names = fetch_df(conn, "SELECT * FROM hub.lab_test_map").set_index("test_code").test_name
        bili = lab.test_code.eq("BILI")
        value = lab.value.where(~bili, lab.value * BILI_UMOL).round(2)
        vend = pd.DataFrame({
            "file_date": (pd.to_datetime(lab.collected_at).dt.normalize() + pd.to_timedelta(r.integers(0, 3, len(lab)), unit="D")).dt.date,
            "accession_no": [f"ACC-{i:07d}" for i in lab.id], "patient_ref": lab.usubjid.map(patient_ref),
            "test_name": lab.test_code.map(names), "result": value.astype(str),
            "unit": lab.unit.where(~bili, "umol/L"),
            "collected": pd.to_datetime(lab.collected_at).dt.strftime("%d/%m/%Y")})
        print(f"lab_vendor.transfer: {copy_df(conn, 'lab_vendor.transfer', vend)} rows")

        # ---- 4. CTMS --------------------------------------------------------------------------
        variants = [lambda n: n, lambda n: n + ", LLC", lambda n: n.upper().replace("CLINIC", "CLN").replace("CENTER", "CTR"),
                    lambda n: "The " + n]
        ctms_sites, truth = [], []
        for _, st in sites.iterrows():
            code = f"SITE-{int(st.site_id):04d}"
            name = variants[int(r.integers(0, len(variants)))](st["name"])
            ctms_sites.append(dict(site_code=code, site_name=name, city=["Brightwater", "Calderfield", "Dovemont", "Eastharrow",
                                                                         "Fairlinden", "Greywick", "Hollowmere", "Ironvale"][int(st.site_id) % 8],
                                   activated=STUDY_START + timedelta(days=int(r.integers(-30, 40)))))
            truth.append(("ctms_site", code, st.site_id))
        dup_site = sites.site_id.iloc[10]
        d = [x for x in ctms_sites if x["site_code"] == f"SITE-{int(dup_site):04d}"][0]
        ctms_sites.append({**d, "site_code": d["site_code"] + "B", "site_name": d["site_name"].replace("LLC", "L.L.C.")})
        truth.append(("ctms_site", d["site_code"] + "B", dup_site))
        ctms_sites.append(dict(site_code="SITE-0750", site_name="Zephyr Ridge Research", city="Greywick",
                               activated=STUDY_START + timedelta(days=20)))
        truth.append(("ctms_site", "SITE-0750", None))
        copy_df(conn, "ctms.sites", pd.DataFrame(ctms_sites))

        mult = {Personality.RULE_BENDER.value: 3.0, Personality.SLOPPY_ENTRY.value: 2.0}
        devs = []
        for u, s in subj.iterrows():
            for _ in range(r.poisson(0.5 * mult.get(pers[s.site_id], 1.0))):
                devs.append(dict(site_code=f"SITE-{int(s.site_id):04d}", patient_ref=patient_ref(u),
                                 category=DEV_CATEGORIES[int(r.integers(0, len(DEV_CATEGORIES)))],
                                 occurred=pd.Timestamp(s.consent_at).date() + timedelta(days=int(r.integers(0, 170)))))
        copy_df(conn, "ctms.deviations", pd.DataFrame(devs))
        mv = []
        for c in ctms_sites:
            if c["site_code"] == "SITE-0750":
                continue
            d0 = pd.Timestamp(c["activated"]).date()
            for k in range(0, 420, int(r.integers(45, 91))):
                mv.append(dict(site_code=c["site_code"], visit_date=d0 + timedelta(days=k + 20),
                               type=["On-site", "Remote"][int(r.integers(0, 2))], notes=""))
        copy_df(conn, "ctms.monitoring_visits", pd.DataFrame(mv))
        sf = set(fetch_df(conn, "SELECT usubjid FROM edc_pending.subject_updates WHERE status='screen_failure'").usubjid)
        scr = []
        for u, s in subj.iterrows():
            failed = u in sf
            scr.append(dict(site_code=f"SITE-{int(s.site_id):04d}", screened=pd.Timestamp(s.consent_at).date(),
                            outcome="Failed" if failed else "Passed",
                            fail_reason=FAIL_REASONS[int(r.integers(0, len(FAIL_REASONS)))] if failed else None))
        for _, st in sites.iterrows():  # screen failures that never reached the EDC
            for _ in range(int(r.integers(1, 6))):
                scr.append(dict(site_code=f"SITE-{int(st.site_id):04d}", screened=STUDY_START + timedelta(days=int(r.integers(10, 170))),
                                outcome="Failed", fail_reason=FAIL_REASONS[int(r.integers(0, len(FAIL_REASONS)))]))
        copy_df(conn, "ctms.screening", pd.DataFrame(scr))
        print(f"ctms: sites={len(ctms_sites)} deviations={len(devs)} monitoring_visits={len(mv)} screening={len(scr)}")

        # ---- 5. IRT + randomization (arm only here) --------------------------------------------
        visits = fetch_df(conn, "SELECT usubjid, visit, actual_date FROM edc_pending.visits")
        taken: set[str] = set()
        ref_of: dict[str, str] = {}
        kits, rand = [], []
        k = 1
        for u in subj.index:
            src = clone_map.get(u, u)
            arm = arm_by_src.get(src, "Screen Failure")
            if arm == "Screen Failure" or u in sf:
                continue
            ref = irt_ref(u, taken)
            taken.add(ref)
            ref_of[u] = ref
            v = visits[visits.usubjid == u]
            base = v[v.visit == "BASELINE"].actual_date
            rand.append(dict(patient_ref=ref, arm=arm, randomized=base.iloc[0] if len(base) else subj.loc[u].consent_at))
            for _, vv in v[v.visit.str.startswith("WEEK") | v.visit.eq("BASELINE")].iterrows():
                if vv.visit.endswith("(T)"):
                    continue
                kits.append(dict(kit_no=f"K-{k:06d}", patient_ref=ref, dispensed=vv.actual_date))
                k += 1
            truth.append(("irt", ref, u))
        copy_df(conn, "unblinded.randomization", pd.DataFrame(rand))
        copy_df(conn, "irt.kits", pd.DataFrame(kits))
        print(f"irt.kits: {len(kits)}  unblinded.randomization: {len(rand)}")

        # ---- 6. crosswalk truth ----------------------------------------------------------------
        for u in subj.index:
            truth.append(("lab_vendor", patient_ref(u), u))
            truth.append(("safety", subject_ref(u), u))
        copy_df(conn, "answer_key.crosswalk_truth", pd.DataFrame(truth, columns=["system", "source_id", "canonical_id"]))
        conn.commit()


if __name__ == "__main__":
    main()
