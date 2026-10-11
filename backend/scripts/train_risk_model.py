"""Train the learned site risk model on simulated site histories (spec §9.7; part of `make seed`). Needs no database and never
reads the answer key. Writes backend/models/site_risk.joblib (gitignored); deterministic for a given SEED."""
from app.config import get_settings
from app.sites import risk_model


def main() -> None:
    model = risk_model.train(get_settings().seed)
    risk_model.save(model)
    m = model.metrics
    print(f"site risk model: {model.n_sites} simulated sites; held-out AUC {m['holdout_auc']:.2f}, precision@k {m['holdout_precision_at_k']:.2f}, "
          f"pattern accuracy {m['holdout_pattern_accuracy']:.2f} -> {risk_model.MODEL_PATH.name}")
    for feature, value in sorted(model.importance.items(), key=lambda x: -x[1])[:5]:
        print(f"  {risk_model.feature_label(feature):<45} importance {value:.3f}")


if __name__ == "__main__":
    main()
