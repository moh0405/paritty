import os

import psycopg
import pytest

from app.config import get_settings
from app.db.target import use_database, with_dbname
from app.evals import harness, scorer
from app.evals.fork_manager import GOLDEN_DB, TemplateDbForkManager
from app.evals.injectors import REGISTRY
from app.evals.scenarios import Injection, Scenario, list_scenarios, load
from app.seed.common import PROTOCOL


def golden_exists() -> bool:
    try:
        with psycopg.connect(with_dbname(get_settings().database_url, "postgres")) as c:
            return bool(c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (GOLDEN_DB,)).fetchone())
    except Exception:
        return False


needs_golden = pytest.mark.skipif(not golden_exists(), reason="golden template database missing (run make golden)")


def test_scenarios_load_and_every_kind_has_an_injector():
    names = {s["name"] for s in list_scenarios()}
    assert {"smoke", "full", "sites", "forecast_backtest"} <= names
    for n in names:
        for inj in load(n).injections:
            assert inj.kind in REGISTRY, f"{n} uses unknown injector {inj.kind}"


def test_scenario_expands_model_from_environment():
    assert load("smoke").model == get_settings().gemini_fast_model


def test_injector_registry_covers_the_spec_list_for_built_modules():
    expected = {"impossible_value", "date_order", "unit_mixup", "missing_visit", "duplicate", "missing_field", "lab_value_mismatch", "lab_unit_mismatch",
                "lab_one_sided", "stale_feed", "sae_date_shift", "sae_synonym", "sae_coded_change", "sae_causality_flip", "sae_seriousness_flip",
                "sae_missing_outcome", "sae_edc_only", "sae_safety_only", "sae_death_mismatch", "hys_law_plant", "site_creep", "rare_ae_cluster",
                "ae_lab_link", "site_personality"}
    assert expected <= set(REGISTRY)


@needs_golden
def test_fork_is_isolated_fast_and_deleted():
    fm = TemplateDbForkManager()
    f = fm.create("fork_pytest")
    try:
        assert f.seconds < 30
        with psycopg.connect(f.app_url) as c:
            before = c.execute("SELECT count(*) FROM edc.ae").fetchone()[0]
            c.execute("DELETE FROM edc.ae")
            c.commit()
        with psycopg.connect(get_settings().database_url) as main:
            assert main.execute("SELECT count(*) FROM edc.ae").fetchone()[0] >= before >= 0      # the main database is untouched
    finally:
        fm.delete(f)
    with psycopg.connect(with_dbname(get_settings().database_url, "postgres")) as c:
        assert not c.execute("SELECT 1 FROM pg_database WHERE datname = 'fork_pytest'").fetchone()


@needs_golden
def test_mini_run_plants_blindly_records_the_key_scores_and_cleans_up():
    s = get_settings()
    main_app, main_eval = s.database_url, s.eval_admin_url
    scn = Scenario("mini", 6, "m", "v1", [Injection("impossible_value", 3), Injection("hys_law_plant", 1)], baseline=False)
    fm = TemplateDbForkManager()
    f = fm.create("fork_pytest_mini")
    try:
        obs, planted, truth, done = harness.run_on_fork(f, scn, seed=12345, run_id="00000000-0000-0000-0000-000000000abc")
        assert done["impossible_value"] == 3 and len(planted) >= 3
        assert set(planted.kind) >= {"impossible_value"}
        metrics = {(m.module, m.metric): m.value for m in scorer.score(planted, truth, obs, None, f.seconds)}
        assert ("checks", "recall") in metrics and ("system", "grounding_rate") in metrics
        # the answer key lives only in the fork and is invisible to the app role
        with psycopg.connect(f.app_url) as c:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("SET ROLE data_manager")
                c.execute("SELECT * FROM answer_key.planted")
    finally:
        use_database(main_app, main_eval)
        fm.delete(f)
    with psycopg.connect(main_eval) as c:      # nothing leaked into the main answer key
        assert c.execute("SELECT count(*) FROM answer_key.planted WHERE scenario_run_id = '00000000-0000-0000-0000-000000000abc'").fetchone()[0] == 0
    assert os.environ["DATABASE_URL"] == main_app


def test_score_metrics_on_synthetic_observations():
    import pandas as pd
    planted = pd.DataFrame([dict(kind="impossible_value", usubjid="u1", site_id="701", src_table="edc.vitals", src_pk="5", field="value", injected="300"),
                            dict(kind="impossible_value", usubjid="u2", site_id="701", src_table="edc.vitals", src_pk="6", field="value", injected="300")])
    from datetime import date
    obs = scorer.Observations(date(2026, 1, 1), check_keys={("edc.vitals", "5"), ("edc.vitals", "99")}, claims={"verified": 4}, llm={"calls": 0, "input_tokens": 0, "output_tokens": 0, "avg_latency_ms": 0}, counts={"queries": 0})
    m = {(x.module, x.metric): x.value for x in scorer.score(planted, pd.DataFrame(), obs, None, 0.1)}
    assert m[("checks", "recall")] == 0.5 and m[("checks", "precision")] == 0.5
    ctl = scorer.Observations(date(2026, 1, 1), check_keys={("edc.vitals", "99")})
    m2 = {(x.module, x.metric): x.value for x in scorer.score(planted, pd.DataFrame(), obs, ctl, 0.1)}
    assert m2[("checks", "precision")] == 1.0                      # the control run also flagged row 99, so it is not a false alarm
