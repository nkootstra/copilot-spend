from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from copilot_spend.quota import PRU_PRICE_USD, Spend


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
    payload: dict[str, Any] = {
        "login": spend.login,
        "plan": spend.plan,
        "entitlement_prus": spend.entitlement,
        "consumed_prus": spend.consumed,
        "billable_prus": spend.billable_prus,
        "free_remaining_prus": spend.free_remaining_prus,
        "dollars_owed": spend.dollars_owed,
        "dollars_entitlement": spend.dollars_entitlement,
        "dollars_free_remaining": spend.dollars_free_remaining,
        "pru_price_usd": PRU_PRICE_USD,
        "reset": spend.reset.isoformat() if spend.reset is not None else None,
    }
    return json.dumps(payload, indent=2, sort_keys=True)
