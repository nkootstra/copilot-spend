from __future__ import annotations

from datetime import datetime, timedelta, timezone

from copilot_spend.output import render
from copilot_spend.quota import Spend


def _spend(*, consumed=221, remaining=79, entitlement=300, reset=None,
           login="test-user", plan="business"):
    return Spend(
        login=login,
        plan=plan,
        entitlement=entitlement,
        remaining=remaining,
        consumed=consumed,
        dollars_spent=round(consumed * 0.04, 2),
        dollars_remaining=round(remaining * 0.04, 2),
        dollars_entitlement=round(entitlement * 0.04, 2),
        reset=reset,
    )


NOW = datetime(2026, 5, 16, tzinfo=timezone.utc)


def test_output_contains_required_fields_R15():
    reset = datetime(2026, 5, 31, tzinfo=timezone.utc)
    out = render(_spend(reset=reset), now=NOW)

    assert "test-user" in out
    assert "business" in out
    assert "$8.84" in out
    assert "221 PRUs" in out
    assert "$12.00" in out
    assert "300 PRUs" in out
    assert "$3.16" in out
    assert "79 PRUs" in out
    assert "May 31, 2026" in out


def test_reset_none_renders_unknown_R13():
    out = render(_spend(reset=None), now=NOW)

    assert "next reset: unknown" in out
    assert "2026" not in out  # no leaked date


def test_output_is_pure_ascii_R14():
    out = render(_spend(reset=datetime(2026, 5, 31, tzinfo=timezone.utc)), now=NOW)

    for ch in out:
        assert ord(ch) < 128, f"non-ASCII character {ch!r} (ord {ord(ch)}) in output"
    assert "\x1b" not in out  # no ANSI escape sequences


def test_overage_annotation_present_when_negative():
    out = render(_spend(consumed=321, remaining=-21,
                         reset=datetime(2026, 5, 31, tzinfo=timezone.utc)),
                 now=NOW)

    assert "in overage" in out
    assert "-$0.84" in out
    assert "-21 PRUs" in out


def test_no_overage_annotation_when_positive():
    out = render(_spend(reset=datetime(2026, 5, 31, tzinfo=timezone.utc)), now=NOW)

    assert "in overage" not in out


def test_zero_remaining_no_overage():
    out = render(_spend(consumed=300, remaining=0,
                         reset=datetime(2026, 5, 31, tzinfo=timezone.utc)),
                 now=NOW)

    assert "in overage" not in out


def test_dollar_format_always_two_decimals():
    out = render(_spend(consumed=0, remaining=300,
                         reset=datetime(2026, 5, 31, tzinfo=timezone.utc)),
                 now=NOW)

    assert "$0.00" in out
    assert "$12.00" in out
    # Should NOT see one-decimal or no-decimal dollar amounts
    assert "$12 " not in out
    assert "$12.0 " not in out


def test_relative_today():
    reset = NOW.replace(hour=23)
    out = render(_spend(reset=reset), now=NOW)

    assert "today" in out


def test_relative_tomorrow():
    reset = NOW + timedelta(days=1)
    out = render(_spend(reset=reset), now=NOW)

    assert "tomorrow" in out


def test_relative_n_days():
    reset = NOW + timedelta(days=15)
    out = render(_spend(reset=reset), now=NOW)

    assert "in 15 days" in out


def test_overdue_relative():
    reset = NOW - timedelta(days=3)
    out = render(_spend(reset=reset), now=NOW)

    assert "overdue" in out


def test_missing_login_renders_unknown_account_label():
    out = render(_spend(login="", reset=None), now=NOW)

    assert "<unknown account>" in out


def test_missing_plan_renders_no_plan_suffix():
    out = render(_spend(plan="", reset=None), now=NOW)

    assert "GitHub Copilot - test-user" in out
    assert "()" not in out  # no empty parens for missing plan
