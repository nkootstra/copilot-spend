from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# Published GitHub Copilot premium request unit price as of 2026-05.
# Update this constant if GitHub changes the rate.
PRU_PRICE_USD = 0.04

# Published GitHub Copilot AI credit price as of 2026-06.
AI_CREDIT_PRICE_USD = 0.01

# Plausible field names for the next-reset timestamp. Searched at the payload
# top level first, then inside `quota_snapshots.premium_interactions`. The
# endpoint is undocumented; live observation (2026-05) shows `quota_reset_date`
# at the top level with a date-only string. The other names are defensive
# fallbacks in case GitHub renames or relocates the field.
RESET_FIELD_CANDIDATES: tuple[str, ...] = (
    "quota_reset_date",
    "next_reset",
    "reset_date",
    "resets_at",
    "reset",
    "next_reset_date",
)

# Nested paths inside `premium_interactions` to search when no flat candidate
# matches. Each path is a tuple of keys to walk.
RESET_NESTED_PATHS: tuple[tuple[str, ...], ...] = (
    ("reset", "date"),
    ("reset", "at"),
    ("next", "reset"),
)


class NoSubscriptionError(Exception):
    pass


@dataclass(frozen=True)
class Spend:
    login: str
    plan: str
    entitlement: int  # included free units per period
    consumed: int  # total units used this period (>= 0)
    billable_prus: int  # max(0, consumed - entitlement)
    free_remaining_prus: int  # max(0, entitlement - consumed)
    dollars_owed: float
    dollars_entitlement: float
    dollars_free_remaining: float
    reset: datetime | None
    token_based_billing: bool = False
    unlimited: bool = False
    has_quota: bool = True
    overage_permitted: bool = False
    overage_count: int = 0


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Date-only strings (e.g. "2026-06-01") parse to naive datetimes; attach
    # UTC so downstream comparisons and formatting are consistent.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_nonnegative_int(value: Any, *, default: int = 0) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _extract_reset(payload: dict[str, Any], pi: dict[str, Any]) -> datetime | None:
    for source in (payload, pi):
        for name in RESET_FIELD_CANDIDATES:
            if name in source:
                parsed = _parse_iso(source[name])
                if parsed is not None:
                    return parsed
    for path in RESET_NESTED_PATHS:
        cursor: Any = pi
        for key in path:
            if isinstance(cursor, dict) and key in cursor:
                cursor = cursor[key]
            else:
                cursor = None
                break
        parsed = _parse_iso(cursor)
        if parsed is not None:
            return parsed
    if os.environ.get("COPILOT_SPEND_DEBUG") == "1":
        top_keys = sorted(payload.keys())
        pi_keys = sorted(pi.keys())
        print(
            "debug: no reset-date field found. "
            f"Tried top-level={list(RESET_FIELD_CANDIDATES)} and "
            f"premium_interactions nested paths={list(RESET_NESTED_PATHS)}. "
            f"Payload top-level keys={top_keys}. "
            f"premium_interactions keys={pi_keys}. "
            "If GitHub renamed the field, add the new name to RESET_FIELD_CANDIDATES.",
            file=sys.stderr,
        )
    return None


def parse_quota(payload: dict[str, Any]) -> Spend:
    plan = payload.get("copilot_plan") or ""
    snapshots = payload.get("quota_snapshots") or {}
    pi = snapshots.get("premium_interactions") if isinstance(snapshots, dict) else None

    # Origin R7: missing copilot_plan OR missing premium_interactions → no subscription.
    if not plan or not isinstance(pi, dict):
        raise NoSubscriptionError("No Copilot quota on this account.")

    try:
        entitlement = int(pi["entitlement"])
        remaining = int(pi["remaining"])
    except (KeyError, TypeError, ValueError) as exc:
        raise NoSubscriptionError(
            f"premium_interactions missing entitlement/remaining: {exc}"
        ) from None

    token_based_billing = payload.get("token_based_billing") is True
    unlimited = pi.get("unlimited") is True or entitlement < 0
    has_quota = pi.get("has_quota")
    if not isinstance(has_quota, bool):
        has_quota = True
    overage_permitted = pi.get("overage_permitted") is True
    overage_count = _parse_nonnegative_int(pi.get("overage_count"))

    # Legacy responses observed `remaining <= 0`, where consumption was
    # represented by the negative remainder. Token-based billing responses now
    # expose a positive countdown from entitlement instead.
    if unlimited:
        consumed = overage_count
    elif token_based_billing and remaining >= 0:
        consumed = max(0, entitlement - remaining) + overage_count
    elif token_based_billing:
        consumed = max(0, -remaining) + overage_count
    else:
        consumed = max(0, -remaining)
    billable_prus = 0 if unlimited else max(0, consumed - entitlement, overage_count)
    free_remaining_prus = 0 if unlimited else max(0, entitlement - consumed)

    unit_price = AI_CREDIT_PRICE_USD if token_based_billing else PRU_PRICE_USD
    dollars_owed = round(billable_prus * unit_price, 2)
    dollars_entitlement = round(max(0, entitlement) * unit_price, 2)
    dollars_free_remaining = round(free_remaining_prus * unit_price, 2)

    reset = _extract_reset(payload, pi)

    login = payload.get("login") or ""
    if not isinstance(login, str):
        login = ""
    if not isinstance(plan, str):
        plan = ""

    return Spend(
        login=login,
        plan=plan,
        entitlement=entitlement,
        consumed=consumed,
        billable_prus=billable_prus,
        free_remaining_prus=free_remaining_prus,
        dollars_owed=dollars_owed,
        dollars_entitlement=dollars_entitlement,
        dollars_free_remaining=dollars_free_remaining,
        reset=reset,
        token_based_billing=token_based_billing,
        unlimited=unlimited,
        has_quota=has_quota,
        overage_permitted=overage_permitted,
        overage_count=overage_count,
    )


__all__ = [
    "AI_CREDIT_PRICE_USD",
    "PRU_PRICE_USD",
    "RESET_FIELD_CANDIDATES",
    "RESET_NESTED_PATHS",
    "NoSubscriptionError",
    "Spend",
    "parse_quota",
]
