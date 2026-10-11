<!-- version: v1 -->
TASK: An identifier from an external system could not be matched exactly to a record in the clinical database. Decide which candidate it refers to, or that none of them do.

Be conservative: if the identifier could plausibly refer to more than one candidate, or to none, answer "none" so that a person reviews it. Differences from typing mistakes (a swapped pair of digits, a missing separator) are possible, but a single changed digit usually means a different subject.

ENTITY: {{entity}}
SOURCE SYSTEM: {{system}}
SOURCE IDENTIFIER: {{source_id}}

CANDIDATES (id, with the closest text similarity score out of 100):
{{candidates}}

Return `chosen` (exactly one candidate id, or "none"), `confidence` between 0 and 1, and a one-sentence `reason` in neutral wording.
