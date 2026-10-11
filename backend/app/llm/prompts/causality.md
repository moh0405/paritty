<!-- version: v1 -->
TASK: Assess whether a serious adverse event may be related to the study treatment, using a simplified WHO-UMC scale. This is decision support for a medical monitor, who makes the final call.

Categories:
- certain: plausible time relationship, cannot be explained by other causes, and a positive dechallenge AND rechallenge (rechallenge is almost never available, so avoid "certain").
- probable: plausible time relationship to treatment, unlikely to be explained by another cause, and the event resolved after the treatment stopped.
- possible: plausible time relationship, but another cause could also explain it, or the response to stopping treatment is unknown.
- unlikely: the event began before the first dose, the timing is implausible, or the event resolved while treatment continued.
- unassessable: the evidence is not enough to judge.

Use only the evidence below. List what you relied on as `evidence` claims, each citing evidence cells (copy numbers and dates exactly; do not compute new numbers; refer to timing using the dates themselves). List other plausible causes seen in the evidence (concomitant medicines, medical history) in `alternative_causes`. Set `escalate` to true if the evidence is conflicting or thin. Never mention or infer the treatment arm.

SUBJECT: {{usubjid}}
CASE: {{case_id}}

EVIDENCE (JSON list of rows; each has table, pk, and the row's columns):
{{evidence_json}}
