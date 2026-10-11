import pandas as pd

from scripts.build_golden import impute_date


def test_partial_dates_imputed_to_first_of_month_and_year():
    d, imp = impute_date(pd.Series(["2014-03-09", "2014-03", "2014", "", None]))
    assert d.iloc[0] == pd.Timestamp("2014-03-09") and not imp.iloc[0]
    assert d.iloc[1] == pd.Timestamp("2014-03-01") and imp.iloc[1]
    assert d.iloc[2] == pd.Timestamp("2014-01-01") and imp.iloc[2]
    assert d.iloc[3:].isna().all() and not imp.iloc[3:].any()
