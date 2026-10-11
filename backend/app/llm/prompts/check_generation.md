<!-- version: v1 -->
TASK: Propose data edit checks implied by the study protocol text below.

Each check must be justified by an exact sentence copied from one protocol chunk (`quote`) and name that chunk (`chunk_id`). Only propose checks that the allowed specification types can express. Do not invent limits that the text does not state.

ALLOWED TYPES AND PARAMETERS (params_json is a JSON object):
- range: {"table": "edc.vitals" | "edc.lab" | "edc.subjects", "column": "value" | "x_uln" | "age", "test_code": optional code such as "SYSBP" or "ALT", "visit": optional visit name such as "SCREENING 1", "min": number or null, "max": number or null}
- date_order: {"mode": "pair", "table": "edc.ae" | "edc.exposure", "earlier_col": column, "later_col": column}

PROTOCOL CHUNKS (JSON list of {id, section, text}):
{{chunks_json}}
