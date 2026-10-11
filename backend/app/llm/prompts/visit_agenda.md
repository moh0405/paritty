<!-- version: v2 -->
TASK: Draft a short agenda for a monitoring {{action}} with one clinical trial site.

List the points to review with the site team, most important first, one per line, each line starting with a dash (do not number the lines). Each point names the indicator, its value at the site and the comparison value exactly as in the evidence. Close with one line saying that the points are reasons to look at the data together, not conclusions. Write each number as it appears in the evidence, rounded to two decimals; do not compute new numbers and do not write any other number (no list numbers, no counts). Cite only the columns shown in the evidence rows (`value`, `comparator`, `rag`, `kri`, `visit_date`, `type`).

Also return `claims`: each factual statement the agenda relies on, with citations to the evidence cells that support it.

SITE: {{site}}

INDICATOR NAMES (how to word each `kri` code; these are names, not evidence to cite):
{{indicators}}

EVIDENCE (JSON list of rows; each has table, pk, and the row's columns):
{{evidence_json}}
