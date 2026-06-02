import { existsSync } from "node:fs";
import { join } from "node:path";
import { createInterface } from "node:readline";
import { fetchQuota } from "./api";
import { Auth, isValidHost, normalizeHost } from "./auth";
import { APIError, AuthError, NoSubscriptionError } from "./errors";
import { authPath, configDir, deleteSecretFile, scrub, writeSecretFile } from "./paths";

export { AuthError } from "./errors";

// Bundled GitHub App client id (public; device flow needs no secret). Mirrors
// the Python package so a token minted by either CLI is interchangeable.
export const CLIENT_ID = "Iv1.b507a08c87ecfe98";
export const OAUTH_SCOPE = "read:user";
export const POLL_MAX_WAIT_S = 900;

/**
 * Transport errors surfaced by {@link PostJson}. Python distinguishes
 * `urllib.error.HTTPError` / `TimeoutError` / `urllib.error.URLError`; these
 * classes give the device-flow callers the same three branches to switch on.
 */
export class LoginHttpError extends Error {
  readonly status: number;
  readonly body: string;
  constructor(status: number, body: string) {
    super(`GitHub returned HTTP ${status}`);
    this.name = "LoginHttpError";
    this.status = status;
    this.body = body;
  }
}

export class LoginTimeoutError extends Error {
  constructor(message = "request timed out") {
    super(message);
    this.name = "LoginTimeoutError";
  }
}

export class LoginNetworkError extends Error {
  readonly reason: string;
  constructor(reason: string) {
    super(reason);
    this.name = "LoginNetworkError";
    this.reason = reason;
  }
}

/** Raised when the user interrupts (Ctrl-C) while polling — Python's KeyboardInterrupt analogue. */
export class LoginCancelledError extends Error {
  constructor() {
    super("Login cancelled.");
    this.name = "LoginCancelledError";
  }
}

/** POSTs JSON and returns the parsed object, or throws a Login*Error on transport failure. */
export type PostJson = (
  url: string,
  body: Record<string, unknown>,
  timeout?: number,
) => Promise<Record<string, unknown>>;

export async function defaultPostJson(
  url: string,
  body: Record<string, unknown>,
  timeout = 10.0,
  fetchImpl: typeof fetch = fetch,
): Promise<Record<string, unknown>> {
  let response: Response;
  try {
    response = await fetchImpl(url, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(timeout * 1000),
    });
  } catch (exc) {
    if (exc instanceof Error && (exc.name === "TimeoutError" || exc.name === "AbortError")) {
      throw new LoginTimeoutError();
    }
    throw new LoginNetworkError(exc instanceof Error ? exc.message : String(exc));
  }

  const text = await response.text();
  if (response.status < 200 || response.status >= 300) {
    throw new LoginHttpError(response.status, text);
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    parsed = null;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new AuthError(`Non-object JSON response from ${url}.`);
  }
  return parsed as Record<string, unknown>;
}

function deviceUrl(host: string): string {
  return `https://${host}/login/device/code`;
}

function accessTokenUrl(host: string): string {
  return `https://${host}/login/oauth/access_token`;
}

/** Truncate to `limit` chars, appending an ellipsis when shortened. */
function truncate(text: string, limit: number): string {
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

/**
 * Extract a human-readable description from an error-response body.
 *
 * GitHub device-flow endpoints return `{"error": "...", "error_description": "..."}`
 * even on 4xx — surfacing that turns a bare "GitHub returned 422" into a
 * diagnosable message.
 */
function httpErrorDetail(body: string, limit = 300): string {
  if (!body) {
    return "";
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return truncate(body.trim(), limit);
  }
  if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
    const obj = parsed as Record<string, unknown>;
    const err = obj.error;
    const desc = obj.error_description;
    if (err && desc) {
      return `${String(err)}: ${String(desc)}`;
    }
    if (err) {
      return String(err);
    }
    if (desc) {
      return String(desc);
    }
  }
  return truncate(JSON.stringify(parsed), limit);
}

type LineReader = () => string | Promise<string>;
type Writer = (text: string) => void;

async function promptHost(readLine: LineReader, err: Writer): Promise<string> {
  err("Where do you authenticate?\n");
  err("  1) github.com\n");
  err("  2) GitHub Enterprise\n");
  err("Choose 1 or 2 [1]: ");
  const choice = (await readLine()).trim() || "1";

  if (choice === "1") {
    return "github.com";
  }
  if (choice !== "2") {
    throw new AuthError(`Unrecognized choice: ${JSON.stringify(choice)}. Expected 1 or 2.`);
  }

  err("GHE host (e.g. ghe.example.com): ");
  const raw = (await readLine()).trim();
  const host = normalizeHost(raw);
  if (!isValidHost(host)) {
    throw new AuthError(
      `Not a valid hostname: ${JSON.stringify(raw)}. Expected a bare hostname like \`ghe.example.com\`.`,
    );
  }
  return host;
}

async function requestDeviceCode(
  host: string,
  postJson: PostJson,
): Promise<Record<string, unknown>> {
  const url = deviceUrl(host);
  let payload: Record<string, unknown>;
  try {
    payload = await postJson(url, { client_id: CLIENT_ID, scope: OAUTH_SCOPE });
  } catch (exc) {
    if (exc instanceof LoginHttpError) {
      const detail = httpErrorDetail(exc.body);
      const suffix = detail ? `: ${detail}` : ". Check the host and try again.";
      throw new AuthError(`GitHub returned ${exc.status} from ${url}${suffix}`);
    }
    if (exc instanceof LoginTimeoutError) {
      throw new AuthError(`Timed out reaching ${host} for device-code request.`);
    }
    if (exc instanceof LoginNetworkError) {
      throw new AuthError(`Could not reach '${host}': ${exc.reason}.`);
    }
    throw exc;
  }

  const error = payload.error;
  if (error) {
    const description = payload.error_description ?? error;
    throw new AuthError(
      `GitHub rejected the device-code request (${String(error)}): ${String(description)}.`,
    );
  }

  const required = ["device_code", "user_code", "verification_uri", "interval"];
  if (!required.every((key) => payload[key])) {
    throw new AuthError(`Device-code response from ${url} is missing required fields.`);
  }
  return payload;
}

interface PollOptions {
  now: () => number;
  sleep: (seconds: number) => void | Promise<void>;
  postJson: PostJson;
  maxWait?: number;
}

async function pollForToken(
  host: string,
  deviceCode: string,
  interval: number,
  options: PollOptions,
): Promise<string> {
  const { now, sleep, postJson, maxWait = POLL_MAX_WAIT_S } = options;
  const url = accessTokenUrl(host);
  const body = {
    client_id: CLIENT_ID,
    device_code: deviceCode,
    grant_type: "urn:ietf:params:oauth:grant-type:device_code",
  };
  const started = now();
  let currentInterval = Math.max(Math.trunc(interval), 1);

  for (;;) {
    if (now() - started > maxWait) {
      throw new AuthError("Login timed out. Run `copilot-spend login` again.");
    }

    await sleep(currentInterval);

    let payload: Record<string, unknown>;
    try {
      payload = await postJson(url, body);
    } catch (exc) {
      if (exc instanceof LoginHttpError) {
        const detail = httpErrorDetail(exc.body);
        const suffix = detail ? `: ${detail}` : ". Run `copilot-spend login` again.";
        throw new AuthError(`GitHub returned ${exc.status} during token polling${suffix}`);
      }
      if (exc instanceof LoginTimeoutError) {
        // Transient — keep polling within the time budget.
        continue;
      }
      if (exc instanceof LoginNetworkError) {
        throw new AuthError(`Could not reach '${host}': ${exc.reason}.`);
      }
      throw exc;
    }

    const token = payload.access_token;
    if (token) {
      if (typeof token !== "string") {
        throw new AuthError("GitHub returned a non-string access_token.");
      }
      return token;
    }

    const err = payload.error;
    if (err === "authorization_pending") {
      continue;
    }
    if (err === "slow_down") {
      currentInterval += 5;
      continue;
    }
    if (err === "expired_token") {
      throw new AuthError("Login timed out. Run `copilot-spend login` again.");
    }
    if (err === "access_denied") {
      throw new AuthError("Authorization denied. Run `copilot-spend login` again to retry.");
    }
    if (err === "unauthorized_client") {
      throw new AuthError(
        "GitHub rejected the OAuth app (unauthorized_client). " +
          "The bundled CLIENT_ID may not be allowed on this host. " +
          "See README 'Switch to your own GitHub App'.",
      );
    }
    if (err) {
      const description = payload.error_description ?? err;
      throw new AuthError(
        `GitHub returned an error during polling (${String(err)}): ${String(description)}.`,
      );
    }

    throw new AuthError("Token response missing both access_token and error.");
  }
}

/** A sleep that rejects with {@link LoginCancelledError} if the user hits Ctrl-C mid-wait. */
export function interruptibleSleep(seconds: number): Promise<void> {
  return new Promise((resolve, reject) => {
    function cleanup(): void {
      clearTimeout(timer);
      process.removeListener("SIGINT", onSigint);
    }
    function onSigint(): void {
      cleanup();
      reject(new LoginCancelledError());
    }
    const timer = setTimeout(() => {
      cleanup();
      resolve();
    }, seconds * 1000);
    process.on("SIGINT", onSigint);
  });
}

interface StdinReader {
  readLine: LineReader;
  close: () => void;
}

export function createStdinReader(input: NodeJS.ReadableStream = process.stdin): StdinReader {
  const rl = createInterface({ input });
  const iterator = rl[Symbol.asyncIterator]();
  return {
    readLine: async () => {
      const { value, done } = await iterator.next();
      return done ? "" : (value as string);
    },
    close: () => rl.close(),
  };
}

export interface RunLoginOptions {
  /** Reads one line from the user (without trailing newline); injectable for tests. */
  readLine?: LineReader;
  stdout?: Writer;
  stderr?: Writer;
  sleep?: (seconds: number) => void | Promise<void>;
  /** Monotonic clock in seconds; injectable for deterministic timeout tests. */
  now?: () => number;
  /** HTTP POST transport; injectable for tests. */
  postJson?: PostJson;
  /** Post-login verification call; defaults to the real {@link fetchQuota}. */
  fetchQuotaImpl?: (auth: Auth) => Promise<unknown>;
}

export async function runLogin(options: RunLoginOptions = {}): Promise<number> {
  const out: Writer = options.stdout ?? ((text) => void process.stdout.write(text));
  const err: Writer = options.stderr ?? ((text) => void process.stderr.write(text));
  const sleep = options.sleep ?? interruptibleSleep;
  const now = options.now ?? (() => Number(process.hrtime.bigint()) / 1e9);
  const postJson = options.postJson ?? defaultPostJson;
  const fetchQuotaImpl = options.fetchQuotaImpl ?? fetchQuota;

  const reader: StdinReader = options.readLine
    ? { readLine: options.readLine, close: () => {} }
    : createStdinReader();

  try {
    let host: string;
    let device: Record<string, unknown>;
    try {
      host = await promptHost(reader.readLine, err);
      device = await requestDeviceCode(host, postJson);
    } catch (exc) {
      if (exc instanceof AuthError) {
        err(`error: ${exc.message}\n`);
        return 2;
      }
      throw exc;
    }

    out(
      `Visit ${String(device.verification_uri)} and enter the code: ${String(device.user_code)}\n`,
    );
    err("Waiting for authorization...\n");

    let token: string;
    try {
      token = await pollForToken(host, String(device.device_code), Number(device.interval ?? 5), {
        now,
        sleep,
        postJson,
      });
    } catch (exc) {
      if (exc instanceof LoginCancelledError) {
        err("Login cancelled.\n");
        return 2;
      }
      if (exc instanceof AuthError) {
        err(`error: ${exc.message}\n`);
        return 2;
      }
      throw exc;
    }

    if (!token.startsWith("ghu_")) {
      err(
        "error: GitHub returned a non-GitHub-App token (expected `ghu_…` prefix). " +
          "The bundled CLIENT_ID is misconfigured — see README 'Switch to your own GitHub App'.\n",
      );
      return 2;
    }

    const auth = new Auth(token, host, "native");

    try {
      await fetchQuotaImpl(auth);
    } catch (exc) {
      if (exc instanceof NoSubscriptionError) {
        err("error: post-login verification failed: this account has no Copilot quota.\n");
        return 2;
      }
      if (exc instanceof APIError) {
        const scrubbed = scrub(exc.message, token);
        err(`error: post-login verification failed: ${scrubbed}\n`);
        return 2;
      }
      throw exc;
    }

    const target = authPath();
    if (existsSync(target)) {
      err("Re-authenticating — previous credentials will be replaced.\n");
    }

    try {
      writeSecretFile(target, { "github-copilot": { token, host } });
    } catch (exc) {
      const reason = exc instanceof Error ? exc.message : String(exc);
      err(`error: could not write credentials: ${reason}\n`);
      return 2;
    }

    // Clean up any stale session.json from versions that cached a session token.
    deleteSecretFile(join(configDir(), "session.json"));

    out(`Logged in to GitHub Copilot via ${host}.\n`);
    return 0;
  } finally {
    reader.close();
  }
}

export function runLogout(options: { stdout?: Writer } = {}): number {
  const out: Writer = options.stdout ?? ((text) => void process.stdout.write(text));
  deleteSecretFile(authPath());
  // Legacy cleanup: pre-session-removal versions cached a session token here.
  deleteSecretFile(join(configDir(), "session.json"));
  out("Logged out of copilot-spend.\n");
  return 0;
}
