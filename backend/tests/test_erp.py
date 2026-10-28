import pytest

from app import erp


def test_po_match_within_tolerance():
    r = erp.match_po("PO-1003", "V001", 5040.0)  # +0.8%
    assert r["matched"] and r["issues"] == []


def test_po_amount_mismatch():
    r = erp.match_po("PO-1001", "V001", 18500.0)
    assert not r["matched"]
    assert "+54.2%" in r["issues"][0]


def test_po_wrong_vendor_and_closed():
    r = erp.match_po("PO-1004", "V001", 3000.0)
    assert "PO belongs to a different vendor" in r["issues"]
    assert "PO is closed" in r["issues"]


def test_duplicate_found_in_seeded_ledger():
    assert erp.check_duplicate("V001", "INV-778")["duplicate"] is True
    assert erp.check_duplicate("V001", "INV-999")["duplicate"] is False


def test_payment_is_idempotent():
    first = erp.pay_invoice("V001", "INV-901", 12000.0, run_id="run-a")
    again = erp.pay_invoice("V001", "INV-901", 12000.0, run_id="run-a")   # retry / replay
    other = erp.pay_invoice("V001", "INV-901", 12000.0, run_id="run-b")   # a second run
    assert first == {"status": "paid", "replayed": False, "amount": 12000.0}
    assert again["status"] == "paid" and again["replayed"] is True
    assert other["status"] == "duplicate_blocked"


def test_transient_errors_are_retried(monkeypatch):
    monkeypatch.setenv("FLAKY_RATE", "0.5")
    rolls = iter([0.1, 0.2, 0.9])  # fail, fail, succeed
    monkeypatch.setattr(erp.random, "random", lambda: next(rolls))
    assert erp.find_vendor("Acme Supplies")["found"] is True


def test_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setenv("FLAKY_RATE", "1.0")
    with pytest.raises(erp.TransientERPError):
        erp.find_vendor("Acme Supplies")
