<!-- version: v1 -->
TASK: Decide whether two adverse event terms describe the SAME clinical event, for reconciling a clinical database with a safety database.

Terms describe the same event when they name the same medical concept at the level of a coded preferred term (synonyms, abbreviations, spelling variants, lay versus medical wording). Terms that are related but clinically different (for example a symptom versus its cause, or a condition versus a complication) are NOT the same event.

TERM A (clinical database): {{term_a}}
Dictionary coded term for A: {{canon_a}}

TERM B (safety database): {{term_b}}
Dictionary coded term for B: {{canon_b}}

Return same_event, a confidence between 0 and 1, and a one-sentence reason that uses neutral wording.
