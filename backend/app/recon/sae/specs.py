"""Check specs for SAE reconciliation. They are detected in Python (matching + classification), not compiled to SQL,
so CheckRunner skips them and SaeReconciler writes their failures; queries, evidence and responses reuse the common pipeline."""
from app.checks.base import EditCheckSpec


def _s(id_, desc, severity, kind) -> EditCheckSpec:
    return EditCheckSpec(id=id_, type="cross_form", ctq_category="safety", severity=severity, description=desc,
                         source="sae_recon", params=dict(kind=f"sae_recon:{kind}"))


SAE_SPECS: list[EditCheckSpec] = [
    _s("sae_onset", "Serious adverse event onset date differs between EDC and the safety database", "major", "onset"),
    _s("sae_term", "Serious adverse event term differs between EDC and the safety database", "major", "term"),
    _s("sae_seriousness", "Seriousness differs between EDC and the safety database", "major", "seriousness"),
    _s("sae_causality", "Causality differs between EDC and the safety database", "major", "causality"),
    _s("sae_outcome", "Outcome differs or is missing between EDC and the safety database", "major", "outcome"),
    _s("sae_death", "Death is recorded in only one of EDC and the safety database", "critical", "death"),
    _s("sae_safety_only", "Safety case has no matching serious adverse event in EDC", "major", "safety_only"),
    _s("sae_fatal_one_sided", "Fatal serious adverse event present in only one of EDC and the safety database", "critical", "fatal_one_sided"),
]
SAE_SPEC_IDS = {s.id for s in SAE_SPECS} | {"chk_22"}


def is_sae_spec(params: dict) -> bool:
    """True for specs detected in Python by a reconciler (SAE or lab), not compiled to SQL."""
    return str(params.get("kind", "")).startswith(("sae_recon", "lab_recon"))
