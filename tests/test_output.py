from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from copilot_spend.output import render, render_json
from copilot_spend.quota import AI_CREDIT_PRICE_USD, PRU_PRICE_USD, Spend


def _spend(
    *,
    consumed: int,
    entitlement: int = 300,
    reset=None,
    login: str = "test-user",
    plan: str = "business",
    token_based_billing: bool = False,
    unlimited: bool = False,
    overage_permitted: bool = False,
    overage_count: int = 0,
) -> Spend:
    billable = 0 if unlimited else max(0, consumed - entitlement)
    free_left = 0 if unlimited else max(0, entitlement - consumed)
    unit_price = AI_CREDIT_PRICE_USD if token_based_billing else PRU_PRICE_USD
    return Spend(
        login=login,
        plan=plan,
        entitlement=entitlement,
        consumed=consumed,
        billable_prus=billable,
        free_remaining_prus=free_left,
        dollars_owed=round(billable * unit_price, 2),
        dollars_entitlement=round(max(0, entitlement) * unit_price, 2),
        dollars_free_remaining=round(free_left * unit_price, 2),
        reset=reset,
        token_based_billing=token_based_billing,
        unlimited=unlimited,
        overage_permitted=overage_permitted,
        overage_count=overage_count,
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


def test_token_based_billing_output_uses_ai_credit_price_without_pru_label():
    reset = datetime(2026, 7, 1, tzinfo=timezone.utc)
    out = render(
        _spend(consumed=154, entitlement=5000, reset=reset, token_based_billing=True),
        now=NOW,
    )

    assert "Billing:   token-based" in out
    assert "154 AI credits" in out
    assert "Budget:    $50.00  (5000 AI credits)" in out
    assert "Remaining: $48.46  (4846 AI credits left)" in out
    assert "AI-credit monthly spend is not available" not in out
    assert "PRUs" not in out


def test_token_based_billing_overage_output_shows_overage_permitted():
    reset = datetime(2026, 7, 1, tzinfo=timezone.utc)
    out = render(
        _spend(
            consumed=5042,
            entitlement=5000,
            reset=reset,
            token_based_billing=True,
            overage_permitted=True,
            overage_count=42,
        ),
        now=NOW,
    )

    assert "Billing:   token-based" in out
    assert "Used:      5042 AI credits" in out
    assert "Budget:    $50.00  (5000 AI credits)" in out
    assert "Billable:  $0.42  (42 AI credits over budget; overage enabled)" in out
    assert "PRUs" not in out


def test_token_based_billing_unlimited_output_has_no_zero_dollar_budget():
    reset = datetime(2026, 7, 1, tzinfo=timezone.utc)
    out = render(
        _spend(
            consumed=0,
            entitlement=0,
            reset=reset,
            token_based_billing=True,
            unlimited=True,
            overage_permitted=True,
        ),
        now=NOW,
    )

    assert "Billing:   token-based" in out
    assert "Used:      0 AI credits" in out
    assert "Budget:    unlimited" in out
    assert "Remaining: unlimited" in out
    assert "$0.00" not in out
    assert "PRUs" not in out


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


def test_render_json_returns_valid_parseable_json():
    out = render_json(_spend(consumed=221, reset=datetime(2026, 5, 31, tzinfo=timezone.utc)))

    parsed = json.loads(out)
    assert isinstance(parsed, dict)


def test_render_json_includes_all_documented_fields():
    reset = datetime(2026, 5, 31, tzinfo=timezone.utc)
    parsed = json.loads(render_json(_spend(consumed=4073, reset=reset)))

    assert parsed["login"] == "test-user"
    assert parsed["plan"] == "business"
    assert parsed["entitlement_prus"] == 300
    assert parsed["consumed_prus"] == 4073
    assert parsed["billable_prus"] == 3773
    assert parsed["free_remaining_prus"] == 0
    assert parsed["dollars_owed"] == 150.92
    assert parsed["dollars_entitlement"] == 12.00
    assert parsed["dollars_free_remaining"] == 0.00
    assert parsed["pru_price_usd"] == PRU_PRICE_USD
    assert parsed["reset"] == "2026-05-31T00:00:00+00:00"


def test_render_json_token_based_billing_marks_ai_credit_bucket():
    parsed = json.loads(
        render_json(_spend(consumed=154, entitlement=5000, token_based_billing=True))
    )

    assert parsed["billing_model"] == "token_based"
    assert parsed["token_based_billing"] is True
    assert parsed["legacy_entitlement_premium_interactions"] == 5000
    assert parsed["legacy_consumed_premium_interactions"] == 154
    assert parsed["legacy_remaining_premium_interactions"] == 4846
    assert parsed["ai_credit_monthly_spend_available"] is False
    assert parsed["legacy_overage_permitted"] is False
    assert parsed["legacy_overage_premium_interactions"] == 0
    assert parsed["legacy_unlimited"] is False
    assert parsed["ai_credit_price_usd"] == AI_CREDIT_PRICE_USD
    assert parsed["included_ai_credits"] == 5000
    assert parsed["used_ai_credits"] == 154
    assert parsed["remaining_ai_credits"] == 4846
    assert parsed["billable_ai_credits"] == 0
    assert parsed["dollars_entitlement"] == 50.00
    assert parsed["dollars_free_remaining"] == 48.46
    assert parsed["dollars_owed"] == 0.00
    assert parsed["pru_price_usd"] is None


def test_render_json_token_based_unlimited_clamps_included_ai_credits():
    parsed = json.loads(
        render_json(
            _spend(
                consumed=0,
                entitlement=-1,
                token_based_billing=True,
                unlimited=True,
            )
        )
    )

    assert parsed["legacy_unlimited"] is True
    assert parsed["legacy_entitlement_premium_interactions"] == -1
    assert parsed["included_ai_credits"] == 0
    assert parsed["remaining_ai_credits"] is None


def test_render_json_reset_none_serializes_as_null():
    parsed = json.loads(render_json(_spend(consumed=100, reset=None)))

    assert parsed["reset"] is None


def test_render_json_keys_sorted_for_stable_diffs():
    out = render_json(_spend(consumed=100, reset=None))
    parsed = json.loads(out)

    # sort_keys=True means key order is deterministic — important for
    # diff-friendly output piped into version control or jq.
    assert list(parsed.keys()) == sorted(parsed.keys())
