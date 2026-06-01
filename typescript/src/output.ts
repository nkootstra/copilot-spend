import { AI_CREDIT_PRICE_USD, PRU_PRICE_USD, type Spend } from "./quota";

// C-locale abbreviated month names, matching Python's `strftime("%b")`.
const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

const MS_PER_DAY = 86_400_000;

function pad(value: number, width = 2): string {
  return String(value).padStart(width, "0");
}

function formatDollars(amount: number): string {
  if (amount < 0) {
    return `-$${Math.abs(amount).toFixed(2)}`;
  }
  return `$${amount.toFixed(2)}`;
}

/** UTC-anchored calendar midnight for a `Date`, as an epoch millisecond value. */
function utcMidnight(d: Date): number {
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

/** ISO-8601 string in UTC with an explicit `+00:00` offset (Python isoformat). */
function isoUtc(d: Date): string {
  // toISOString() always emits `…T…:…:….sssZ`; swap the millis+Z for `+00:00`.
  return d.toISOString().replace(/\.\d+Z$/, "+00:00");
}

function formatReset(reset: Date | null, now: Date): string {
  if (reset === null) {
    return "next reset: unknown";
  }

  const absolute = `${MONTHS[reset.getUTCMonth()]} ${pad(reset.getUTCDate())}, ${reset.getUTCFullYear()}`;
  const deltaDays = Math.round((utcMidnight(reset) - utcMidnight(now)) / MS_PER_DAY);

  let relative: string;
  if (deltaDays === 0) {
    relative = "today";
  } else if (deltaDays === 1) {
    relative = "tomorrow";
  } else if (deltaDays > 1) {
    relative = `in ${deltaDays} days`;
  } else if (deltaDays === -1) {
    relative = "yesterday (overdue)";
  } else {
    relative = `overdue by ${Math.abs(deltaDays)} days`;
  }

  return `${absolute} (${relative})`;
}

export function render(spend: Spend, now: Date): string {
  const planLabel = spend.plan ? ` (${spend.plan})` : "";
  const loginLabel = spend.login || "<unknown account>";

  if (spend.tokenBasedBilling) {
    const lines = [
      `GitHub Copilot - ${loginLabel}${planLabel}`,
      "  Billing:   token-based",
      `  Used:      ${spend.consumed} AI credits`,
    ];

    if (spend.unlimited) {
      lines.push("  Budget:    unlimited");
      lines.push("  Remaining: unlimited");
      if (spend.overagePermitted) {
        lines.push("  Overage:   enabled");
      }
    } else if (spend.billablePrus > 0) {
      const suffix = spend.overagePermitted ? "; overage enabled" : "";
      lines.push(
        `  Budget:    ${formatDollars(spend.dollarsEntitlement)}  (${spend.entitlement} AI credits)`,
      );
      lines.push(
        `  Billable:  ${formatDollars(spend.dollarsOwed)}  (${spend.billablePrus} AI credits over budget${suffix})`,
      );
    } else {
      lines.push(
        `  Budget:    ${formatDollars(spend.dollarsEntitlement)}  (${spend.entitlement} AI credits)`,
      );
      lines.push(
        `  Remaining: ${formatDollars(spend.dollarsFreeRemaining)}  (${spend.freeRemainingPrus} AI credits left)`,
      );
    }

    lines.push(`  Resets:    ${formatReset(spend.reset, now)}`);
    return lines.join("\n");
  }

  const lines = [
    `GitHub Copilot - ${loginLabel}${planLabel}`,
    `  Used:      ${spend.consumed} PRUs`,
    `  Allowance: ${formatDollars(spend.dollarsEntitlement)}  (${spend.entitlement} PRUs included)`,
  ];

  if (spend.billablePrus > 0) {
    lines.push(
      `  Billable:  ${formatDollars(spend.dollarsOwed)}  (${spend.billablePrus} PRUs over allowance at $0.04/PRU)`,
    );
  } else {
    lines.push(
      `  Remaining: ${formatDollars(spend.dollarsFreeRemaining)}  (${spend.freeRemainingPrus} PRUs of free allowance left)`,
    );
  }

  lines.push(`  Resets:    ${formatReset(spend.reset, now)}`);
  return lines.join("\n");
}

/**
 * Render Spend as a stable, machine-readable JSON object.
 *
 * Schema is the contract for scripts that pipe `copilot-spend --json` into
 * jq, dashboards, or alerting. Adding new fields is fine; renaming or
 * removing is a breaking change.
 */
export function renderJson(spend: Spend): string {
  const tokenBased = spend.tokenBasedBilling;
  const remainingAiCredits = tokenBased && !spend.unlimited ? spend.freeRemainingPrus : null;

  const payload: Record<string, unknown> = {
    ai_credit_monthly_spend_available: tokenBased ? false : null,
    ai_credit_price_usd: tokenBased ? AI_CREDIT_PRICE_USD : null,
    billable_ai_credits: tokenBased ? spend.billablePrus : null,
    billing_model: tokenBased ? "token_based" : "premium_requests",
    login: spend.login,
    plan: spend.plan,
    entitlement_prus: spend.entitlement,
    consumed_prus: spend.consumed,
    billable_prus: spend.billablePrus,
    free_remaining_prus: spend.freeRemainingPrus,
    included_ai_credits: tokenBased ? Math.max(0, spend.entitlement) : null,
    dollars_owed: spend.dollarsOwed,
    dollars_entitlement: spend.dollarsEntitlement,
    dollars_free_remaining: spend.dollarsFreeRemaining,
    legacy_consumed_premium_interactions: tokenBased ? spend.consumed : null,
    legacy_entitlement_premium_interactions: tokenBased ? spend.entitlement : null,
    legacy_has_quota: tokenBased ? spend.hasQuota : null,
    legacy_overage_permitted: tokenBased ? spend.overagePermitted : null,
    legacy_overage_premium_interactions: tokenBased ? spend.overageCount : null,
    legacy_remaining_premium_interactions: tokenBased ? spend.freeRemainingPrus : null,
    legacy_unlimited: tokenBased ? spend.unlimited : null,
    pru_price_usd: tokenBased ? null : PRU_PRICE_USD,
    remaining_ai_credits: remainingAiCredits,
    reset: spend.reset !== null ? isoUtc(spend.reset) : null,
    token_based_billing: tokenBased,
    used_ai_credits: tokenBased ? spend.consumed : null,
  };

  // The sorted key array doubles as JSON.stringify's replacer: it both selects
  // the keys (all of them) and fixes their output order.
  return JSON.stringify(payload, Object.keys(payload).sort(), 2);
}
