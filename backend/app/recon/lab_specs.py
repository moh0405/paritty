"""Specs for lab reconciliation. Detected in Python (matching), so CheckRunner skips them and LabReconciler writes their failures."""
from app.checks.base import EditCheckSpec

LAB_SPECS: list[EditCheckSpec] = [
    EditCheckSpec(id="chk_24", type="external_lab", ctq_category="safety", severity="major", source="lab_recon", params=dict(kind="lab_recon:value"),
                  description="Central lab value differs from the EDC value by more than 1%"),
    EditCheckSpec(id="chk_25", type="external_lab", ctq_category="safety", severity="major", source="lab_recon", params=dict(kind="lab_recon:one_sided"),
                  description="Lab result is present in only one of EDC and the central lab file"),
    EditCheckSpec(id="chk_26", type="external_lab", ctq_category="safety", severity="minor", source="lab_recon", params=dict(kind="lab_recon:unit"),
                  description="Lab unit differs between EDC and the central lab"),
    EditCheckSpec(id="lab_stale_feed", type="external_lab", ctq_category="other", severity="major", source="lab_recon", params=dict(kind="lab_recon:stale_feed"),
                  description="No central lab file has arrived for more than 3 days while samples are being collected"),
]
