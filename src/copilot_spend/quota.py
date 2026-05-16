from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# Published GitHub Copilot premium request unit price as of 2026-05.
# Update this constant if GitHub changes the rate.
PRU_PRICE_USD = 0.04

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
    entitlement: int               # included free PRUs per period
    consumed: int                  # total PRUs used this period (>= 0)
    billable_prus: int             # max(0, consumed - entitlement)
    free_remaining_prus: int       # max(0, entitlement - consumed)
    dollars_owed: float            # billable_prus * PRU_PRICE_USD
    dollars_entitlement: float     # entitlement * PRU_PRICE_USD (reference)
    dollars_free_remaining: float  # free_remaining_prus * PRU_PRICE_USD
    reset: datetime | None


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


def _extract_reset(payload: dict, pi: dict) -> datetime | None:
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
    return None


def parse_quota(payload: dict) -> Spend:
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

    # API semantics observed against a business-plan account:
    #   `remaining` counts down from 0 as you consume PRUs (so the value is
    #   ≤ 0 in steady state on this plan class). `entitlement` is the free
    #   credit per period — the first N PRUs are not billable.
    # Defensive: if `remaining` is positive (unobserved case, possibly other
    # plan classes), treat it as zero consumption rather than guessing.
    consumed = max(0, -remaining)
    billable_prus = max(0, consumed - entitlement)
    free_remaining_prus = max(0, entitlement - consumed)

    dollars_owed = round(billable_prus * PRU_PRICE_USD, 2)
    dollars_entitlement = round(entitlement * PRU_PRICE_USD, 2)
    dollars_free_remaining = round(free_remaining_prus * PRU_PRICE_USD, 2)

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
    )


__all__ = [
    "PRU_PRICE_USD",
    "RESET_FIELD_CANDIDATES",
    "RESET_NESTED_PATHS",
    "NoSubscriptionError",
    "Spend",
    "parse_quota",
]
