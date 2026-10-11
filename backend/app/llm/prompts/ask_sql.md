<!-- version: v1 -->
TASK: Turn a question about a clinical trial into ONE read-only PostgreSQL SELECT over the allowed views below.

Rules:
- Use only the views listed, always schema-qualified (for example hub.v_open_items). No other tables, no functions that read files or sleep, no comments, one statement, no semicolons inside.
- The treatment arm is never available. If the question needs something the views do not have, set `refuse` to true and explain in `explanation` what is missing.
- Prefer simple SQL; select only the columns needed; do not add a LIMIT (it is added for you).
- `explanation` is one sentence saying what the query returns.

ALLOWED VIEWS (columns):
{{schema}}

QUESTION: {{question}}
