from __future__ import annotations

from datetime import datetime, timedelta, timezone

from copilot_spend.output import render
from copilot_spend.quota import PRU_PRICE_USD, Spend


def _spend(
    *,
    consumed: int,
    entitlement: int = 300,
    reset=None,
    login: str = "test-user",
    plan: str = "business",
) -> Spend:
    billable = max(0, consumed - entitlement)
    free_left = max(0, entitlement - consumed)
    return Spend(
        login=login,
        plan=plan,
        entitlement=entitlement,
        consumed=consumed,
        billable_prus=billable,
        free_remaining_prus=free_left,
        dollars_owed=round(billable * PRU_PRICE_USD, 2),
        dollars_entitlement=round(entitlement * PRU_PRICE_USD, 2),
        dollars_free_remaining=round(free_left * PRU_PRICE_USD, 2),
        reset=reset,
    )


NOW = datetime(2026, 5, 16, tzinfo=timezone.utc)


def test_output_contains_required_fields_under_cap_R15():
    reset = datetime(2026, 5, 31, tzinfo=timezone.utc)
    out = render(_spend(consumed=221, reset=reset), now=NOW)

    assert "test-user" in out
    assert "business" in out
    assert "221 PRUs" in out
    assert "$12.00" in out
    assert "300 PRUs included" in out
    assert "$3.16" in out
    assert "79 PRUs of free allowance left" in out
    assert "May 31, 2026" in out


def test_output_contains_required_fields_over_cap():
    reset = datetime(2026, 6, 1, tzinfo=timezone.utc)
    out = render(_spend(consumed=4073, reset=reset), now=NOW)

    assert "test-user" in out
    assert "business" in out
    assert "4073 PRUs" in out
    assert "$150.92" in out
    assert "3773 PRUs over allowance" in out
    assert "Jun 01, 2026" in out


def test_overage_renders_billable_line_not_remaining_line():
    out = render(_spend(consumed=400, reset=datetime(2026, 5, 31, tzinfo=timezone.utc)), now=NOW)

    assert "Billable:" in out
    assert "Remaining:" not in out


def test_under_cap_renders_remaining_line_not_billable_line():
    out = render(_spend(consumed=100, reset=datetime(2026, 5, 31, tzinfo=timezone.utc)), now=NOW)

    assert "Remaining:" in out
    assert "Billable:" not in out


def test_exactly_at_cap_renders_remaining_with_zero():
    out = render(_spend(consumed=300, reset=datetime(2026, 5, 31, tzinfo=timezone.utc)), now=NOW)

    assert "Remaining:" in out
    assert "Billable:" not in out
    assert "$0.00" in out
    assert "0 PRUs of free allowance left" in out


def test_reset_none_renders_unknown_R13():
    out = render(_spend(consumed=100, reset=None), now=NOW)

    assert "next reset: unknown" in out
    assert "2026" not in out  # no leaked date


def test_output_is_pure_ascii_R14():
    out = render(_spend(consumed=4073, reset=datetime(2026, 5, 31, tzinfo=timezone.utc)), now=NOW)

    for ch in out:
        assert ord(ch) < 128, f"non-ASCII character {ch!r} (ord {ord(ch)}) in output"
    assert "\x1b" not in out  # no ANSI escape sequences


def test_dollar_format_always_two_decimals():
    out = render(_spend(consumed=0, reset=datetime(2026, 5, 31, tzinfo=timezone.utc)), now=NOW)

    assert "$12.00" in out
    assert "$12 " not in out
    assert "$12.0 " not in out


def test_relative_today():
    reset = NOW.replace(hour=23)
    out = render(_spend(consumed=100, reset=reset), now=NOW)

    assert "today" in out


def test_relative_tomorrow():
    reset = NOW + timedelta(days=1)
    out = render(_spend(consumed=100, reset=reset), now=NOW)

    assert "tomorrow" in out


def test_relative_n_days():
    reset = NOW + timedelta(days=15)
    out = render(_spend(consumed=100, reset=reset), now=NOW)

    assert "in 15 days" in out


def test_overdue_relative():
    reset = NOW - timedelta(days=3)
    out = render(_spend(consumed=100, reset=reset), now=NOW)

    assert "overdue" in out


def test_missing_login_renders_unknown_account_label():
    out = render(_spend(consumed=100, login="", reset=None), now=NOW)

    assert "<unknown account>" in out


def test_missing_plan_renders_no_plan_suffix():
    out = render(_spend(consumed=100, plan="", reset=None), now=NOW)

    assert "GitHub Copilot - test-user" in out
    assert "()" not in out  # no empty parens for missing plan
