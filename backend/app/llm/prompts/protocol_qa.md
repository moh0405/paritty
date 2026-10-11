<!-- version: v1 -->
TASK: Answer a question from a clinical trial site using ONLY the protocol excerpts below.

Rules for this task:
- Quote the protocol: every statement in the answer must be supported by a quote copied EXACTLY (character for character) from one excerpt, with that excerpt's chunk_id.
- Set `escalate` to true if the excerpts do not clearly settle the question, if answering needs a medical judgment about a specific patient (for example whether a condition, medicine or circumstance makes someone suitable), or if the question is about unblinding. Never guess; escalate instead.
- `confidence` is between 0 and 1: how directly the quotes answer the question.
- Keep the answer to one or two sentences.

QUESTION: {{question}}

PROTOCOL EXCERPTS (JSON list; each has chunk_id, section, text):
{{chunks_json}}
