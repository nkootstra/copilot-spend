import { afterEach, beforeEach, describe, expect, spyOn, test } from "bun:test";
import { NoSubscriptionError } from "../src/errors";
import { AI_CREDIT_PRICE_USD, PRU_PRICE_USD, parseQuota } from "../src/quota";
import { isolateEnv } from "./helpers";

interface PayloadOpts {
  entitlement: number;
  remaining: number;
  resetField?: string;
  resetValue?: string | null;
  plan?: string;
  login?: string;
  nestedReset?: Record<string, unknown>;
  tokenBasedBilling?: boolean;
  snapshotFields?: Record<string, unknown>;
}

function payload(opts: PayloadOpts): Record<string, unknown> {
  const {
    entitlement,
    remaining,
    resetField = "next_reset",
    resetValue = "2026-05-31T00:00:00Z",
    plan = "business",
    login = "u",
    nestedReset,
    tokenBasedBilling,
    snapshotFields,
  } = opts;

  const pi: Record<string, unknown> = { entitlement, remaining };
  if (resetValue !== null) {
    pi[resetField] = resetValue;
  }
  if (nestedReset) {
    Object.assign(pi, nestedReset);
  }
  if (snapshotFields) {
    Object.assign(pi, snapshotFields);
  }
  const result: Record<string, unknown> = {
    login,
    copilot_plan: plan,
    quota_snapshots: { premium_interactions: pi },
  };
  if (tokenBasedBilling !== undefined) {
    result.token_based_billing = tokenBasedBilling;
  }
  return result;
}

let restoreEnv: () => void;

beforeEach(() => {
  restoreEnv = isolateEnv(["COPILOT_SPEND_DEBUG"]);
});

afterEach(() => {
  restoreEnv();
});

describe("PRU math", () => {
  test("overage math AE3: 4073 consumed under 300 allowance → 3773 billable", () => {
    const spend = parseQuota(payload({ entitlement: 300, remaining: -4073 }));

    expect(spend.entitlement).toBe(300);
    expect(spend.consumed).toBe(4073);
    expect(spend.billablePrus).toBe(3773);
    expect(spend.freeRemainingPrus).toBe(0);
    expect(spend.dollarsOwed).toBe(150.92);
    expect(spend.dollarsEntitlement).toBe(12.0);
    expect(spend.dollarsFreeRemaining).toBe(0.0);
  });

  test("normal math AE4: 221 consumed under 300 allowance → 79 free left", () => {
    const spend = parseQuota(payload({ entitlement: 300, remaining: -221 }));

    expect(spend.consumed).toBe(221);
    expect(spend.billablePrus).toBe(0);
    expect(spend.freeRemainingPrus).toBe(79);
    expect(spend.dollarsOwed).toBe(0.0);
    expect(spend.dollarsEntitlement).toBe(12.0);
    expect(spend.dollarsFreeRemaining).toBe(3.16);
  });

  test("consumption exactly at allowance", () => {
    const spend = parseQuota(payload({ entitlement: 300, remaining: -300 }));

    expect(spend.consumed).toBe(300);
    expect(spend.billablePrus).toBe(0);
    expect(spend.freeRemainingPrus).toBe(0);
    expect(spend.dollarsOwed).toBe(0.0);
    expect(spend.dollarsFreeRemaining).toBe(0.0);
  });

  test("zero consumption", () => {
    const spend = parseQuota(payload({ entitlement: 300, remaining: 0 }));

    expect(spend.consumed).toBe(0);
    expect(spend.billablePrus).toBe(0);
    expect(spend.freeRemainingPrus).toBe(300);
    expect(spend.dollarsOwed).toBe(0.0);
    expect(spend.dollarsFreeRemaining).toBe(12.0);
  });

  test("positive remaining treated as zero consumption", () => {
    const spend = parseQuota(payload({ entitlement: 300, remaining: 79 }));

    expect(spend.consumed).toBe(0);
    expect(spend.billablePrus).toBe(0);
    expect(spend.freeRemainingPrus).toBe(300);
  });
});

describe("token-based billing", () => {
  test("positive remaining counts down from entitlement", () => {
    const spend = parseQuota(
      payload({ entitlement: 5000, remaining: 4846, tokenBasedBilling: true }),
    );

    expect(spend.tokenBasedBilling).toBe(true);
    expect(spend.consumed).toBe(154);
    expect(spend.billablePrus).toBe(0);
    expect(spend.freeRemainingPrus).toBe(4846);
    expect(spend.dollarsEntitlement).toBe(50.0);
    expect(spend.dollarsFreeRemaining).toBe(48.46);
  });

  test("overage_count counts as billable usage", () => {
    const spend = parseQuota(
      payload({
        entitlement: 5000,
        remaining: 0,
        tokenBasedBilling: true,
        snapshotFields: { overage_count: 42, overage_permitted: true },
      }),
    );

    expect(spend.overagePermitted).toBe(true);
    expect(spend.overageCount).toBe(42);
    expect(spend.consumed).toBe(5042);
    expect(spend.billablePrus).toBe(42);
    expect(spend.freeRemainingPrus).toBe(0);
    expect(spend.dollarsOwed).toBe(0.42);
  });

  test("unlimited snapshot has no legacy budget", () => {
    const spend = parseQuota(
      payload({
        entitlement: 0,
        remaining: 0,
        tokenBasedBilling: true,
        snapshotFields: { unlimited: true, has_quota: true, overage_permitted: true },
      }),
    );

    expect(spend.unlimited).toBe(true);
    expect(spend.hasQuota).toBe(true);
    expect(spend.overagePermitted).toBe(true);
    expect(spend.consumed).toBe(0);
    expect(spend.billablePrus).toBe(0);
    expect(spend.freeRemainingPrus).toBe(0);
    expect(spend.dollarsEntitlement).toBe(0.0);
  });

  test("unlimited negative entitlement clamps budget dollars", () => {
    const spend = parseQuota(
      payload({
        entitlement: -1,
        remaining: 0,
        tokenBasedBilling: true,
        snapshotFields: { has_quota: true, overage_permitted: true },
      }),
    );

    expect(spend.unlimited).toBe(true);
    expect(spend.entitlement).toBe(-1);
    expect(spend.dollarsEntitlement).toBe(0.0);
  });

  test("negative remaining fallback includes overage_count", () => {
    const spend = parseQuota(
      payload({
        entitlement: 5000,
        remaining: -100,
        tokenBasedBilling: true,
        snapshotFields: { overage_count: 42, overage_permitted: true },
      }),
    );

    expect(spend.consumed).toBe(142);
    expect(spend.billablePrus).toBe(42);
    expect(spend.freeRemainingPrus).toBe(4858);
    expect(spend.dollarsOwed).toBe(0.42);
  });
});

describe("reset parsing", () => {
  test("parses ISO-8601 with Z suffix", () => {
    const spend = parseQuota(
      payload({ entitlement: 300, remaining: -100, resetValue: "2026-05-31T00:00:00Z" }),
    );

    expect(spend.reset).not.toBeNull();
    expect(spend.reset?.getTime()).toBe(Date.UTC(2026, 4, 31));
  });

  test("parses ISO-8601 with explicit offset", () => {
    const spend = parseQuota(
      payload({ entitlement: 300, remaining: -100, resetValue: "2026-05-31T12:00:00+00:00" }),
    );

    expect(spend.reset).not.toBeNull();
  });

  test("uses second candidate when first absent", () => {
    const spend = parseQuota(
      payload({ entitlement: 300, remaining: -100, resetField: "reset_date" }),
    );

    expect(spend.reset).not.toBeNull();
  });

  test("uses third candidate when first two absent", () => {
    const spend = parseQuota(
      payload({ entitlement: 300, remaining: -100, resetField: "resets_at" }),
    );

    expect(spend.reset).not.toBeNull();
  });

  test("finds top-level quota_reset_date", () => {
    const p = payload({ entitlement: 300, remaining: -100, resetValue: null });
    p.quota_reset_date = "2026-06-01";

    const spend = parseQuota(p);

    expect(spend.reset?.getTime()).toBe(Date.UTC(2026, 5, 1));
  });

  test("date-only string attaches UTC", () => {
    const spend = parseQuota(
      payload({ entitlement: 300, remaining: -100, resetValue: "2026-05-31" }),
    );

    expect(spend.reset?.getTime()).toBe(Date.UTC(2026, 4, 31));
  });

  test("finds nested reset.date", () => {
    const spend = parseQuota(
      payload({
        entitlement: 300,
        remaining: -100,
        resetValue: null,
        nestedReset: { reset: { date: "2026-05-31T00:00:00Z" } },
      }),
    );

    expect(spend.reset).not.toBeNull();
  });

  test("missing reset returns null AE5", () => {
    const spend = parseQuota(payload({ entitlement: 300, remaining: -100, resetValue: null }));

    expect(spend.reset).toBeNull();
  });

  test("non-ISO reset returns null", () => {
    const spend = parseQuota(
      payload({ entitlement: 300, remaining: -100, resetValue: "next-tuesday" }),
    );

    expect(spend.reset).toBeNull();
  });

  test("reset miss is silent without debug env", () => {
    // `beforeEach` already cleared COPILOT_SPEND_DEBUG; assert the silent path.
    const writeSpy = spyOn(process.stderr, "write").mockReturnValue(true);

    parseQuota(payload({ entitlement: 300, remaining: -100, resetValue: null }));

    expect(writeSpy).not.toHaveBeenCalled();
    writeSpy.mockRestore();
  });

  test("reset miss emits diagnostic under debug env", () => {
    process.env.COPILOT_SPEND_DEBUG = "1";
    const writeSpy = spyOn(process.stderr, "write").mockReturnValue(true);

    parseQuota(payload({ entitlement: 300, remaining: -100, resetValue: null }));

    const err = writeSpy.mock.calls.map((call) => String(call[0])).join("");
    expect(err).toContain("reset-date");
    expect(err).toContain("quota_reset_date");
    expect(err).toContain("premium_interactions keys");
    writeSpy.mockRestore();
  });
});

describe("subscription gating", () => {
  test("missing premium_interactions raises AE7", () => {
    const p = { login: "u", copilot_plan: "business", quota_snapshots: {} };

    expect(() => parseQuota(p)).toThrow(NoSubscriptionError);
  });

  test("null premium_interactions raises", () => {
    const p = {
      login: "u",
      copilot_plan: "business",
      quota_snapshots: { premium_interactions: null },
    };

    expect(() => parseQuota(p)).toThrow(NoSubscriptionError);
  });

  test("missing copilot_plan raises", () => {
    const p = {
      login: "u",
      quota_snapshots: { premium_interactions: { entitlement: 300, remaining: -100 } },
    };

    expect(() => parseQuota(p)).toThrow(NoSubscriptionError);
  });

  test("empty quota_snapshots raises", () => {
    const p = { login: "u", copilot_plan: "business" };

    expect(() => parseQuota(p)).toThrow(NoSubscriptionError);
  });

  test("premium_interactions missing entitlement raises", () => {
    const p = {
      login: "u",
      copilot_plan: "business",
      quota_snapshots: { premium_interactions: { remaining: -100 } },
    };

    expect(() => parseQuota(p)).toThrow(NoSubscriptionError);
  });

  test("non-numeric entitlement raises", () => {
    const p = {
      login: "u",
      copilot_plan: "business",
      quota_snapshots: { premium_interactions: { entitlement: "lots", remaining: -100 } },
    };

    expect(() => parseQuota(p)).toThrow(NoSubscriptionError);
  });
});

describe("login and plan", () => {
  test("login and plan populated", () => {
    const spend = parseQuota(
      payload({ entitlement: 300, remaining: -100, plan: "business", login: "test-user" }),
    );

    expect(spend.login).toBe("test-user");
    expect(spend.plan).toBe("business");
  });

  test("missing login becomes empty string", () => {
    const p = {
      copilot_plan: "business",
      quota_snapshots: { premium_interactions: { entitlement: 300, remaining: -100 } },
    };

    const spend = parseQuota(p);

    expect(spend.login).toBe("");
  });
});

describe("price constants", () => {
  test("PRU price is 4 cents", () => {
    expect(PRU_PRICE_USD).toBe(0.04);
  });

  test("AI credit price is 1 cent", () => {
    expect(AI_CREDIT_PRICE_USD).toBe(0.01);
  });
});
