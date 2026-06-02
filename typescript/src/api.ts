import type { Auth } from "./auth";
import { APIError, NoSubscriptionError } from "./errors";
import { scrub } from "./paths";
import { packageVersion } from "./version";

export { APIError } from "./errors";

// A single retry covers the common transient-5xx case (load-balancer hiccup,
// brief overload) without compounding latency or hammering an already-sick
// upstream. 0.5s gives the backend time to recover without making the user
// feel the tool froze.
const RETRY_BACKOFF_S = 0.5;

function buildUrl(host: string): string {
  if (host === "github.com") {
    return "https://api.github.com/copilot_internal/user";
  }
  return `https://${host}/api/v3/copilot_internal/user`;
}

function bodyExcerpt(raw: string, limit = 500): string {
  let text = raw.trim();
  if (text.length > limit) {
    text = `${text.slice(0, limit)}…`;
  }
  return text;
}

function reauthMessage(source: string): string {
  if (source === "native") {
    return "Token rejected by GitHub Copilot. Run `copilot-spend login` to re-authenticate.";
  }
  return (
    "Token rejected by GitHub Copilot — opencode token may be expired. " +
    "Run `opencode login` to refresh."
  );
}

function isTimeout(exc: unknown): boolean {
  return exc instanceof Error && (exc.name === "TimeoutError" || exc.name === "AbortError");
}

function defaultSleep(seconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, seconds * 1000));
}

function parseBody(raw: string, url: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (exc) {
    const reason = exc instanceof Error ? exc.message : String(exc);
    throw new APIError(`GitHub Copilot API at ${url} returned a non-JSON response: ${reason}`);
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new APIError(`GitHub Copilot API at ${url} returned non-object JSON.`);
  }
  return parsed as Record<string, unknown>;
}

export interface FetchQuotaOptions {
  /** Per-request timeout in seconds. */
  timeout?: number;
  /** Injectable backoff sleep (seconds) for deterministic tests. */
  sleep?: (seconds: number) => Promise<void>;
  /** Injectable fetch implementation for tests — the exact shape fetchQuota uses. */
  fetchImpl?: (url: string, init: RequestInit) => Promise<Response>;
}

export async function fetchQuota(
  auth: Auth,
  options: FetchQuotaOptions = {},
): Promise<Record<string, unknown>> {
  const timeout = options.timeout ?? 10.0;
  const sleep = options.sleep ?? defaultSleep;
  const fetchImpl = options.fetchImpl ?? fetch;

  // `/copilot_internal/user` accepts the OAuth/GitHub-App user token directly
  // as Bearer for both `ghu_` (native) and `gho_` (opencode). No session-token
  // exchange — that token (`/copilot_internal/v2/token`) is for the Copilot
  // Chat proxy at api.githubcopilot.com, not this endpoint.
  const url = buildUrl(auth.host);
  const headers: Record<string, string> = {
    Authorization: `Bearer ${auth.token}`,
    "User-Agent": `copilot-spend/${packageVersion()}`,
    Accept: "application/json",
  };

  // One retry on transient 5xx. Anything else (401/403/404/4xx) fails fast.
  for (let attempt = 0; ; attempt++) {
    let response: Response;
    try {
      response = await fetchImpl(url, {
        method: "GET",
        headers,
        signal: AbortSignal.timeout(timeout * 1000),
      });
    } catch (exc) {
      if (isTimeout(exc)) {
        throw new APIError(`Request to ${auth.host} timed out after ${timeout}s.`);
      }
      const reason = exc instanceof Error ? exc.message : String(exc);
      throw new APIError(`Could not reach ${auth.host}: ${reason}`);
    }

    const status = response.status;
    if (status >= 200 && status < 300) {
      return parseBody(await response.text(), url);
    }
    if (status === 401 || status === 403) {
      throw new APIError(reauthMessage(auth.source));
    }
    if (status === 404) {
      throw new NoSubscriptionError("No Copilot quota on this account.");
    }
    if (status >= 500 && status < 600) {
      if (attempt === 0) {
        await sleep(RETRY_BACKOFF_S);
        continue;
      }
      // Retry already spent; this message omits the body, so don't read it.
      throw new APIError(`GitHub Copilot API returned ${status} at ${url} — try again shortly.`);
    }

    let body: string;
    try {
      body = scrub(bodyExcerpt(await response.text()), auth.token);
    } catch {
      body = "<no response body>";
    }
    throw new APIError(`GitHub Copilot API returned ${status} at ${url}: ${body}`);
  }
}
