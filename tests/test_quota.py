from __future__ import annotations

from datetime import datetime, timezone

import pytest

from copilot_spend.quota import (
    PRU_PRICE_USD,
    NoSubscriptionError,
    parse_quota,
)


def _payload(
    *,
    entitlement: int,
    remaining: int,
    reset_field: str = "next_reset",
    reset_value: str | None = "2026-05-31T00:00:00Z",
    plan: str = "business",
    login: str = "u",
    nested_reset: dict | None = None,
) -> dict:
    pi: dict = {"entitlement": entitlement, "remaining": remaining}
    if reset_value is not None:
        pi[reset_field] = reset_value
    if nested_reset is not None:
        pi.update(nested_reset)
    return {
        "login": login,
        "copilot_plan": plan,
        "quota_snapshots": {"premium_interactions": pi},
    }


def test_overage_math_AE3():
    # 4073 PRUs consumed under a 300-PRU allowance → 3773 billable.
    spend = parse_quota(_payload(entitlement=300, remaining=-4073))

    assert spend.entitlement == 300
    assert spend.consumed == 4073
    assert spend.billable_prus == 3773
    assert spend.free_remaining_prus == 0
    assert spend.dollars_owed == 150.92
    assert spend.dollars_entitlement == 12.00
    assert spend.dollars_free_remaining == 0.00


def test_normal_math_AE4():
    # 221 PRUs consumed under a 300-PRU allowance → 0 billable, 79 free left.
    spend = parse_quota(_payload(entitlement=300, remaining=-221))

    assert spend.consumed == 221
    assert spend.billable_prus == 0
    assert spend.free_remaining_prus == 79
    assert spend.dollars_owed == 0.00
    assert spend.dollars_entitlement == 12.00
    assert spend.dollars_free_remaining == 3.16


def test_consumption_exactly_at_allowance():
    spend = parse_quota(_payload(entitlement=300, remaining=-300))

    assert spend.consumed == 300
    assert spend.billable_prus == 0
    assert spend.free_remaining_prus == 0
    assert spend.dollars_owed == 0.00
    assert spend.dollars_free_remaining == 0.00


def test_zero_consumption():
    spend = parse_quota(_payload(entitlement=300, remaining=0))

    assert spend.consumed == 0
    assert spend.billable_prus == 0
    assert spend.free_remaining_prus == 300
    assert spend.dollars_owed == 0.00
    assert spend.dollars_free_remaining == 12.00


def test_positive_remaining_treated_as_zero_consumption():
    # Defensive: positive remaining is not the observed shape on business plans;
    # treat as zero consumption rather than guessing.
    spend = parse_quota(_payload(entitlement=300, remaining=79))

    assert spend.consumed == 0
    assert spend.billable_prus == 0
    assert spend.free_remaining_prus == 300


def test_reset_parses_iso8601_with_z_suffix():
    spend = parse_quota(
        _payload(entitlement=300, remaining=-100, reset_value="2026-05-31T00:00:00Z")
    )

    assert spend.reset is not None
    assert spend.reset == datetime(2026, 5, 31, tzinfo=timezone.utc)


def test_reset_parses_iso8601_with_explicit_offset():
    spend = parse_quota(
        _payload(entitlement=300, remaining=-100, reset_value="2026-05-31T12:00:00+00:00")
    )

    assert spend.reset is not None


def test_reset_uses_second_candidate_when_first_absent():
    spend = parse_quota(_payload(entitlement=300, remaining=-100, reset_field="reset_date"))

    assert spend.reset is not None


def test_reset_uses_third_candidate_when_first_two_absent():
    spend = parse_quota(_payload(entitlement=300, remaining=-100, reset_field="resets_at"))

    assert spend.reset is not None


def test_reset_finds_top_level_quota_reset_date():
    payload = _payload(entitlement=300, remaining=-100, reset_value=None)
    payload["quota_reset_date"] = "2026-06-01"

    spend = parse_quota(payload)

    assert spend.reset == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_reset_date_only_string_attaches_utc():
    spend = parse_quota(_payload(entitlement=300, remaining=-100, reset_value="2026-05-31"))

    assert spend.reset == datetime(2026, 5, 31, tzinfo=timezone.utc)


def test_reset_finds_nested_reset_date():
    payload = _payload(
        entitlement=300,
        remaining=-100,
        reset_value=None,
        nested_reset={"reset": {"date": "2026-05-31T00:00:00Z"}},
    )

    spend = parse_quota(payload)

    assert spend.reset is not None


def test_reset_missing_returns_none_AE5():
    spend = parse_quota(_payload(entitlement=300, remaining=-100, reset_value=None))

    assert spend.reset is None


def test_reset_non_iso_returns_none():
    spend = parse_quota(_payload(entitlement=300, remaining=-100, reset_value="next-tuesday"))

    assert spend.reset is None


def test_missing_premium_interactions_raises_AE7():
    payload = {
        "login": "u",
        "copilot_plan": "business",
        "quota_snapshots": {},
    }

    with pytest.raises(NoSubscriptionError):
        parse_quota(payload)


def test_null_premium_interactions_raises():
    payload = {
        "login": "u",
        "copilot_plan": "business",
        "quota_snapshots": {"premium_interactions": None},
    }

    with pytest.raises(NoSubscriptionError):
        parse_quota(payload)


def test_missing_copilot_plan_raises():
    payload = {
        "login": "u",
        "quota_snapshots": {"premium_interactions": {"entitlement": 300, "remaining": -100}},
    }

    with pytest.raises(NoSubscriptionError):
        parse_quota(payload)


def test_empty_quota_snapshots_raises():
    payload = {"login": "u", "copilot_plan": "business"}

    with pytest.raises(NoSubscriptionError):
        parse_quota(payload)


def test_login_and_plan_populated():
    spend = parse_quota(
        _payload(entitlement=300, remaining=-100, plan="business", login="test-user")
    )

    assert spend.login == "test-user"
    assert spend.plan == "business"


def test_missing_login_becomes_empty_string():
    payload = {
        "copilot_plan": "business",
        "quota_snapshots": {"premium_interactions": {"entitlement": 300, "remaining": -100}},
    }

    spend = parse_quota(payload)

    assert spend.login == ""


def test_pru_price_constant_is_4_cents():
    assert PRU_PRICE_USD == 0.04
