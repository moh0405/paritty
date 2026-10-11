"""Assemble data/protocol/protocol.md, the eligibility Q&A set, and load chunks into ai.protocol_chunks (spec §7.5)."""
import json

from app.llm.embed import embed_texts, to_pgvector
from app.protocol.chunker import chunk_protocol
from app.seed.common import PROTOCOL, RAW, connect, copy_df
import pandas as pd

# (question, expected_answer, expected_quote, should_escalate) - quotes must be exact substrings of protocol.md
QA: list[tuple[str, str, str, bool]] = [
    ("Our candidate scored 15 on the Mini-Mental exam. Can we enroll?", "No. The Mini-Mental score must be higher than 15.", "with a Mini-Mental score higher than 15 points", False),
    ("Is a candidate who previously took donepezil eligible?", "No. Previous anticholinesterase treatment is an exclusion.", "Previous treatment with anticholinesterase drugs or memantine.", False),
    ("The patient has tried memantine in the past. Is that a problem?", "Yes, previous memantine treatment is an exclusion.", "Previous treatment with anticholinesterase drugs or memantine.", False),
    ("Does the patient need a caregiver?", "Yes. Lack of a reliable caregiver is an exclusion.", "Lack of a reliable caregiver.", False),
    ("The patient also has vascular dementia. Eligible?", "No. Dementias other than Alzheimer's disease are excluded.", "Dementias other than Alzheimer's disease", False),
    ("What is the upper age limit at consent?", "90 years.", "Subjects must be between 50 and 90 years of age at consent.", False),
    ("Seated systolic BP at screening is 162. Can we screen the patient?", "No. It must be below 160 mmHg.", "Seated systolic blood pressure at Screening 1 must be below 160 mmHg.", False),
    ("What ALT level is allowed at Screening 1?", "No more than 1.5 times ULN.", "must not exceed 1.5 times the upper limit of normal (ULN)", False),
    ("Total bilirubin is 1.8 times ULN at screening. Eligible?", "No. It must not exceed 1.5 times ULN.", "Total bilirubin at Screening 1 must not exceed 1.5 times ULN.", False),
    ("What creatinine clearance is required?", "At least 30 mL/min.", "Creatinine clearance must be at least 30 mL/min.", False),
    ("Can we start procedures before the consent form is signed?", "No. Consent comes first.", "Written informed consent must be obtained before any study procedure is performed.", False),
    ("How many times can a screen failure be rescreened?", "Once, at least 4 weeks later, with sponsor approval.", "Subjects who fail screening may be rescreened once, at least 4 weeks after the original screening date, with sponsor approval.", False),
    ("What is the visit window?", "Plus or minus 7 days around the planned day.", "Each scheduled visit has a window of plus or minus 7 days around its planned study day.", False),
    ("On which study day is the Week 8 visit planned?", "Day 56.", "Week 8 for Day 56", False),
    ("When is the final follow-up visit?", "Week 26, planned for Day 182.", "Week 26 is planned for Day 182 and is the final follow-up visit.", False),
    ("Are the Week 10 visits done in clinic?", "No, they are telephone contacts.", "Visits at Week 10, 14, 18 and 22 are telephone contacts.", False),
    ("In what positions do we measure vital signs?", "Supine for 5 minutes, then standing for 1 and 3 minutes.", "Vital signs are measured supine for 5 minutes, then standing for 1 minute and 3 minutes, at every clinic visit.", False),
    ("The patient missed a patch yesterday. Can they wear two today?", "No. Never two patches on the same day.", "never apply two patches on the same day", False),
    ("Can we dispense a kit after a subject discontinued?", "No.", "Study treatment stops on the date of discontinuation and must not be dispensed afterwards.", False),
    ("Is donepezil allowed during the study?", "No. Anticholinesterase inhibitors are prohibited.", "Anticholinesterase inhibitors and memantine are prohibited during the study.", False),
    ("May the patient take paracetamol for a fever?", "Yes, up to 2 g per day.", "Paracetamol up to 2 g per day is permitted for pain or fever.", False),
    ("ALT is 4x ULN and bilirubin is 2.5x ULN. What do we do?", "Report to the medical monitor within 24 hours and repeat the liver tests within 48 to 72 hours.", "must be reported to the medical monitor within 24 hours", False),
    ("At what ALT level must treatment be interrupted?", "At or above 5 times ULN.", "Study treatment must be interrupted if ALT or AST is at or above 5 times ULN.", False),
    ("When must treatment be permanently stopped for liver values?", "ALT or AST above 8 times ULN.", "Study treatment must be permanently discontinued if ALT or AST is above 8 times ULN.", False),
    ("How fast must we report an SAE?", "Within 24 hours of awareness.", "All serious adverse events must be reported to the sponsor safety team within 24 hours of site awareness.", False),
    ("A subject died overnight. How do we report it?", "Immediately by telephone.", "A death must be reported immediately by telephone.", False),
    ("How soon must visit data be entered in the EDC?", "Within 5 days of the visit.", "Case report form data must be entered within 5 days of the visit.", False),
    ("How long do we have to answer a query?", "10 days from when it was sent.", "Queries must be answered within 10 days of being sent.", False),
    ("Within what time must a discontinued subject attend a final lab visit?", "Within 14 days where possible.", "A subject who discontinues must attend a final lab visit within 14 days where possible.", False),
    ("The patient withdrew consent. Do we delete their earlier data?", "No.", "Withdrawal of consent does not remove data already collected.", False),
    # --- questions that need medical judgment or are not covered: the assistant must escalate ---
    ("The patient has a long QT history and mild fatty liver. Is that OK for enrollment?", "", "", True),
    ("Is the patient's daughter reliable enough as a caregiver? She visits twice a week.", "", "", True),
    ("The patient takes ginkgo biloba. Can they stay in the study?", "", "", True),
    ("The patient seems to have Lewy body features. Do they still count as Alzheimer's?", "", "", True),
    ("Should we unblind this subject because of a rash?", "", "", True),
    ("The patient is on warfarin. Is that acceptable?", "", "", True),
    ("Can we waive the 160 mmHg blood pressure limit for a patient who is otherwise perfect?", "", "", True),
    ("A subject's ALT is 2.0x ULN, which is above the 1.5x screening limit, but it was a one-off after exercise. Can we count it as eligible?", "", "", True),
    ("The patient had a minor stroke 10 months ago. Should we still enroll them?", "", "", True),
    ("What dose of the study patch should we expect the patient to be on?", "", "", True),
]


def main() -> None:
    study = json.loads((RAW / "ctgov_study.json").read_text())["protocolSection"]
    nct = study["identificationModule"]["nctId"]
    real = study["eligibilityModule"]["eligibilityCriteria"].strip()
    inc, exc = real.split("Exclusion Criteria:")
    inc_body = inc.replace("Inclusion Criteria:", "").strip()
    synthetic = (PROTOCOL / "protocol_synthetic_sections.md").read_text()
    head, rest = synthetic.split("## 4. Additional Screening Requirements [SYNTHETIC]", 1)
    md = (
        "# Paritty Study LS-2026-01 - Protocol Summary\n\n"
        "Sections marked [SYNTHETIC] are fictional and written for this demo. Sections marked [REAL] quote the public "
        f"ClinicalTrials.gov record {nct} verbatim.\n\n"
        + head.strip() + "\n\n"
        "## 2. Eligibility - Inclusion Criteria [REAL ClinicalTrials.gov " + nct + "]\n\n" + inc_body + "\n\n"
        "## 3. Eligibility - Exclusion Criteria [REAL ClinicalTrials.gov " + nct + "]\n\n" + exc.strip() + "\n\n"
        "## 4. Additional Screening Requirements [SYNTHETIC]" + rest
    )
    (PROTOCOL / "protocol.md").write_text(md)
    bad = [q for q, _, quote, esc in QA if quote and quote not in md]
    if bad:
        raise SystemExit(f"expected_quote not found in protocol.md for: {bad}")
    with open(PROTOCOL / "eligibility_emails.jsonl", "w") as f:
        for i, (q, a, quote, esc) in enumerate(QA, start=1):
            f.write(json.dumps(dict(id=i, question=q, expected_answer=a, expected_quote=quote, should_escalate=esc)) + "\n")

    chunks = chunk_protocol(md)
    vecs = embed_texts([c.text for c in chunks])
    rows = pd.DataFrame({"section": [c.section for c in chunks], "text": [c.text for c in chunks],
                         "is_synthetic": [c.is_synthetic for c in chunks],
                         "embedding": [to_pgvector(v) if v else None for v in vecs]})
    with connect() as conn:
        conn.execute("TRUNCATE ai.protocol_chunks, answer_key.eligibility_qa RESTART IDENTITY")
        copy_df(conn, "ai.protocol_chunks", rows)
        copy_df(conn, "answer_key.eligibility_qa", pd.DataFrame(
            [dict(id=i, question=q, expected_answer=a, expected_quote=quote, should_escalate=esc)
             for i, (q, a, quote, esc) in enumerate(QA, start=1)]))
        conn.commit()
    words = [len(c.text.split()) for c in chunks]
    print(f"protocol.md: {len(md.split())} words; {len(chunks)} chunks ({min(words)}-{max(words)} words, "
          f"{sum(v is not None for v in vecs)} embedded); {len(QA)} eligibility questions "
          f"({sum(e for *_, e in QA)} escalate)")


if __name__ == "__main__":
    main()
