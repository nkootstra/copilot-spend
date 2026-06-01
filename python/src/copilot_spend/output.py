from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from copilot_spend.quota import AI_CREDIT_PRICE_USD, PRU_PRICE_USD, Spend


def _format_dollars(amount: float) -> str:
    if amount < 0:
        return f"-${abs(amount):.2f}"
    return f"${amount:.2f}"


def _format_reset(reset: datetime | None, now: datetime) -> str:
    if reset is None:
        return "next reset: unknown"

    absolute = reset.strftime("%b %d, %Y")
    delta_days = (reset.date() - now.date()).days

    if delta_days == 0:
        relative = "today"
    elif delta_days == 1:
        relative = "tomorrow"
    elif delta_days > 1:
        relative = f"in {delta_days} days"
    elif delta_days == -1:
        relative = "yesterday (overdue)"
    else:
        relative = f"overdue by {abs(delta_days)} days"

    return f"{absolute} ({relative})"


def render(spend: Spend, *, now: datetime) -> str:
    plan_label = f" ({spend.plan})" if spend.plan else ""
    login_label = spend.login or "<unknown account>"

    if spend.token_based_billing:
        lines = [
            f"GitHub Copilot - {login_label}{plan_label}",
            "  Billing:   token-based",
            f"  Used:      {spend.consumed} AI credits",
        ]

        if spend.unlimited:
            lines.append("  Budget:    unlimited")
            lines.append("  Remaining: unlimited")
            if spend.overage_permitted:
                lines.append("  Overage:   enabled")
        elif spend.billable_prus > 0:
            suffix = "; overage enabled" if spend.overage_permitted else ""
            lines.append(
                f"  Budget:    {_format_dollars(spend.dollars_entitlement)}"
                f"  ({spend.entitlement} AI credits)"
            )
            lines.append(
                f"  Billable:  {_format_dollars(spend.dollars_owed)}"
                f"  ({spend.billable_prus} AI credits over budget{suffix})"
            )
        else:
            lines.append(
                f"  Budget:    {_format_dollars(spend.dollars_entitlement)}"
                f"  ({spend.entitlement} AI credits)"
            )
            lines.append(
                f"  Remaining: {_format_dollars(spend.dollars_free_remaining)}"
                f"  ({spend.free_remaining_prus} AI credits left)"
            )

        lines.append(f"  Resets:    {_format_reset(spend.reset, now)}")
        return "\n".join(lines)

    lines = [
        f"GitHub Copilot - {login_label}{plan_label}",
        f"  Used:      {spend.consumed} PRUs",
        f"  Allowance: {_format_dollars(spend.dollars_entitlement)}  ({spend.entitlement} PRUs included)",
    ]

    if spend.billable_prus > 0:
        lines.append(
            f"  Billable:  {_format_dollars(spend.dollars_owed)}"
            f"  ({spend.billable_prus} PRUs over allowance at $0.04/PRU)"
        )
    else:
        lines.append(
            f"  Remaining: {_format_dollars(spend.dollars_free_remaining)}"
            f"  ({spend.free_remaining_prus} PRUs of free allowance left)"
        )

    lines.append(f"  Resets:    {_format_reset(spend.reset, now)}")
    return "\n".join(lines)


def render_json(spend: Spend) -> str:
    """Render Spend as a stable, machine-readable JSON object.

    Schema is the contract for scripts that pipe `copilot-spend --json` into
    jq, dashboards, or alerting. Adding new fields is fine; renaming or
    removing is a breaking change.
    """
    token_based = spend.token_based_billing
    remaining_ai_credits = (
        spend.free_remaining_prus if token_based and not spend.unlimited else None
    )
    payload: dict[str, Any] = {
        "ai_credit_monthly_spend_available": False if token_based else None,
        "ai_credit_price_usd": AI_CREDIT_PRICE_USD if token_based else None,
        "billable_ai_credits": spend.billable_prus if token_based else None,
        "billing_model": "token_based" if token_based else "premium_requests",
        "login": spend.login,
        "plan": spend.plan,
        "entitlement_prus": spend.entitlement,
        "consumed_prus": spend.consumed,
        "billable_prus": spend.billable_prus,
        "free_remaining_prus": spend.free_remaining_prus,
        "included_ai_credits": max(0, spend.entitlement) if token_based else None,
        "dollars_owed": spend.dollars_owed,
        "dollars_entitlement": spend.dollars_entitlement,
        "dollars_free_remaining": spend.dollars_free_remaining,
        "legacy_consumed_premium_interactions": spend.consumed if token_based else None,
        "legacy_entitlement_premium_interactions": spend.entitlement if token_based else None,
        "legacy_has_quota": spend.has_quota if token_based else None,
        "legacy_overage_permitted": spend.overage_permitted if token_based else None,
        "legacy_overage_premium_interactions": spend.overage_count if token_based else None,
        "legacy_remaining_premium_interactions": spend.free_remaining_prus if token_based else None,
        "legacy_unlimited": spend.unlimited if token_based else None,
        "pru_price_usd": None if token_based else PRU_PRICE_USD,
        "remaining_ai_credits": remaining_ai_credits,
        "reset": spend.reset.isoformat() if spend.reset is not None else None,
        "token_based_billing": token_based,
        "used_ai_credits": spend.consumed if token_based else None,
    }
    return json.dumps(payload, indent=2, sort_keys=True)
