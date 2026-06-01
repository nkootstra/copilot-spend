import { NoSubscriptionError } from "./errors";

// Published GitHub Copilot premium request unit price as of 2026-05.
// Update this constant if GitHub changes the rate.
export const PRU_PRICE_USD = 0.04;

// Published GitHub Copilot AI credit price as of 2026-06.
export const AI_CREDIT_PRICE_USD = 0.01;

// Plausible field names for the next-reset timestamp. Searched at the payload
// top level first, then inside `quota_snapshots.premium_interactions`. The
// endpoint is undocumented; live observation (2026-05) shows `quota_reset_date`
// at the top level with a date-only string. The other names are defensive
// fallbacks in case GitHub renames or relocates the field.
export const RESET_FIELD_CANDIDATES = [
  "quota_reset_date",
  "next_reset",
  "reset_date",
  "resets_at",
  "reset",
  "next_reset_date",
] as const;

// Nested paths inside `premium_interactions` to search when no flat candidate
// matches. Each path is a list of keys to walk.
export const RESET_NESTED_PATHS = [
  ["reset", "date"],
  ["reset", "at"],
  ["next", "reset"],
] as const;

export interface Spend {
  login: string;
  plan: string;
  entitlement: number; // included free units per period
  consumed: number; // total units used this period (>= 0)
  billablePrus: number; // max(0, consumed - entitlement)
  freeRemainingPrus: number; // max(0, entitlement - consumed)
  dollarsOwed: number;
  dollarsEntitlement: number;
  dollarsFreeRemaining: number;
  reset: Date | null;
  tokenBasedBilling: boolean;
  unlimited: boolean;
  hasQuota: boolean;
  overagePermitted: boolean;
  overageCount: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const DATE_ONLY_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const DATE_TIME_RE =
  /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?$/;

/**
 * Parse an ISO-8601 date or datetime into a UTC `Date`, or `null` if the value
 * is not a recognizable timestamp. Date-only strings and offset-less datetimes
 * are anchored to UTC, mirroring the Python `_parse_iso` behavior so downstream
 * comparisons stay consistent.
 */
function parseIso(value: unknown): Date | null {
  if (typeof value !== "string" || !value) {
    return null;
  }

  const dateOnly = DATE_ONLY_RE.exec(value);
  if (dateOnly) {
    const [, y, m, d] = dateOnly;
    const dt = new Date(Date.UTC(Number(y), Number(m) - 1, Number(d)));
    return Number.isNaN(dt.getTime()) ? null : dt;
  }

  const match = DATE_TIME_RE.exec(value);
  if (!match) {
    return null;
  }
  const [, y, mo, d, h, mi, s, offset] = match;
  let ms = Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s));
  if (offset && offset !== "Z") {
    const sign = offset.startsWith("-") ? -1 : 1;
    const digits = offset.slice(1).replace(":", "");
    const offsetMinutes = Number(digits.slice(0, 2)) * 60 + Number(digits.slice(2, 4));
    ms -= sign * offsetMinutes * 60_000;
  }
  const dt = new Date(ms);
  return Number.isNaN(dt.getTime()) ? null : dt;
}

/** Coerce to a non-negative integer, falling back to `fallback` on garbage. */
function parseNonnegativeInt(value: unknown, fallback = 0): number {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return fallback;
  }
  return Math.max(0, Math.trunc(n));
}

/** Strict integer coercion; throws on missing/non-numeric input. */
function toInt(value: unknown): number {
  if (value === undefined || value === null || value === "") {
    throw new TypeError("missing");
  }
  const n = Number(value);
  if (!Number.isFinite(n)) {
    throw new TypeError("not a number");
  }
  return Math.trunc(n);
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

function extractReset(payload: Record<string, unknown>, pi: Record<string, unknown>): Date | null {
  for (const source of [payload, pi]) {
    for (const name of RESET_FIELD_CANDIDATES) {
      if (name in source) {
        const parsed = parseIso(source[name]);
        if (parsed !== null) {
          return parsed;
        }
      }
    }
  }

  for (const path of RESET_NESTED_PATHS) {
    let cursor: unknown = pi;
    for (const key of path) {
      if (isRecord(cursor) && key in cursor) {
        cursor = cursor[key];
      } else {
        cursor = null;
        break;
      }
    }
    const parsed = parseIso(cursor);
    if (parsed !== null) {
      return parsed;
    }
  }

  if (process.env.COPILOT_SPEND_DEBUG === "1") {
    const topKeys = Object.keys(payload).sort();
    const piKeys = Object.keys(pi).sort();
    process.stderr.write(
      `debug: no reset-date field found. Tried top-level=${JSON.stringify([...RESET_FIELD_CANDIDATES])} and premium_interactions nested paths=${JSON.stringify(RESET_NESTED_PATHS.map((p) => [...p]))}. Payload top-level keys=${JSON.stringify(topKeys)}. premium_interactions keys=${JSON.stringify(piKeys)}. If GitHub renamed the field, add the new name to RESET_FIELD_CANDIDATES.\n`,
    );
  }
  return null;
}

export function parseQuota(payload: Record<string, unknown>): Spend {
  const planRaw = payload.copilot_plan;
  const snapshots = payload.quota_snapshots;
  const pi = isRecord(snapshots) ? snapshots.premium_interactions : undefined;

  // Origin R7: missing copilot_plan OR missing premium_interactions → no subscription.
  if (!planRaw || !isRecord(pi)) {
    throw new NoSubscriptionError("No Copilot quota on this account.");
  }

  let entitlement: number;
  let remaining: number;
  try {
    entitlement = toInt(pi.entitlement);
    remaining = toInt(pi.remaining);
  } catch (exc) {
    const reason = exc instanceof Error ? exc.message : String(exc);
    throw new NoSubscriptionError(`premium_interactions missing entitlement/remaining: ${reason}`);
  }

  const tokenBasedBilling = payload.token_based_billing === true;
  const unlimited = pi.unlimited === true || entitlement < 0;
  const hasQuota = typeof pi.has_quota === "boolean" ? pi.has_quota : true;
  const overagePermitted = pi.overage_permitted === true;
  const overageCount = parseNonnegativeInt(pi.overage_count);

  // Legacy responses observed `remaining <= 0`, where consumption was
  // represented by the negative remainder. Token-based billing responses now
  // expose a positive countdown from entitlement instead.
  let consumed: number;
  if (unlimited) {
    consumed = overageCount;
  } else if (tokenBasedBilling && remaining >= 0) {
    consumed = Math.max(0, entitlement - remaining) + overageCount;
  } else if (tokenBasedBilling) {
    consumed = Math.max(0, -remaining) + overageCount;
  } else {
    consumed = Math.max(0, -remaining);
  }
  const billablePrus = unlimited ? 0 : Math.max(0, consumed - entitlement, overageCount);
  const freeRemainingPrus = unlimited ? 0 : Math.max(0, entitlement - consumed);

  const unitPrice = tokenBasedBilling ? AI_CREDIT_PRICE_USD : PRU_PRICE_USD;
  const dollarsOwed = round2(billablePrus * unitPrice);
  const dollarsEntitlement = round2(Math.max(0, entitlement) * unitPrice);
  const dollarsFreeRemaining = round2(freeRemainingPrus * unitPrice);

  const reset = extractReset(payload, pi);

  const loginRaw = payload.login;
  const login = typeof loginRaw === "string" ? loginRaw : "";
  const plan = typeof planRaw === "string" ? planRaw : "";

  return {
    login,
    plan,
    entitlement,
    consumed,
    billablePrus,
    freeRemainingPrus,
    dollarsOwed,
    dollarsEntitlement,
    dollarsFreeRemaining,
    reset,
    tokenBasedBilling,
    unlimited,
    hasQuota,
    overagePermitted,
    overageCount,
  };
}
