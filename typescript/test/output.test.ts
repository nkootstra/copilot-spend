import { describe, expect, test } from "bun:test";
import { render, renderJson } from "../src/output";
import { AI_CREDIT_PRICE_USD, PRU_PRICE_USD, type Spend } from "../src/quota";

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

interface SpendOpts {
  consumed: number;
  entitlement?: number;
  reset?: Date | null;
  login?: string;
  plan?: string;
  tokenBasedBilling?: boolean;
  unlimited?: boolean;
  overagePermitted?: boolean;
  overageCount?: number;
}

function makeSpend(opts: SpendOpts): Spend {
  const {
    consumed,
    entitlement = 300,
    reset = null,
    login = "test-user",
    plan = "business",
    tokenBasedBilling = false,
    unlimited = false,
    overagePermitted = false,
    overageCount = 0,
  } = opts;

  const billable = unlimited ? 0 : Math.max(0, consumed - entitlement);
  const freeLeft = unlimited ? 0 : Math.max(0, entitlement - consumed);
  const unitPrice = tokenBasedBilling ? AI_CREDIT_PRICE_USD : PRU_PRICE_USD;
  return {
    login,
    plan,
    entitlement,
    consumed,
    billablePrus: billable,
    freeRemainingPrus: freeLeft,
    dollarsOwed: round2(billable * unitPrice),
    dollarsEntitlement: round2(Math.max(0, entitlement) * unitPrice),
    dollarsFreeRemaining: round2(freeLeft * unitPrice),
    reset,
    tokenBasedBilling,
    unlimited,
    hasQuota: true,
    overagePermitted,
    overageCount,
  };
}

const NOW = new Date(Date.UTC(2026, 4, 16));

describe("render — PRU mode", () => {
  test("contains required fields under cap R15", () => {
    const out = render(makeSpend({ consumed: 221, reset: new Date(Date.UTC(2026, 4, 31)) }), NOW);

    expect(out).toContain("test-user");
    expect(out).toContain("business");
    expect(out).toContain("221 PRUs");
    expect(out).toContain("$12.00");
    expect(out).toContain("300 PRUs included");
    expect(out).toContain("$3.16");
    expect(out).toContain("79 PRUs of free allowance left");
    expect(out).toContain("May 31, 2026");
  });

  test("contains required fields over cap", () => {
    const out = render(makeSpend({ consumed: 4073, reset: new Date(Date.UTC(2026, 5, 1)) }), NOW);

    expect(out).toContain("test-user");
    expect(out).toContain("business");
    expect(out).toContain("4073 PRUs");
    expect(out).toContain("$150.92");
    expect(out).toContain("3773 PRUs over allowance");
    expect(out).toContain("Jun 01, 2026");
  });

  test("overage renders billable line not remaining line", () => {
    const out = render(makeSpend({ consumed: 400, reset: new Date(Date.UTC(2026, 4, 31)) }), NOW);

    expect(out).toContain("Billable:");
    expect(out).not.toContain("Remaining:");
  });

  test("under cap renders remaining line not billable line", () => {
    const out = render(makeSpend({ consumed: 100, reset: new Date(Date.UTC(2026, 4, 31)) }), NOW);

    expect(out).toContain("Remaining:");
    expect(out).not.toContain("Billable:");
  });

  test("exactly at cap renders remaining with zero", () => {
    const out = render(makeSpend({ consumed: 300, reset: new Date(Date.UTC(2026, 4, 31)) }), NOW);

    expect(out).toContain("Remaining:");
    expect(out).not.toContain("Billable:");
    expect(out).toContain("$0.00");
    expect(out).toContain("0 PRUs of free allowance left");
  });

  test("dollar format always two decimals", () => {
    const out = render(makeSpend({ consumed: 0, reset: new Date(Date.UTC(2026, 4, 31)) }), NOW);

    expect(out).toContain("$12.00");
    expect(out).not.toContain("$12 ");
    expect(out).not.toContain("$12.0 ");
  });
});

describe("render — token-based mode", () => {
  test("uses AI-credit price without PRU label", () => {
    const out = render(
      makeSpend({
        consumed: 154,
        entitlement: 5000,
        reset: new Date(Date.UTC(2026, 6, 1)),
        tokenBasedBilling: true,
      }),
      NOW,
    );

    expect(out).toContain("Billing:   token-based");
    expect(out).toContain("154 AI credits");
    expect(out).toContain("Budget:    $50.00  (5000 AI credits)");
    expect(out).toContain("Remaining: $48.46  (4846 AI credits left)");
    expect(out).not.toContain("AI-credit monthly spend is not available");
    expect(out).not.toContain("PRUs");
  });

  test("overage output shows overage permitted", () => {
    const out = render(
      makeSpend({
        consumed: 5042,
        entitlement: 5000,
        reset: new Date(Date.UTC(2026, 6, 1)),
        tokenBasedBilling: true,
        overagePermitted: true,
        overageCount: 42,
      }),
      NOW,
    );

    expect(out).toContain("Billing:   token-based");
    expect(out).toContain("Used:      5042 AI credits");
    expect(out).toContain("Budget:    $50.00  (5000 AI credits)");
    expect(out).toContain("Billable:  $0.42  (42 AI credits over budget; overage enabled)");
    expect(out).not.toContain("PRUs");
  });

  test("unlimited output has no zero-dollar budget", () => {
    const out = render(
      makeSpend({
        consumed: 0,
        entitlement: 0,
        reset: new Date(Date.UTC(2026, 6, 1)),
        tokenBasedBilling: true,
        unlimited: true,
        overagePermitted: true,
      }),
      NOW,
    );

    expect(out).toContain("Billing:   token-based");
    expect(out).toContain("Used:      0 AI credits");
    expect(out).toContain("Budget:    unlimited");
    expect(out).toContain("Remaining: unlimited");
    expect(out).not.toContain("$0.00");
    expect(out).not.toContain("PRUs");
  });
});

describe("render — reset and labels", () => {
  test("reset none renders unknown R13", () => {
    const out = render(makeSpend({ consumed: 100, reset: null }), NOW);

    expect(out).toContain("next reset: unknown");
    expect(out).not.toContain("2026"); // no leaked date
  });

  test("output is pure ASCII R14", () => {
    const out = render(makeSpend({ consumed: 4073, reset: new Date(Date.UTC(2026, 4, 31)) }), NOW);

    for (const ch of out) {
      expect(ch.codePointAt(0)).toBeLessThan(128);
    }
    expect(out).not.toContain("\x1b"); // no ANSI escape sequences
  });

  test("relative today", () => {
    const reset = new Date(Date.UTC(2026, 4, 16, 23));
    const out = render(makeSpend({ consumed: 100, reset }), NOW);

    expect(out).toContain("today");
  });

  test("relative tomorrow", () => {
    const reset = new Date(Date.UTC(2026, 4, 17));
    const out = render(makeSpend({ consumed: 100, reset }), NOW);

    expect(out).toContain("tomorrow");
  });

  test("relative n days", () => {
    const reset = new Date(Date.UTC(2026, 4, 31));
    const out = render(makeSpend({ consumed: 100, reset }), NOW);

    expect(out).toContain("in 15 days");
  });

  test("overdue relative", () => {
    const reset = new Date(Date.UTC(2026, 4, 13));
    const out = render(makeSpend({ consumed: 100, reset }), NOW);

    expect(out).toContain("overdue");
  });

  test("missing login renders unknown-account label", () => {
    const out = render(makeSpend({ consumed: 100, login: "", reset: null }), NOW);

    expect(out).toContain("<unknown account>");
  });

  test("missing plan renders no plan suffix", () => {
    const out = render(makeSpend({ consumed: 100, plan: "", reset: null }), NOW);

    expect(out).toContain("GitHub Copilot - test-user");
    expect(out).not.toContain("()"); // no empty parens for missing plan
  });
});

describe("renderJson", () => {
  test("returns valid parseable JSON object", () => {
    const out = renderJson(makeSpend({ consumed: 221, reset: new Date(Date.UTC(2026, 4, 31)) }));

    const parsed = JSON.parse(out);
    expect(typeof parsed).toBe("object");
    expect(parsed).not.toBeNull();
  });

  test("includes all documented fields", () => {
    const parsed = JSON.parse(
      renderJson(makeSpend({ consumed: 4073, reset: new Date(Date.UTC(2026, 4, 31)) })),
    );

    expect(parsed.login).toBe("test-user");
    expect(parsed.plan).toBe("business");
    expect(parsed.entitlement_prus).toBe(300);
    expect(parsed.consumed_prus).toBe(4073);
    expect(parsed.billable_prus).toBe(3773);
    expect(parsed.free_remaining_prus).toBe(0);
    expect(parsed.dollars_owed).toBe(150.92);
    expect(parsed.dollars_entitlement).toBe(12.0);
    expect(parsed.dollars_free_remaining).toBe(0.0);
    expect(parsed.pru_price_usd).toBe(PRU_PRICE_USD);
    expect(parsed.reset).toBe("2026-05-31T00:00:00+00:00");
  });

  test("token-based billing marks AI-credit bucket", () => {
    const parsed = JSON.parse(
      renderJson(makeSpend({ consumed: 154, entitlement: 5000, tokenBasedBilling: true })),
    );

    expect(parsed.billing_model).toBe("token_based");
    expect(parsed.token_based_billing).toBe(true);
    expect(parsed.legacy_entitlement_premium_interactions).toBe(5000);
    expect(parsed.legacy_consumed_premium_interactions).toBe(154);
    expect(parsed.legacy_remaining_premium_interactions).toBe(4846);
    expect(parsed.ai_credit_monthly_spend_available).toBe(false);
    expect(parsed.legacy_overage_permitted).toBe(false);
    expect(parsed.legacy_overage_premium_interactions).toBe(0);
    expect(parsed.legacy_unlimited).toBe(false);
    expect(parsed.ai_credit_price_usd).toBe(AI_CREDIT_PRICE_USD);
    expect(parsed.included_ai_credits).toBe(5000);
    expect(parsed.used_ai_credits).toBe(154);
    expect(parsed.remaining_ai_credits).toBe(4846);
    expect(parsed.billable_ai_credits).toBe(0);
    expect(parsed.dollars_entitlement).toBe(50.0);
    expect(parsed.dollars_free_remaining).toBe(48.46);
    expect(parsed.dollars_owed).toBe(0.0);
    expect(parsed.pru_price_usd).toBeNull();
  });

  test("token-based unlimited clamps included AI credits", () => {
    const parsed = JSON.parse(
      renderJson(
        makeSpend({ consumed: 0, entitlement: -1, tokenBasedBilling: true, unlimited: true }),
      ),
    );

    expect(parsed.legacy_unlimited).toBe(true);
    expect(parsed.legacy_entitlement_premium_interactions).toBe(-1);
    expect(parsed.included_ai_credits).toBe(0);
    expect(parsed.remaining_ai_credits).toBeNull();
  });

  test("reset none serializes as null", () => {
    const parsed = JSON.parse(renderJson(makeSpend({ consumed: 100, reset: null })));

    expect(parsed.reset).toBeNull();
  });

  test("keys sorted for stable diffs", () => {
    const parsed = JSON.parse(renderJson(makeSpend({ consumed: 100, reset: null })));

    const keys = Object.keys(parsed);
    expect(keys).toEqual([...keys].sort());
  });
});
