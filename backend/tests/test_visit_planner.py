from datetime import date

import pytest

from app.sites.visit_planner import action_for, next_month, risk_of, site_level


@pytest.mark.parametrize("reds,ambers,level", [(0, 0, "green"), (0, 1, "green"), (0, 2, "amber"), (1, 0, "amber"), (2, 0, "red"), (3, 4, "red")])
def test_site_level_thresholds(reds, ambers, level):
    assert site_level(reds, ambers) == level


def test_action_is_visit_call_or_remote_and_quiet_sites_are_left_alone():
    assert action_for("red", 0) == "visit" and action_for("amber", 0) == "call"
    assert action_for("green", 2) == "remote" and action_for("green", 0) is None


def test_risk_averages_the_two_scores_when_the_model_is_available():
    assert risk_of(80, None) == pytest.approx(0.8)
    assert risk_of(80, 40) == pytest.approx(0.6)


def test_next_month_rolls_over_the_year():
    assert next_month(date(2026, 3, 6)) == "2026-04" and next_month(date(2026, 12, 31)) == "2027-01"
