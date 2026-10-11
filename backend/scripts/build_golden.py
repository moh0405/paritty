"""Normalize CDISC pilot SDTM into edc_pending.* (spec §7.1). Deterministic for a given SEED.

Timeline compression: pilot dates span ~2 years; each subject is shifted so consent falls in the first
~180 sim days (site activation offset + U(0,120)), so a demo trial can reach lock within a year.
entered_at here is a placeholder (event + 2 days); scale_sites.py assigns real per-site entry lags.
"""
import json
import re
from datetime import timedelta

import numpy as np
import pandas as pd

from app.medical.ctcae import GRADED_TESTS, grade_lab
from app.seed.common import RAW, connect, copy_df, reset_seeded, rng
from app.sim.constants import STUDY_START

SITE_NAMES = [
    "Halvren Memory Clinic", "Ostrava Brook Neurology", "Pellmar Cognitive Center", "Wyndale Brain Institute",
    "Tarnowick Neuro Associates", "Quillon Valley Clinic", "Brasmere Research Group", "Ellowen Memory Center",
    "Dunmarrow Neurology", "Fenwick Reach Clinic", "Glimmerton Cognitive Care", "Harrowgate Neuro Research",
    "Isleworth Park Clinic", "Jorvane Memory Institute", "Kestrelby Neurology", "Lorimont Brain Health",
    "Mossgrave Clinical Research", "Norvale Cognitive Center", "Orrinford Neurology", "Pemberlyn Memory Clinic",
    "Quarrowby Research Center", "Rathmoor Neuro Group", "Selwick Cognitive Clinic", "Thornaby Brain Institute",
]
CITIES = ["Brightwater", "Calderfield", "Dovemont", "Eastharrow", "Fairlinden", "Greywick", "Hollowmere", "Ironvale",
          "Junipor", "Kelmsford", "Larkhaven", "Mirewood"]
BILI_MGDL = 17.1


def impute_date(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    """ISO-8601 (possibly partial) -> (date, imputed flag). Missing day/month -> 1 / Jan."""
    s = s.fillna("").astype(str).str.strip()
    full = pd.to_datetime(s.str[:10], format="%Y-%m-%d", errors="coerce")
    ym = pd.to_datetime(s.where(s.str.fullmatch(r"\d{4}-\d{2}"), None) + "-01", format="%Y-%m-%d", errors="coerce")
    y = pd.to_datetime(s.where(s.str.fullmatch(r"\d{4}"), None) + "-01-01", format="%Y-%m-%d", errors="coerce")
    out = full.fillna(ym).fillna(y)
    imputed = out.notna() & full.isna()
    return out, imputed


def main() -> None:
    r = rng(1)
    dm = pd.read_parquet(RAW / "dm.parquet")
    ae = pd.read_parquet(RAW / "ae.parquet")
    lb = pd.read_parquet(RAW / "lb.parquet")
    vs = pd.read_parquet(RAW / "vs.parquet")
    sv = pd.read_parquet(RAW / "sv.parquet")
    ex = pd.read_parquet(RAW / "ex.parquet")
    cm = pd.read_parquet(RAW / "cm.parquet")
    mh = pd.read_parquet(RAW / "mh.parquet")
    ds = pd.read_parquet(RAW / "ds.parquet")
    log: list[str] = []

    # ---- subjects: consent, shift ------------------------------------------------------------
    sv["d"] = pd.to_datetime(sv.SVSTDTC.str[:10], errors="coerce")
    first_visit = sv.groupby("USUBJID").d.min()
    dm = dm.set_index("USUBJID")
    dm["first_visit"] = first_visit
    dm["consent"] = dm.first_visit - pd.to_timedelta(r.integers(0, 15, len(dm)), unit="D")  # RFICDTC is blank in pilot
    site_ids = sorted(dm.SITEID.unique())
    site_off = {s: int(r.integers(0, 61)) for s in site_ids}
    new_consent = pd.Series(
        [pd.Timestamp(STUDY_START) + timedelta(days=site_off[s] + int(r.integers(0, 121))) for s in dm.SITEID],
        index=dm.index)
    dm["shift"] = (new_consent - dm.consent)
    shift = dm["shift"]

    def sh(df: pd.DataFrame, col: pd.Series) -> pd.Series:
        return col + df.USUBJID.map(shift)

    entered = lambda d: d + timedelta(days=2)  # noqa: E731  placeholder, replaced in scale_sites

    sites = pd.DataFrame({"site_id": site_ids, "name": SITE_NAMES[: len(site_ids)], "is_synthetic": False})

    dsd = ds[ds.DSCAT == "DISPOSITION EVENT"].set_index("USUBJID")
    status_map = {"COMPLETED": "completed", "SCREEN FAILURE": "screen_failure", "DEATH": "died"}
    first_dose, _ = impute_date(dm.RFXSTDTC.reset_index(drop=True))
    first_dose.index = dm.index
    subjects, updates = [], []
    for u, row in dm.iterrows():
        sh_ = row["shift"]
        consent = row.consent + sh_
        fd = first_dose[u]
        disp_date, _ = impute_date(pd.Series([dsd.DSSTDTC.get(u, "")]))
        disp = disp_date.iloc[0]
        disp = disp + sh_ if pd.notna(disp) else pd.NaT
        decod = dsd.DSDECOD.get(u, "")
        status = status_map.get(decod, "discontinued")
        death = pd.to_datetime(row.DTHDTC[:10], errors="coerce") if row.DTHFL == "Y" and row.DTHDTC else pd.NaT
        death = death + sh_ if pd.notna(death) else pd.NaT
        subjects.append(dict(
            usubjid=u, site_id=row.SITEID, age=int(row.AGE) if pd.notna(row.AGE) else None, sex=row.SEX,
            consent_at=consent.date(), first_dose_at=(fd + sh_).date() if pd.notna(fd) else None,
            discontinued_at=None, death_at=None, status="enrolled", is_synthetic=False,
            entered_at=entered(consent).date()))
        if pd.notna(disp):
            updates.append(dict(
                usubjid=u, apply_on=(disp + timedelta(days=2)).date(), status=status,
                discontinued_at=disp.date() if status in ("discontinued", "screen_failure") else None,
                death_at=death.date() if pd.notna(death) else None))
    subjects = pd.DataFrame(subjects)
    updates = pd.DataFrame(updates)

    # ---- AE ----------------------------------------------------------------------------------
    onset, imputed = impute_date(ae.AESTDTC)
    end, _ = impute_date(ae.AEENDTC)
    undated = onset.isna()
    if undated.any():
        log.append(f"ae: dropped {int(undated.sum())} rows without an onset date")
    sev_grade = {"MILD": 1, "MODERATE": 2, "SEVERE": 3}  # approximation; true CTCAE grade not in SDTM
    aedf = pd.DataFrame({
        "usubjid": ae.USUBJID, "site_id": ae.USUBJID.map(dm.SITEID), "source_seq": ae.AESEQ.astype(int),
        "term_verbatim": ae.AETERM, "term_coded": ae.AEDECOD, "onset_at": sh(ae, onset), "end_at": sh(ae, end),
        "date_imputed": imputed, "serious": ae.AESER.eq("Y"), "severity": ae.AESEV,
        "ctcae_grade": ae.AESEV.map(sev_grade).astype("Int64"), "causality": ae.AEREL.replace("", None), "outcome": ae.AEOUT.replace("", None),
        "augmented": False})[~undated]
    aedf["entered_at"] = aedf.onset_at.map(lambda d: entered(d).date())
    for c in ("onset_at", "end_at"):
        aedf[c] = aedf[c].dt.date

    # ---- labs --------------------------------------------------------------------------------
    lb = lb[lb.LBSTRESN.notna()].copy()
    ts = pd.to_datetime(lb.LBDTC, format="ISO8601", errors="coerce")
    undated = ts.isna()
    if undated.any():
        log.append(f"lab: excluded {int(undated.sum())} undated rows")
    lb, ts = lb[~undated], ts[~undated]
    ts = ts.where(lb.LBDTC.str.len() > 10, ts + pd.Timedelta(hours=8))
    val, uln, lln = lb.LBSTRESN.astype(float), lb.LBSTNRHI.astype(float), lb.LBSTNRLO.astype(float)
    unit = lb.LBSTRESU.replace("", None)
    is_bili = lb.LBTESTCD.eq("BILI")  # EDC holds conventional bilirubin (mg/dL); vendor sends umol/L (spec §9.4)
    val, uln, lln = (x.where(~is_bili, x / BILI_MGDL) for x in (val, uln, lln))
    unit = unit.where(~is_bili, "mg/dL")
    labdf = pd.DataFrame({
        "usubjid": lb.USUBJID, "site_id": lb.USUBJID.map(dm.SITEID), "test_code": lb.LBTESTCD,
        "value": val, "unit": unit, "uln": uln, "lln": lln, "x_uln": (val / uln).where(uln > 0),
        "visit": lb.VISIT, "source_seq": lb.LBSEQ.astype(int), "collected_at": ts + lb.USUBJID.map(shift)})
    labdf["ctcae_grade"] = pd.array([
        grade_lab(t, v, u_, l_, un) if t in GRADED_TESTS else None
        for t, v, u_, l_, un in zip(labdf.test_code, labdf.value, labdf.uln, labdf.lln, labdf.unit)], dtype="Int64")
    labdf["entered_at"] = labdf.collected_at.map(lambda d: entered(d).date())

    # ---- vitals: unique timestamps via timepoint ordinal ------------------------------------
    vs = vs[vs.VSSTRESN.notna()].copy()
    d, _ = impute_date(vs.VSDTC)
    vs["ord"] = vs.sort_values("VSTPTNUM").groupby(["USUBJID", "VSTESTCD", "VSDTC"]).cumcount()
    vsdf = pd.DataFrame({
        "usubjid": vs.USUBJID, "site_id": vs.USUBJID.map(dm.SITEID), "test_code": vs.VSTESTCD,
        "value": vs.VSSTRESN.astype(float), "unit": vs.VSSTRESU.replace("", None), "visit": vs.VISIT,
        "measured_at": d + pd.Timedelta(hours=8) + pd.to_timedelta(vs.ord.fillna(0) * 2, unit="m") + vs.USUBJID.map(shift)})
    vsdf = vsdf[vsdf.measured_at.notna()]
    vsdf["entered_at"] = vsdf.measured_at.map(lambda x: entered(x).date())

    # ---- visits / exposure / conmeds / history ----------------------------------------------
    vd, _ = impute_date(sv.SVSTDTC)
    visits = pd.DataFrame({
        "usubjid": sv.USUBJID, "site_id": sv.USUBJID.map(dm.SITEID), "visit": sv.VISIT,
        "planned_day": sv.VISITDY.astype("Int64"), "actual_date": sh(sv, vd)})
    visits = visits[visits.actual_date.notna()]
    visits["entered_at"] = visits.actual_date.map(lambda x: entered(x).date())
    visits["actual_date"] = visits.actual_date.dt.date

    es, _ = impute_date(ex.EXSTDTC)
    ee, _ = impute_date(ex.EXENDTC)
    expo = pd.DataFrame({
        "usubjid": ex.USUBJID, "site_id": ex.USUBJID.map(dm.SITEID), "dose": 1.0,  # blinded: EXDOSE would reveal the arm
        "start_at": sh(ex, es), "end_at": sh(ex, ee)})
    expo = expo[expo.start_at.notna()]
    expo["entered_at"] = expo.start_at.map(lambda x: entered(x).date())
    for c in ("start_at", "end_at"):
        expo[c] = expo[c].dt.date

    cs, _ = impute_date(cm.CMSTDTC)
    ce, _ = impute_date(cm.CMENDTC)
    cmdf = pd.DataFrame({
        "usubjid": cm.USUBJID, "site_id": cm.USUBJID.map(dm.SITEID),
        "term": cm.CMDECOD.where(cm.CMDECOD.str.len() > 0, cm.CMTRT), "start_at": sh(cm, cs), "end_at": sh(cm, ce)})
    cmdf = cmdf[cmdf.start_at.notna()]
    cmdf["entered_at"] = cmdf.start_at.map(lambda x: entered(x).date())
    for c in ("start_at", "end_at"):
        cmdf[c] = cmdf[c].dt.date
    mhdf = pd.DataFrame({"usubjid": mh.USUBJID, "term": mh.MHDECOD.where(mh.MHDECOD.str.len() > 0, mh.MHTERM)})

    # ---- load --------------------------------------------------------------------------------
    names = lb.groupby("LBTESTCD").LBTEST.first()
    with connect() as conn:
        conn.execute("TRUNCATE edc.sites, edc.subjects, edc.ae, edc.lab, edc.vitals, edc.visits, edc.exposure, "
                     "edc.conmeds, edc.medical_history, edc_pending.sites, edc_pending.subjects, edc_pending.ae, "
                     "edc_pending.lab, edc_pending.vitals, edc_pending.visits, edc_pending.exposure, "
                     "edc_pending.conmeds, edc_pending.medical_history, edc_pending.subject_updates RESTART IDENTITY CASCADE")
        reset_seeded(conn)
        copy_df(conn, "hub.lab_test_map", pd.DataFrame({"test_code": names.index, "test_name": names.values}))
        for t, df in [("sites", sites), ("subjects", subjects), ("ae", aedf), ("lab", labdf), ("vitals", vsdf),
                      ("visits", visits), ("exposure", expo), ("conmeds", cmdf), ("medical_history", mhdf),
                      ("subject_updates", updates)]:
            print(f"edc_pending.{t}: {copy_df(conn, 'edc_pending.' + t, df)} rows")
        conn.commit()
    (RAW / "build_golden.log.json").write_text(json.dumps(log, indent=2))
    for line in log:
        print("note:", line)


if __name__ == "__main__":
    main()
