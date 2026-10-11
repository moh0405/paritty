"""Plant realistic mess into the golden database and record every plant in answer_key.planted (spec §7.4).

Detectors and app code must never read answer_key; only this script and the eval scorer do.
Plants go into edc_pending.* (nothing has been released yet), lab_vendor, safety, ctms and irt.
"""
import csv
import json
from collections import defaultdict
from datetime import timedelta

import numpy as np
import pandas as pd

from app.medical.ctcae import grade_lab
from app.seed.common import PROTOCOL, connect, copy_df, fetch_df, rng
from app.sim.constants import STUDY_START
from app.sim.personalities import PARAMS, Personality

BILI_UMOL = 17.1
LAB_COLS = "usubjid, site_id, test_code, value, unit, uln, lln, x_uln, ctcae_grade, visit, source_seq, collected_at, entered_at"
VIT_COLS = "usubjid, site_id, test_code, value, unit, visit, measured_at, entered_at"
AE_COLS = ("usubjid, site_id, source_seq, term_verbatim, term_coded, onset_at, end_at, date_imputed, serious, severity, "
           "ctcae_grade, causality, outcome, augmented, entered_at")
RARE_TERM = "TINNITUS"


class Planter:
    def __init__(self, conn, r: np.random.Generator):
        self.conn, self.r = conn, r
        self.records: list[dict] = []
        self.used: dict[str, set] = defaultdict(set)
        pers = fetch_df(conn, "SELECT * FROM answer_key.site_personality").set_index("site_id").personality
        self.mult = pers.map(lambda p: PARAMS[Personality(p)].error_multiplier)
        self.pers = pers

    def add(self, kind, module, src_table, src_pk, field, original, injected, usubjid=None, site_id=None):
        self.records.append(dict(kind=kind, module=module, usubjid=usubjid, site_id=site_id, src_table=src_table,
                                 src_pk=None if src_pk is None else str(src_pk), field=field,
                                 original=None if original is None else str(original),
                                 injected=None if injected is None else str(injected)))

    def pick(self, df: pd.DataFrame, n: int, table: str, weighted: bool = True) -> pd.DataFrame:
        """Sample n unused rows; sites with higher error multipliers are proportionally more likely."""
        df = df[~df.id.isin(self.used[table])]
        if len(df) < n:
            print(f"  warning: only {len(df)} candidates for {n} plants in {table}")
            n = len(df)
        w = df.site_id.map(self.mult).to_numpy(dtype=float) if weighted else np.ones(len(df))
        idx = self.r.choice(len(df), n, replace=False, p=w / w.sum())
        out = df.iloc[idx]
        self.used[table].update(out.id)
        return out

    def q(self, sql: str, params=None):
        return self.conn.execute(sql, params)

    # ---- edit-check errors (~150) ----------------------------------------------------------
    def edit_check_errors(self) -> None:
        r, q = self.r, self.q
        vit = fetch_df(self.conn, "SELECT id, usubjid, site_id, test_code, value FROM edc_pending.vitals")
        bad = {"SYSBP": (8, lambda v: float(r.integers(260, 400))), "DIABP": (6, lambda v: float(r.integers(160, 260))),
               "PULSE": (6, lambda v: float(r.choice([5, 8, 12, 215, 240, 300]))), "TEMP": (4, lambda v: float(r.choice([28.0, 30.5]))),
               "WEIGHT": (4, lambda v: float(r.choice([2.5, 6.8, 9.0]))), "HEIGHT": (2, lambda v: float(r.choice([35, 60, 85])))}
        for code, (n, fn) in bad.items():
            for _, row in self.pick(vit[vit.test_code == code], n, "vitals").iterrows():
                new = fn(row.value)
                q("UPDATE edc_pending.vitals SET value=%s WHERE id=%s", (new, row.id))
                self.add("impossible_value", "checks", "edc.vitals", row.id, "value", row.value, new, row.usubjid, row.site_id)
        for _, row in self.pick(vit[vit.test_code == "WEIGHT"], 10, "vitals").iterrows():  # lb entered as kg
            new = round(row.value * 2.2046, 1)
            q("UPDATE edc_pending.vitals SET value=%s WHERE id=%s", (new, row.id))
            self.add("unit_mixup", "checks", "edc.vitals", row.id, "value", row.value, new, row.usubjid, row.site_id)
        for _, row in self.pick(vit[vit.test_code == "TEMP"], 10, "vitals").iterrows():  # degrees F entered as C
            new = round(row.value * 9 / 5 + 32, 1)
            q("UPDATE edc_pending.vitals SET value=%s WHERE id=%s", (new, row.id))
            self.add("unit_mixup", "checks", "edc.vitals", row.id, "value", row.value, new, row.usubjid, row.site_id)

        ae = fetch_df(self.conn, "SELECT id, usubjid, site_id, onset_at, end_at, entered_at FROM edc_pending.ae WHERE NOT serious")
        for _, row in self.pick(ae[ae.end_at.notna()], 12, "ae").iterrows():   # end before start
            new = pd.Timestamp(row.onset_at).date() - timedelta(days=int(r.integers(3, 20)))
            q("UPDATE edc_pending.ae SET end_at=%s WHERE id=%s", (new, row.id))
            self.add("date_order", "checks", "edc.ae", row.id, "end_at", row.end_at, new, row.usubjid, row.site_id)
        for _, row in self.pick(ae, 5, "ae").iterrows():                          # onset after today (future date)
            new = pd.Timestamp(row.entered_at).date() + timedelta(days=int(r.integers(15, 40)))
            q("UPDATE edc_pending.ae SET onset_at=%s, end_at=NULL WHERE id=%s", (new, row.id))
            self.add("date_order", "checks", "edc.ae", row.id, "onset_at(future)", row.onset_at, new, row.usubjid, row.site_id)
        subj = fetch_df(self.conn, "SELECT usubjid, consent_at FROM edc_pending.subjects").set_index("usubjid").consent_at
        for _, row in self.pick(ae, 5, "ae").iterrows():                          # AE before consent
            new = pd.Timestamp(subj[row.usubjid]).date() - timedelta(days=int(r.integers(5, 30)))
            q("UPDATE edc_pending.ae SET onset_at=%s, end_at=NULL WHERE id=%s", (new, row.id))
            self.add("date_order", "checks", "edc.ae", row.id, "onset_at(before consent)", row.onset_at, new, row.usubjid, row.site_id)

        vis = fetch_df(self.conn, "SELECT id, usubjid, site_id, visit, planned_day, actual_date FROM edc_pending.visits")
        v = vis[vis.planned_day.notna() & (vis.planned_day >= 14)].copy()
        prev = vis[vis.planned_day.notna()].sort_values(["usubjid", "planned_day"])
        prev["prev_date"] = prev.groupby("usubjid").actual_date.shift(1)
        v = v.merge(prev[["id", "prev_date"]], on="id")
        for _, row in self.pick(v[v.prev_date.notna()], 8, "visits").iterrows():   # visit before the previous visit
            new = pd.Timestamp(row.prev_date).date() - timedelta(days=int(r.integers(2, 10)))
            q("UPDATE edc_pending.visits SET actual_date=%s WHERE id=%s", (new, row.id))
            self.add("date_order", "checks", "edc.visits", row.id, "actual_date", row.actual_date, new, row.usubjid, row.site_id)
        later = vis.groupby("usubjid").planned_day.max()
        v2 = vis[vis.planned_day.notna() & (vis.planned_day >= 28)]
        v2 = v2[v2.apply(lambda x: later[x.usubjid] > x.planned_day, axis=1)]
        for _, row in self.pick(v2, 15, "visits").iterrows():                     # missing scheduled visit
            q("DELETE FROM edc_pending.visits WHERE id=%s", (row.id,))
            self.add("missing_visit", "checks", "edc.visits", row.id, row.visit, row.planned_day, None, row.usubjid, row.site_id)

        lab = fetch_df(self.conn, "SELECT id, usubjid, site_id, test_code, value, unit, uln FROM edc_pending.lab")
        for _, row in self.pick(lab, 10, "lab").iterrows():                       # duplicates (EDC and vendor)
            new_id = q(f"INSERT INTO edc_pending.lab ({LAB_COLS}) SELECT {LAB_COLS} FROM edc_pending.lab WHERE id=%s RETURNING id",
                       (row.id,)).fetchone()[0]
            q("INSERT INTO lab_vendor.transfer (file_date, accession_no, patient_ref, test_name, result, unit, collected) "
              "SELECT file_date, %s, patient_ref, test_name, result, unit, collected FROM lab_vendor.transfer WHERE accession_no=%s",
              (f"ACC-{new_id:07d}", f"ACC-{row.id:07d}"))
            self.used["lab"].add(new_id)
            self.add("duplicate", "checks", "edc.lab", new_id, "row", row.id, "copy", row.usubjid, row.site_id)
        for _, row in self.pick(vit, 10, "vitals").iterrows():
            new_id = q(f"INSERT INTO edc_pending.vitals ({VIT_COLS}) SELECT {VIT_COLS} FROM edc_pending.vitals WHERE id=%s RETURNING id",
                       (row.id,)).fetchone()[0]
            self.add("duplicate", "checks", "edc.vitals", new_id, "row", row.id, "copy", row.usubjid, row.site_id)
        for _, row in self.pick(ae, 5, "ae").iterrows():
            new_id = q(f"INSERT INTO edc_pending.ae ({AE_COLS}) SELECT {AE_COLS} FROM edc_pending.ae WHERE id=%s RETURNING id",
                       (row.id,)).fetchone()[0]
            self.used["ae"].add(new_id)
            self.add("duplicate", "checks", "edc.ae", new_id, "row", row.id, "copy", row.usubjid, row.site_id)

        sae = fetch_df(self.conn, "SELECT id, usubjid, site_id FROM edc_pending.ae WHERE serious")
        for _, row in self.pick(sae, 8, "ae_serious").iterrows():                 # serious AE missing severity
            q("UPDATE edc_pending.ae SET severity=NULL WHERE id=%s", (row.id,))
            self.add("missing_field", "checks", "edc.ae", row.id, "severity", None, None, row.usubjid, row.site_id)
        for _, row in self.pick(lab[lab.unit.notna()], 8, "lab").iterrows():      # lab missing unit (vendor too: recon stays clean)
            q("UPDATE edc_pending.lab SET unit=NULL WHERE id=%s", (row.id,))
            q("UPDATE lab_vendor.transfer SET unit=NULL WHERE accession_no=%s", (f"ACC-{row.id:07d}",))
            self.add("missing_field", "checks", "edc.lab", row.id, "unit", row.unit, None, row.usubjid, row.site_id)
        for _, row in self.pick(lab[lab.uln.notna()], 9, "lab").iterrows():       # lab missing reference range
            q("UPDATE edc_pending.lab SET uln=NULL, lln=NULL, x_uln=NULL, ctcae_grade=NULL WHERE id=%s", (row.id,))
            self.add("missing_field", "checks", "edc.lab", row.id, "uln", row.uln, None, row.usubjid, row.site_id)

        # dosing after discontinuation + kits dispensed to discontinued subjects (also hub questions 2 and 3)
        disc = fetch_df(self.conn, "SELECT u.usubjid, s.site_id, u.discontinued_at FROM edc_pending.subject_updates u "
                                   "JOIN edc_pending.subjects s USING (usubjid) WHERE u.status='discontinued' AND u.discontinued_at IS NOT NULL")
        disc = disc.sample(8, random_state=int(r.integers(0, 10_000)))
        for _, row in disc.iloc[:4].iterrows():
            start = pd.Timestamp(row.discontinued_at).date() + timedelta(days=int(r.integers(5, 20)))
            new_id = q("INSERT INTO edc_pending.exposure (usubjid, site_id, dose, start_at, end_at, entered_at) VALUES (%s,%s,1.0,%s,%s,%s) RETURNING id",
                       (row.usubjid, row.site_id, start, start + timedelta(days=7), start + timedelta(days=9))).fetchone()[0]
            self.add("dose_after_discontinuation", "checks", "edc.exposure", new_id, "start_at", row.discontinued_at, start, row.usubjid, row.site_id)
        self.kit_targets = disc.iloc[4:8]

    # ---- external lab vendor mismatches (~25) ---------------------------------------------
    def lab_mismatches(self) -> None:
        r, q = self.r, self.q
        lab = fetch_df(self.conn, "SELECT id, usubjid, site_id, test_code, value, unit FROM edc_pending.lab WHERE value IS NOT NULL "
                                  "AND unit IS NOT NULL AND test_code IN ('ALT','AST','BILI','ALP','CREAT','HGB','PLAT','GLUC','CHOL','ALB')")
        lab = lab[~lab.id.isin(self.used["lab"])]
        for _, row in self.pick(lab, 10, "lab", weighted=False).iterrows():
            acc = f"ACC-{row.id:07d}"
            old = q("SELECT id, result FROM lab_vendor.transfer WHERE accession_no=%s", (acc,)).fetchone()
            new = round(float(old[1]) * (1 + float(r.choice([-1, 1])) * float(r.uniform(0.05, 0.3))), 2)
            q("UPDATE lab_vendor.transfer SET result=%s WHERE id=%s", (str(new), old[0]))
            self.add("lab_value_mismatch", "lab_recon", "lab_vendor.transfer", old[0], "result", old[1], new, row.usubjid, row.site_id)
        for _, row in self.pick(lab[lab.test_code != "BILI"], 5, "lab", weighted=False).iterrows():
            old = q("SELECT id, unit FROM lab_vendor.transfer WHERE accession_no=%s", (f"ACC-{row.id:07d}",)).fetchone()
            new = str(r.choice(["g/L", "mg/dL", "ukat/L"]))
            q("UPDATE lab_vendor.transfer SET unit=%s WHERE id=%s", (new, old[0]))
            self.add("lab_unit_mismatch", "lab_recon", "lab_vendor.transfer", old[0], "unit", old[1], new, row.usubjid, row.site_id)
        for _, row in self.pick(lab, 5, "lab", weighted=False).iterrows():       # EDC has it, vendor does not
            old = q("DELETE FROM lab_vendor.transfer WHERE accession_no=%s RETURNING id", (f"ACC-{row.id:07d}",)).fetchone()
            self.add("lab_one_sided", "lab_recon", "lab_vendor.transfer", old[0], "edc_only", row.value, None, row.usubjid, row.site_id)
        for _, row in self.pick(lab, 5, "lab", weighted=False).iterrows():       # vendor has it, EDC does not
            q("DELETE FROM edc_pending.lab WHERE id=%s", (row.id,))
            self.add("lab_one_sided", "lab_recon", "edc.lab", row.id, "vendor_only", row.value, None, row.usubjid, row.site_id)
        w0 = STUDY_START + timedelta(days=100)  # stale feed: files for 10 sim days arrive late, as one batch
        n = q("UPDATE lab_vendor.transfer SET file_date=%s WHERE file_date >= %s AND file_date < %s",
              (w0 + timedelta(days=10), w0, w0 + timedelta(days=10))).rowcount
        self.add("stale_feed", "lab_recon", "lab_vendor.transfer", None, f"{w0}..{w0 + timedelta(days=9)}", n, "late batch")

    # ---- SAE discrepancies (~30) ------------------------------------------------------------
    def sae_discrepancies(self) -> None:
        r, q = self.r, self.q
        syn: dict[str, list[str]] = defaultdict(list)
        with open(PROTOCOL / "ae_synonyms.csv") as f:
            for row in csv.DictReader(f):
                syn[row["term_a"]].append(row["term_b"])
        cv = fetch_df(self.conn, "SELECT * FROM safety.case_versions ORDER BY safetyreportid, version")
        counts = cv.groupby("safetyreportid").version.transform("max")
        cv = cv[(counts == 1)].copy()
        cv["payload"] = cv.payload.map(lambda p: p if isinstance(p, dict) else json.loads(p))
        cv["term"] = cv.payload.map(lambda p: p["patient"]["reaction"][0]["reactionmeddrapt"])
        cv["usubjid"] = cv.subject_ref.map(lambda s: f"01-{s.split('SITE ')[1]}-{s.split()[1]}")
        ae = fetch_df(self.conn, "SELECT id, usubjid, site_id, term_coded, onset_at, outcome FROM edc_pending.ae WHERE serious")
        ae["key"] = ae.usubjid + "|" + ae.onset_at.map(lambda d: pd.Timestamp(d).strftime("%Y%m%d")) + "|" + ae.term_coded
        ae_by_key = ae.set_index("key")
        pool = list(r.permutation(len(cv)))
        pool_terms = sorted(set(cv.term))

        def take(pred=lambda row: True):
            for i in list(pool):
                row = cv.iloc[i]
                if pred(row):
                    pool.remove(i)
                    return row
            return None

        def ae_of(row):
            p = row.payload["patient"]["reaction"][0]
            return ae_by_key.loc[f"{row.usubjid}|{p['reactionstartdate']}|{p['reactionmeddrapt']}"]

        def save(row, payload, causality=None):
            q("UPDATE safety.case_versions SET payload=%s, causality=COALESCE(%s, causality) WHERE id=%s",
              (json.dumps(payload), causality, int(row.id)))

        def plan(kind, n, fn, pred=lambda row: True):
            for _ in range(n):
                row = take(pred)
                if row is None:
                    print(f"  warning: no candidate case left for {kind}")
                    return
                a = ae_of(row)
                payload = json.loads(json.dumps(row.payload))
                fn(row, a, payload)

        def date_shift(minor):
            def fn(row, a, payload):
                delta = int(r.choice([-1, 1])) * (1 if minor else int(r.integers(3, 11)))
                rx = payload["patient"]["reaction"][0]
                old = rx["reactionstartdate"]
                rx["reactionstartdate"] = (pd.Timestamp(old) + timedelta(days=delta)).strftime("%Y%m%d")
                save(row, payload)
                self.add("sae_date_shift", "sae_recon", "safety.case_versions", row.safetyreportid, "onset_delta_days", old, delta, row.usubjid, a.site_id)
            return fn

        def synonym(row, a, payload):
            new = str(r.choice(syn[row.term]))
            payload["patient"]["reaction"][0]["reactionmeddrapt"] = new
            save(row, payload)
            self.add("sae_synonym", "sae_recon", "safety.case_versions", row.safetyreportid, "reactionmeddrapt", row.term, new, row.usubjid, a.site_id)

        def coded(row, a, payload):
            new = str(r.choice([t for t in pool_terms if t != row.term and t not in syn.get(row.term, [])]))
            payload["patient"]["reaction"][0]["reactionmeddrapt"] = new
            save(row, payload)
            self.add("sae_coded_change", "sae_recon", "safety.case_versions", row.safetyreportid, "reactionmeddrapt", row.term, new, row.usubjid, a.site_id)

        def causality(row, a, payload):
            new = "Not related" if row.causality == "Related" else "Related"
            save(row, payload, new)
            self.add("sae_causality_flip", "sae_recon", "safety.case_versions", row.safetyreportid, "causality", row.causality, new, row.usubjid, a.site_id)

        def seriousness(row, a, payload):
            payload["serious"] = "2"
            for c in [k for k in payload if k.startswith("seriousness")]:
                payload.pop(c)
            save(row, payload)
            self.add("sae_seriousness_flip", "sae_recon", "safety.case_versions", row.safetyreportid, "serious", "1", "2", row.usubjid, a.site_id)

        def missing_outcome(row, a, payload):
            original = payload["patient"]["reaction"][0].pop("reactionoutcome", None)
            save(row, payload)
            self.add("sae_missing_outcome", "sae_recon", "safety.case_versions", row.safetyreportid, "reactionoutcome", original, None, row.usubjid, a.site_id)

        def edc_only(row, a, payload):
            q("DELETE FROM safety.case_versions WHERE safetyreportid=%s", (row.safetyreportid,))
            self.add("sae_edc_only", "sae_recon", "safety.case_versions", row.safetyreportid, "case", "present", "absent", row.usubjid, a.site_id)

        def safety_only(row, a, payload):
            q("DELETE FROM edc_pending.ae WHERE id=%s", (int(a.id),))
            self.add("sae_safety_only", "sae_recon", "edc.ae", int(a.id), "row", "present", "absent", row.usubjid, a.site_id)
            self.records[-1]["field"] = row.safetyreportid

        def death(row, a, payload):
            payload["seriousnessdeath"] = "1"
            payload["patient"]["reaction"][0]["reactionoutcome"] = "5"
            save(row, payload)
            self.add("sae_death_mismatch", "sae_recon", "safety.case_versions", row.safetyreportid, "death", "0", "1", row.usubjid, a.site_id)

        plan("date_shift_minor", 3, date_shift(True))
        plan("date_shift_major", 4, date_shift(False))
        plan("synonym", 5, synonym, lambda row: row.term in syn)
        plan("coded", 3, coded)
        plan("causality", 5, causality, lambda row: row.causality in ("Related", "Not related"))
        plan("seriousness", 2, seriousness)
        plan("missing_outcome", 3, missing_outcome)
        plan("edc_only", 2, edc_only)
        plan("safety_only", 2, safety_only)
        plan("death", 1, death, lambda row: row.payload["patient"]["reaction"][0].get("reactionoutcome") != "5")

    # ---- medical signals ------------------------------------------------------------------
    def set_lab(self, usubjid, visit, test, x_uln) -> int | None:
        row = self.q("SELECT id, uln, lln, unit, site_id FROM edc_pending.lab WHERE usubjid=%s AND visit=%s AND test_code=%s "
                     "AND uln > 0 ORDER BY collected_at LIMIT 1", (usubjid, visit, test)).fetchone()
        if row is None:
            return None
        lid, uln, lln, unit, _ = row
        value = round(x_uln * uln, 2)
        self.q("UPDATE edc_pending.lab SET value=%s, x_uln=%s, ctcae_grade=%s WHERE id=%s",
               (value, x_uln, grade_lab(test, value, uln, lln, unit), lid))
        self.q("UPDATE lab_vendor.transfer SET result=%s WHERE accession_no=%s",
               (str(round(value * BILI_UMOL, 2) if test == "BILI" else value), f"ACC-{lid:07d}"))
        self.used["lab"].add(lid)
        return lid

    def medical_signals(self) -> None:
        r, q = self.r, self.q
        lab = fetch_df(self.conn, "SELECT usubjid, site_id, visit, test_code FROM edc_pending.lab WHERE uln > 0 AND test_code IN ('ALT','AST','BILI','ALP')")
        sub = fetch_df(self.conn, "SELECT usubjid FROM edc_pending.subject_updates WHERE status IN ('completed','discontinued')")
        normal_sites = set(self.pers[self.pers == "normal"].index)
        ok = []
        for visit in ("WEEK 8", "WEEK 12", "WEEK 16"):
            g = lab[(lab.visit == visit) & lab.site_id.isin(normal_sites) & lab.usubjid.isin(sub.usubjid)].groupby(["usubjid", "site_id"]).test_code.nunique()
            ok.append([u for (u, s), n in g.items() if n == 4])
        used_sites: set[str] = set()
        for visit, cands in zip(("WEEK 8", "WEEK 12", "WEEK 16"), ok):
            cands = [u for u in cands if u.split("-")[1] not in used_sites]
            u = str(r.choice(cands))
            used_sites.add(u.split("-")[1])
            ids = [self.set_lab(u, visit, t, x) for t, x in (("ALT", 5.0), ("AST", 4.2), ("BILI", 3.1), ("ALP", 1.2))]
            self.add("hys_law_plant", "medical", "edc.lab", ids[0], "ALT/AST/BILI x ULN", "normal", "5.0/4.2/3.1", u, u.split("-")[1])

        creep_site = str(r.choice(sorted(normal_sites - used_sites)))   # ALT creeps +8% per 2-week visit at one site
        rows = fetch_df(self.conn, "SELECT l.id, l.value, l.uln, l.lln, l.unit, v.planned_day FROM edc_pending.lab l "
                                   "JOIN (SELECT usubjid, visit, max(planned_day) planned_day FROM edc_pending.visits GROUP BY 1,2) v "
                                   "USING (usubjid, visit) WHERE l.site_id=%s AND l.test_code='ALT' AND l.uln > 0", (creep_site,))
        for _, row in rows.iterrows():
            val = round(float(row.value) * 1.08 ** max(0.0, float(row.planned_day) / 14.0), 2)
            q("UPDATE edc_pending.lab SET value=%s, x_uln=%s, ctcae_grade=%s WHERE id=%s",
              (val, val / row.uln, grade_lab("ALT", val, row.uln, row.lln, row.unit), int(row.id)))
            q("UPDATE lab_vendor.transfer SET result=%s WHERE accession_no=%s", (str(val), f"ACC-{int(row.id):07d}"))
            self.used["lab"].add(int(row.id))
        self.add("site_creep", "medical", "edc.lab", None, "ALT x ULN slope", "flat", "+8% per 2 weeks", None, creep_site)

        cl_site = str(r.choice(sorted(normal_sites - used_sites - {creep_site})))  # rare AE cluster: 4 cases at one site
        subs = fetch_df(self.conn, "SELECT usubjid, consent_at FROM edc_pending.subjects WHERE site_id=%s", (cl_site,)).sample(4, random_state=1)
        lag = PARAMS[Personality.NORMAL].entry_lag
        for _, s in subs.iterrows():
            onset = pd.Timestamp(s.consent_at).date() + timedelta(days=int(r.integers(30, 120)))
            new_id = q(f"INSERT INTO edc_pending.ae (usubjid, site_id, source_seq, term_verbatim, term_coded, onset_at, serious, severity, ctcae_grade, causality, outcome, entered_at) "
                       f"VALUES (%s,%s,900,%s,%s,%s,false,'MILD',1,'POSSIBLE','NOT RECOVERED/NOT RESOLVED',%s) RETURNING id",
                       (s.usubjid, cl_site, RARE_TERM, RARE_TERM, onset, onset + timedelta(days=int(r.integers(*lag))))).fetchone()[0]
            self.add("rare_ae_cluster", "medical", "edc.ae", new_id, "term_coded", None, RARE_TERM, s.usubjid, cl_site)

        pl = fetch_df(self.conn, "SELECT id, usubjid, site_id, visit, test_code, uln, lln, unit FROM edc_pending.lab "
                                 "WHERE test_code IN ('PLAT','HGB') AND visit IN ('WEEK 8','WEEK 12','WEEK 16') AND uln > 0")
        pl = pl[~pl.id.isin(self.used["lab"]) & pl.site_id.isin(normal_sites)]
        for i, (_, row) in enumerate(self.pick(pl, 6, "lab", weighted=False).iterrows()):   # AE-lab co-occurrence
            plat = row.test_code == "PLAT"
            val = 60.0 if plat else 5.9
            q("UPDATE edc_pending.lab SET value=%s, x_uln=%s, ctcae_grade=%s WHERE id=%s",
              (val, val / row.uln, grade_lab(row.test_code, val, row.uln, row.lln, row.unit), int(row.id)))
            q("UPDATE lab_vendor.transfer SET result=%s WHERE accession_no=%s", (str(val), f"ACC-{int(row.id):07d}"))
            dt = q("SELECT collected_at::date FROM edc_pending.lab WHERE id=%s", (int(row.id),)).fetchone()[0]
            onset = dt + timedelta(days=int(r.integers(-5, 6)))
            term = "THROMBOCYTOPENIA" if plat else "ANAEMIA"
            ae_id = q(f"INSERT INTO edc_pending.ae (usubjid, site_id, source_seq, term_verbatim, term_coded, onset_at, serious, severity, ctcae_grade, causality, outcome, entered_at) "
                      f"VALUES (%s,%s,901,%s,%s,%s,false,'MODERATE',2,'POSSIBLE','NOT RECOVERED/NOT RESOLVED',%s) RETURNING id",
                      (row.usubjid, row.site_id, term, term, onset, onset + timedelta(days=3))).fetchone()[0]
            self.add("ae_lab_link", "medical", "edc.lab", int(row.id), f"{row.test_code} grade 2 + AE", None, ae_id, row.usubjid, row.site_id)

    # ---- hub quality ----------------------------------------------------------------------
    def hub_quality(self) -> None:
        r, q = self.r, self.q
        dev = fetch_df(self.conn, "SELECT * FROM ctms.deviations ORDER BY id").sample(5, random_state=3)
        for _, d in dev.iterrows():
            nid = q("INSERT INTO ctms.deviations (site_code, patient_ref, category, occurred) VALUES (%s,%s,%s,%s) RETURNING id",
                    (d.site_code, d.patient_ref, d.category, d.occurred)).fetchone()[0]
            self.add("hub_duplicate", "hub", "ctms.deviations", nid, "row", d.id, "copy", None, None)
        for i in range(4):
            ref = f"R-799-{i + 1:03d}"
            q("INSERT INTO irt.kits (kit_no, patient_ref, dispensed) VALUES (%s,%s,%s)", (f"K-9{i:05d}", ref, STUDY_START + timedelta(days=50 + i)))
            self.add("hub_orphan_kit", "hub", "irt.kits", f"K-9{i:05d}", "patient_ref", None, ref)
        subj = fetch_df(self.conn, "SELECT usubjid, first_dose_at FROM edc_pending.subjects WHERE first_dose_at IS NOT NULL")
        truth = fetch_df(self.conn, "SELECT source_id, canonical_id FROM answer_key.crosswalk_truth WHERE system='irt'")
        merged = truth.merge(subj, left_on="canonical_id", right_on="usubjid").sample(3, random_state=5)
        for _, row in merged.iterrows():
            new = pd.Timestamp(row.first_dose_at).date() + timedelta(days=int(r.integers(3, 7)))
            old = q("UPDATE unblinded.randomization SET randomized=%s WHERE patient_ref=%s RETURNING randomized", (new, row.source_id)).fetchone()
            self.add("hub_randomization_after_dose", "hub", "unblinded.randomization", row.source_id, "randomized", row.first_dose_at, new, row.usubjid)
        mv = fetch_df(self.conn, "SELECT id FROM ctms.monitoring_visits").sample(3, random_state=7)
        for i, m in enumerate(mv.id):
            bad = "1900-01-01" if i % 2 == 0 else "2099-12-31"
            q("UPDATE ctms.monitoring_visits SET visit_date=%s WHERE id=%s", (bad, int(m)))
            self.add("hub_impossible_date", "hub", "ctms.monitoring_visits", int(m), "visit_date", None, bad)
        for _, row in self.kit_targets.iterrows():
            ref = truth[truth.canonical_id == row.usubjid].source_id
            if len(ref):
                d = pd.Timestamp(row.discontinued_at).date() + timedelta(days=int(r.integers(10, 30)))
                kit = f"K-8{int(r.integers(0, 99999)):05d}"
                q("INSERT INTO irt.kits (kit_no, patient_ref, dispensed) VALUES (%s,%s,%s)", (kit, ref.iloc[0], d))
                self.add("hub_kit_after_discontinuation", "hub", "irt.kits", kit, "dispensed", row.discontinued_at, d, row.usubjid, row.site_id)


def main() -> None:
    with connect() as conn:
        if conn.execute("SELECT count(*) FROM answer_key.planted").fetchone()[0]:
            raise SystemExit("baseline already planted; rerun the seed from build_golden")
        p = Planter(conn, rng(4))
        for name in ("edit_check_errors", "lab_mismatches", "sae_discrepancies", "medical_signals", "hub_quality"):
            print(f"planting: {name}")
            getattr(p, name)()
        df = pd.DataFrame(p.records)
        copy_df(conn, "answer_key.planted", df)
        conn.commit()
    print(df.groupby(["module", "kind"]).size().to_string())
    print("total planted:", len(df))


if __name__ == "__main__":
    main()
