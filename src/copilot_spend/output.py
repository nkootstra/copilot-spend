from __future__ import annotations

from datetime import datetime

from copilot_spend.quota import Spend


def _format_dollars(amount: float) -> str:
    if amount < 0:
        return f"-${abs(amount):.2f}"
    return f"${amount:.2f}"


def _format_prus(value: int) -> str:
    return f"{value}"


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
    overage_note = ", in overage" if spend.remaining < 0 else ""

    plan_label = f" ({spend.plan})" if spend.plan else ""
    login_label = spend.login or "<unknown account>"

    lines = [
        f"GitHub Copilot - {login_label}{plan_label}",
        f"  Spent:     {_format_dollars(spend.dollars_spent)}  ({_format_prus(spend.consumed)} PRUs)",
        f"  Allowance: {_format_dollars(spend.dollars_entitlement)}  ({_format_prus(spend.entitlement)} PRUs)",
        f"  Remaining: {_format_dollars(spend.dollars_remaining)}  ({_format_prus(spend.remaining)} PRUs{overage_note})",
        f"  Resets:    {_format_reset(spend.reset, now)}",
    ]
    return "\n".join(lines)
