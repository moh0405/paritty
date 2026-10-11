<!-- version: v1 -->
TASK: Draft a short medical review note (three to six sentences) for a medical monitor about the flagged findings for one subject.

State only what the evidence shows, in neutral wording ("potential", "needs review", "reason to look"). Do not diagnose, do not suggest a cause, and end by saying the findings need medical review. Return `claims`: each factual statement in the note with citations to the evidence cells that support it. Copy numbers and dates exactly; do not compute new numbers.

SUBJECT: {{usubjid}}

FLAGGED FINDINGS:
{{findings}}

EVIDENCE (JSON list of rows; each has table, pk, and the row's columns):
{{evidence_json}}
