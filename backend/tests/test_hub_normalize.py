import pytest

from app.hub.normalize import norm_site_name, parse_irt_ref, parse_lab_ref, parse_safety_ref, parse_site_code


def test_clean_formats_parse_to_the_same_subject():
    assert parse_lab_ref("PT701-1015").usubjid == "01-701-1015"
    assert parse_safety_ref("SUBJ 1015 / SITE 701").usubjid == "01-701-1015"
    k = parse_irt_ref("R-701-015")
    assert (k.site, k.number) == ("701", "015")


@pytest.mark.parametrize("noisy", ["PT701-1O15", "pt701-1015", "PT 701 - 1015", "PT701_1015", "PT701-l015"])
def test_noisy_lab_references_are_repaired(noisy):
    assert parse_lab_ref(noisy).usubjid == "01-701-1015"


def test_repair_is_flagged():
    assert parse_lab_ref("PT701-1O15").repaired and not parse_lab_ref("PT701-1015").repaired


@pytest.mark.parametrize("noisy", ["SUBJ 1015/SITE 701", "Subj 1015 / Site 701", "SUBJ 1015 SITE 701", "SUBJ 1O15 / SITE 701"])
def test_noisy_safety_references_are_repaired(noisy):
    assert parse_safety_ref(noisy).usubjid == "01-701-1015"


def test_garbage_does_not_parse():
    assert parse_lab_ref("hello") is None and parse_safety_ref(None) is None and parse_irt_ref("") is None
    assert parse_lab_ref("PT7011015") is None        # missing separator is left for the fuzzy matcher


def test_site_codes_and_duplicate_suffix():
    assert parse_site_code("SITE-0701") == ("701", "")
    assert parse_site_code("SITE-0711B") == ("711", "B")
    assert parse_site_code("site 0750") == ("750", "")
    assert parse_site_code("Halvren") is None


def test_site_name_normalization_makes_variants_comparable():
    base = norm_site_name("Halvren Memory Clinic")
    for v in ("Halvren Memory Clinic, LLC", "The Halvren Memory Clinic", "HALVREN MEMORY CLN", "Halvren Memory Clinic, L.L.C."):
        assert norm_site_name(v) == base
    assert norm_site_name("Quillon Valley CTR") == "quillon valley center"
