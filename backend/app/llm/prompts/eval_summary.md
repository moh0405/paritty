<!-- version: v1 -->
TASK: Summarise an evaluation run of a clinical data-cleaning system for a study lead, in plain English (four to eight sentences).

Say what was tested, what worked well, what did not, and what to look at next. Be specific and honest: mention weak results as clearly as strong ones. Every number you state must be copied exactly from a metric row, and every statement must be listed in `claims` with citations to those rows (table "eval.v_metrics", pk = the row's ref, column "value"). Do not compute new numbers; percentages may be written from a 0-1 value only if you also cite that value. Use neutral wording.

SCENARIO: {{scenario}}

METRICS (JSON list of rows; each has ref, module, metric, value, detail):
{{metrics_json}}
