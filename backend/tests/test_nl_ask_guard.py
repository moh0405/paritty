import pytest

from app.hub.ask import GuardError, check_sql


def ok(sql):
    return check_sql(sql)[1]


def test_simple_select_over_an_allowed_view_passes():
    assert ok("SELECT site_id, open_queries FROM hub.v_open_items WHERE open_queries > 3 ORDER BY 2 DESC") == ["hub.v_open_items"]
    assert ok("select * from hub.catalog;") == ["hub.catalog"]
    assert ok("SELECT a.site_id FROM hub.v_open_items a JOIN hub.v_site_counts b ON a.site_id = b.site_id") == ["hub.v_open_items", "hub.v_site_counts"]


def test_ctes_and_subqueries_are_allowed():
    assert ok("WITH x AS (SELECT site_id FROM hub.v_open_items) SELECT * FROM x") == ["hub.v_open_items"]
    assert ok("SELECT * FROM (SELECT site_id FROM hub.v_site_counts) q") == ["hub.v_site_counts"]


@pytest.mark.parametrize("sql", [
    "DELETE FROM hub.catalog", "UPDATE hub.catalog SET owner = 'x'", "DROP TABLE hub.catalog", "INSERT INTO hub.catalog VALUES (1)",
    "SELECT 1; DROP TABLE hub.catalog", "SELECT * FROM hub.catalog; SELECT * FROM hub.dq_results",
    "SELECT * FROM unblinded.randomization", "SELECT * FROM answer_key.planted", "SELECT * FROM audit.log", "SELECT * FROM edc.ae",
    "SELECT * FROM hub.v_sites WHERE true -- hide", "SELECT /* x */ * FROM hub.v_sites",
    "SELECT pg_read_file('/etc/passwd')", "SELECT pg_sleep(100)", "SELECT current_setting('app.site_scope')", "SELECT set_config('a','b',false)",
    "SELECT arm FROM hub.v_subjects", "SELECT * FROM hub.catalog, edc.ae", "SELECT * FROM catalog", "SELECT * FROM information_schema.tables",
    "COPY hub.catalog TO '/tmp/x'", "SELECT * INTO newtable FROM hub.catalog", "", "SET ROLE unblinded_statistician", "EXPLAIN SELECT * FROM hub.catalog",
    "SELECT 1",
])
def test_dangerous_or_out_of_scope_sql_is_rejected(sql):
    with pytest.raises(GuardError):
        check_sql(sql)


def test_a_forbidden_word_inside_a_string_literal_is_fine():
    assert ok("SELECT * FROM hub.catalog WHERE description ILIKE '%update%' OR table_name = 'x; drop'") == ["hub.catalog"]


def test_commas_in_select_and_order_by_are_fine_but_comma_joins_are_not_at_any_depth():
    assert ok("SELECT site_id, open_queries, open_critical_queries FROM hub.v_open_items ORDER BY open_queries DESC, site_id ASC") == ["hub.v_open_items"]
    assert ok("SELECT * FROM hub.v_open_items WHERE site_id IN ('701', '702')") == ["hub.v_open_items"]
    for sql in ("SELECT * FROM (SELECT * FROM hub.catalog, hub.dq_results) q",
                "WITH x AS (SELECT * FROM hub.catalog, edc.ae) SELECT * FROM x",
                "SELECT * FROM hub.v_sites s, hub.v_subjects u WHERE s.site_id = u.site_id"):
        with pytest.raises(GuardError):
            check_sql(sql)
