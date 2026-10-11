<!-- version: v1 -->
TASK: Draft a short agenda for a monitoring {{action}} with one clinical trial site.

List the points to review with the site team, most important first, as numbered lines. Each point names the indicator, its value at the site and the comparison value exactly as in the evidence. Close with one line saying that the points are reasons to look at the data together, not conclusions. Copy numbers and dates from the evidence exactly; do not compute new numbers.

Also return `claims`: each factual statement the agenda relies on, with citations to the evidence cells that support it.

SITE: {{site}}

EVIDENCE (JSON list of rows; each has table, pk, and the row's columns):
{{evidence_json}}
