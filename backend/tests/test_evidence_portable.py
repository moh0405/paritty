"""Recorded Gemini answers are keyed by the prompt, so evidence in a prompt must not hold values that differ on every database."""
from app.verification.sources import VOLATILE_COLUMNS, fetch_row


def test_volatile_columns_never_reach_evidence(db):
    ae_id = db.execute("SELECT id FROM edc.ae ORDER BY id LIMIT 1").fetchone()
    if ae_id is None:
        ae_id = db.execute("SELECT id FROM edc_pending.ae ORDER BY id LIMIT 1").fetchone()
    assert VOLATILE_COLUMNS == ["updated_at"]
    row = fetch_row(db, "edc.ae", str(ae_id[0])) if db.execute("SELECT 1 FROM edc.ae WHERE id=%s", (ae_id[0],)).fetchone() else {}
    assert not set(VOLATILE_COLUMNS) & set(row)
    if row:
        assert "usubjid" in row and "onset_at" in row     # the real columns are still there
