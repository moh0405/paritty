<!-- version: v1 -->
TASK: Draft one data query for a clinical trial site about a data point that failed an edit check.

The query text must be specific and short (one or two sentences): name the subject, the recorded value and date exactly as in the evidence, say what is expected, and ask the site to confirm or correct it against source documents. Copy numbers and dates from the evidence exactly; do not compute new numbers.

Also return `claims`: each factual statement the query relies on, with citations to the evidence cells that support it.

EDIT CHECK: {{check_description}}
EXPECTED: {{expected}}
OBSERVED: {{observed}}

EVIDENCE (JSON list of rows; each has table, pk, and the row's columns):
{{evidence_json}}
