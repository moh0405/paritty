<!-- version: v2 -->
TASK: Draft a short, courteous follow-up letter from central monitoring to one clinical trial site.

Thank the site team, list the points noticed during central review (name the indicator, its value at the site and the comparison value exactly as in the evidence), and ask the site to reply with context or corrections. Say plainly that the points are reasons to look at the data together, not conclusions about the site. Write each number as it appears in the evidence, rounded to two decimals; do not compute new numbers and do not write any other number (no list numbers, no counts). Cite only the columns shown in the evidence rows (`value`, `comparator`, `rag`, `kri`, `visit_date`, `type`).

Also return `claims`: each factual statement the letter relies on, with citations to the evidence cells that support it.

SITE: {{site}}
PROPOSED CONTACT: {{action}}

INDICATOR NAMES (how to word each `kri` code; these are names, not evidence to cite):
{{indicators}}

EVIDENCE (JSON list of rows; each has table, pk, and the row's columns):
{{evidence_json}}
