import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { existsSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { Readable } from "node:stream";
import { AuthError } from "../src/auth";
import { APIError, NoSubscriptionError } from "../src/errors";
import {
  createStdinReader,
  defaultPostJson,
  interruptibleSleep,
  LoginCancelledError,
  LoginHttpError,
  LoginNetworkError,
  LoginTimeoutError,
  type PostJson,
  type RunLoginOptions,
  runLogin,
  runLogout,
} from "../src/login";
import { authPath, configDir, writeSecretFile } from "../src/paths";
import { isolateEnv, isPosix, makeTmpDir, removeTmpDir } from "./helpers";

let tmp: string;
let restoreEnv: () => void;

beforeEach(() => {
  restoreEnv = isolateEnv(["COPILOT_SPEND_CONFIG_DIR", "XDG_CONFIG_HOME", "COPILOT_SPEND_QUIET"]);
  tmp = makeTmpDir();
  process.env.COPILOT_SPEND_CONFIG_DIR = tmp;
});

afterEach(() => {
  removeTmpDir(tmp);
  restoreEnv();
});

/** Mirrors Python's StringIO.readline: yields each line, then "" forever at EOF. */
function lineReader(text: string): () => string {
  const lines = text.split("\n");
  let index = 0;
  return () => {
    if (index >= lines.length) {
      return "";
    }
    return lines[index++] ?? "";
  };
}

/** Collects everything written to a stream into a single string. */
function collector(): { write: (text: string) => void; readonly text: string } {
  let buffer = "";
  return {
    write: (text: string) => {
      buffer += text;
    },
    get text() {
      return buffer;
    },
  };
}

type Scripted = Record<string, unknown> | Error;

/** A postJson double that returns/throws each scripted outcome in order. */
function postSequence(...outcomes: Scripted[]): PostJson {
  const queue = [...outcomes];
  return async (url, body) => {
    const item = queue.shift();
    if (item === undefined) {
      throw new Error(`unexpected extra POST to ${url} with ${JSON.stringify(body)}`);
    }
    if (item instanceof Error) {
      throw item;
    }
    return item;
  };
}

function deviceResponse(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    device_code: "dev123",
    user_code: "USER-CODE",
    verification_uri: "https://github.com/login/device",
    interval: 1,
    expires_in: 900,
    ...overrides,
  };
}

const okFetchQuota = async (): Promise<unknown> => ({ login: "u" });

/** Base options shared by the tests: constant clock, no real sleep, silenced streams. */
function baseOptions(overrides: Partial<RunLoginOptions> = {}): RunLoginOptions {
  return {
    sleep: () => {},
    now: () => 0,
    stdout: () => {},
    stderr: () => {},
    ...overrides,
  };
}

function readAuth(): Record<string, unknown> {
  return JSON.parse(readFileSync(authPath(), "utf-8")) as Record<string, unknown>;
}

describe("runLogin — happy paths", () => {
  test("github.com writes auth.json with 0600 perms", async () => {
    const out = collector();
    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("1\n"),
        stdout: out.write,
        postJson: postSequence(deviceResponse(), { access_token: "ghu_realtoken" }),
        fetchQuotaImpl: okFetchQuota,
      }),
    );

    expect(rc).toBe(0);
    expect(out.text).toContain("Logged in");
    expect(out.text).toContain("USER-CODE");
    expect(existsSync(authPath())).toBe(true);
    expect(readAuth()).toEqual({
      "github-copilot": { token: "ghu_realtoken", host: "github.com" },
    });
    if (isPosix) {
      expect(statSync(authPath()).mode & 0o777).toBe(0o600);
    }
  });

  test("GHE targets enterprise device and token URLs", async () => {
    const urls: string[] = [];
    const recordingPost: PostJson = async (url) => {
      urls.push(url);
      if (url.includes("device/code")) {
        return deviceResponse();
      }
      return { access_token: "ghu_ghe" };
    };

    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("2\nghe.example.com\n"),
        postJson: recordingPost,
        fetchQuotaImpl: okFetchQuota,
      }),
    );

    expect(rc).toBe(0);
    expect(urls[0]).toBe("https://ghe.example.com/login/device/code");
    expect(urls[1]).toBe("https://ghe.example.com/login/oauth/access_token");
    expect((readAuth()["github-copilot"] as Record<string, unknown>).host).toBe("ghe.example.com");
  });

  test("slow_down extends the polling interval", async () => {
    const sleeps: number[] = [];
    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("1\n"),
        sleep: (s) => {
          sleeps.push(s);
        },
        postJson: postSequence(
          deviceResponse({ interval: 2 }),
          { error: "slow_down" },
          { access_token: "ghu_ok" },
        ),
        fetchQuotaImpl: okFetchQuota,
      }),
    );

    expect(rc).toBe(0);
    // First sleep at interval=2; after slow_down, interval becomes 7.
    expect(sleeps).toEqual([2, 7]);
  });

  test("re-auth over existing credentials prints notice and replaces token", async () => {
    writeSecretFile(authPath(), {
      "github-copilot": { token: "ghu_old", host: "github.com" },
    });
    const err = collector();

    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("1\n"),
        stderr: err.write,
        postJson: postSequence(deviceResponse(), { access_token: "ghu_new" }),
        fetchQuotaImpl: okFetchQuota,
      }),
    );

    expect(rc).toBe(0);
    expect(err.text).toContain("Re-authenticating");
    expect((readAuth()["github-copilot"] as Record<string, unknown>).token).toBe("ghu_new");
  });

  test("cleans up legacy session.json", async () => {
    const legacy = join(configDir(), "session.json");
    writeSecretFile(legacy, { token: "old_sess", expires_at: 1 });
    expect(existsSync(legacy)).toBe(true);

    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("1\n"),
        postJson: postSequence(deviceResponse(), { access_token: "ghu_x" }),
        fetchQuotaImpl: okFetchQuota,
      }),
    );

    expect(rc).toBe(0);
    expect(existsSync(legacy)).toBe(false);
  });
});

describe("runLogin — polling errors exit 2", () => {
  test("expired_token reports timeout", async () => {
    const err = collector();
    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("1\n"),
        stderr: err.write,
        postJson: postSequence(deviceResponse(), { error: "expired_token" }),
      }),
    );

    expect(rc).toBe(2);
    expect(err.text.toLowerCase()).toContain("timed out");
    expect(existsSync(authPath())).toBe(false);
  });

  test("access_denied reports denial", async () => {
    const err = collector();
    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("1\n"),
        stderr: err.write,
        postJson: postSequence(deviceResponse(), { error: "access_denied" }),
      }),
    );

    expect(rc).toBe(2);
    expect(err.text.toLowerCase()).toContain("denied");
  });

  test("elapsed-time budget guard fires before polling completes", async () => {
    const clock = [0.0, 9999.0];
    let tick = 0;
    const err = collector();
    const rc = await runLogin({
      readLine: lineReader("1\n"),
      stdout: () => {},
      stderr: err.write,
      sleep: () => {},
      now: () => clock[Math.min(tick++, clock.length - 1)] ?? 0,
      // The pending response is never consumed: the guard raises first.
      postJson: postSequence(deviceResponse(), { error: "authorization_pending" }),
    });

    expect(rc).toBe(2);
    expect(err.text.toLowerCase()).toContain("timed out");
    expect(existsSync(authPath())).toBe(false);
  });

  test("Ctrl-C during polling reports cancellation", async () => {
    const err = collector();
    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("1\n"),
        stderr: err.write,
        postJson: postSequence(deviceResponse(), new LoginCancelledError()),
      }),
    );

    expect(rc).toBe(2);
    expect(err.text.toLowerCase()).toContain("cancelled");
    expect(existsSync(authPath())).toBe(false);
  });

  test("polling HTTP error surfaces JSON error_description", async () => {
    const body = JSON.stringify({
      error: "incorrect_client_credentials",
      error_description: "client_secret invalid",
    });
    const err = collector();
    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("1\n"),
        stderr: err.write,
        postJson: postSequence(deviceResponse(), new LoginHttpError(401, body)),
      }),
    );

    expect(rc).toBe(2);
    expect(err.text).toContain("401");
    expect(err.text).toContain("incorrect_client_credentials");
    expect(err.text).toContain("client_secret invalid");
  });
});

describe("runLogin — device-code errors exit 2", () => {
  test("unauthorized_client device error", async () => {
    const err = collector();
    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("1\n"),
        stderr: err.write,
        postJson: postSequence({
          error: "unauthorized_client",
          error_description: "App not allowed",
        }),
      }),
    );

    expect(rc).toBe(2);
    expect(err.text).toContain("unauthorized_client");
    expect(existsSync(authPath())).toBe(false);
  });

  test("network error names the host and skips the code prompt", async () => {
    const out = collector();
    const err = collector();
    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("2\nunreachable.example.com\n"),
        stdout: out.write,
        stderr: err.write,
        postJson: postSequence(new LoginNetworkError("host not found")),
      }),
    );

    expect(rc).toBe(2);
    expect(err.text).toContain("unreachable.example.com");
    expect(out.text).not.toContain("USER-CODE");
    expect(existsSync(authPath())).toBe(false);
  });

  test("device-code HTTP error surfaces JSON error_description", async () => {
    const body = JSON.stringify({
      error: "invalid_request",
      error_description: "client_id is missing",
    });
    const err = collector();
    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("1\n"),
        stderr: err.write,
        postJson: postSequence(new LoginHttpError(422, body)),
      }),
    );

    expect(rc).toBe(2);
    expect(err.text).toContain("422");
    expect(err.text).toContain("invalid_request");
    expect(err.text).toContain("client_id is missing");
  });

  test("device-code HTTP error with non-JSON body includes excerpt", async () => {
    const err = collector();
    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("1\n"),
        stderr: err.write,
        postJson: postSequence(new LoginHttpError(503, "upstream unavailable")),
      }),
    );

    expect(rc).toBe(2);
    expect(err.text).toContain("503");
    expect(err.text).toContain("upstream unavailable");
  });

  test("rejects an SSRF target host", async () => {
    const err = collector();
    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("2\n169.254.169.254\n"),
        stderr: err.write,
        postJson: postSequence(),
      }),
    );

    expect(rc).toBe(2);
    expect(err.text.toLowerCase()).toContain("hostname");
    expect(existsSync(authPath())).toBe(false);
  });
});

describe("runLogin — token validation and verification", () => {
  test("wrong token prefix exits 2 without writing auth", async () => {
    const err = collector();
    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("1\n"),
        stderr: err.write,
        postJson: postSequence(deviceResponse(), { access_token: "gho_oauth_token" }),
      }),
    );

    expect(rc).toBe(2);
    expect(err.text).toContain("ghu_");
    expect(existsSync(authPath())).toBe(false);
  });

  test("verification APIError does not write auth", async () => {
    const err = collector();
    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("1\n"),
        stderr: err.write,
        postJson: postSequence(deviceResponse(), { access_token: "ghu_real" }),
        fetchQuotaImpl: async () => {
          throw new APIError("server says no");
        },
      }),
    );

    expect(rc).toBe(2);
    expect(err.text).toContain("verification failed");
    expect(existsSync(authPath())).toBe(false);
  });

  test("verification error redacts the token", async () => {
    const err = collector();
    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("1\n"),
        stderr: err.write,
        postJson: postSequence(deviceResponse(), { access_token: "ghu_secret_realtoken" }),
        fetchQuotaImpl: async () => {
          throw new APIError("server says: ghu_secret_realtoken is bad");
        },
      }),
    );

    expect(rc).toBe(2);
    expect(err.text).not.toContain("ghu_secret_realtoken");
    expect(err.text).toContain("<redacted-token>");
  });

  test("no Copilot quota exits 2 without writing auth", async () => {
    const err = collector();
    const rc = await runLogin(
      baseOptions({
        readLine: lineReader("1\n"),
        stderr: err.write,
        postJson: postSequence(deviceResponse(), { access_token: "ghu_no_sub" }),
        fetchQuotaImpl: async () => {
          throw new NoSubscriptionError("nope");
        },
      }),
    );

    expect(rc).toBe(2);
    expect(err.text.toLowerCase()).toContain("no copilot quota");
    expect(existsSync(authPath())).toBe(false);
  });
});

describe("runLogout", () => {
  test("removes auth and legacy session, is idempotent on repeat", () => {
    writeSecretFile(authPath(), { k: "v" });
    const legacy = join(configDir(), "session.json");
    writeSecretFile(legacy, { token: "sess", expires_at: 1 });

    const out = collector();
    const rc = runLogout({ stdout: out.write });

    expect(rc).toBe(0);
    expect(out.text).toContain("Logged out");
    expect(existsSync(authPath())).toBe(false);
    expect(existsSync(legacy)).toBe(false);
  });

  test("logout when nothing is stored still succeeds", () => {
    const out = collector();
    const rc = runLogout({ stdout: out.write });

    expect(rc).toBe(0);
    expect(out.text).toContain("Logged out");
  });
});

describe("defaultPostJson transport", () => {
  function recordingFetch(outcome: Response | Error): {
    fetchImpl: typeof fetch;
    calls: RequestInit[];
  } {
    const calls: RequestInit[] = [];
    const fetchImpl = (async (_url: string, init?: RequestInit) => {
      calls.push(init ?? {});
      if (outcome instanceof Error) {
        throw outcome;
      }
      return outcome;
    }) as unknown as typeof fetch;
    return { fetchImpl, calls };
  }

  test("POSTs JSON with the expected headers and parses the object", async () => {
    const { fetchImpl, calls } = recordingFetch(
      new Response(JSON.stringify({ device_code: "x" }), { status: 200 }),
    );

    const result = await defaultPostJson("https://github.com/x", { a: 1 }, 10, fetchImpl);

    expect(result).toEqual({ device_code: "x" });
    expect(calls[0]?.method).toBe("POST");
    expect(calls[0]?.body).toBe(JSON.stringify({ a: 1 }));
    const headers = calls[0]?.headers as Record<string, string>;
    expect(headers.Accept).toBe("application/json");
    expect(headers["Content-Type"]).toBe("application/json");
  });

  test("non-2xx throws LoginHttpError carrying status and body", async () => {
    const { fetchImpl } = recordingFetch(new Response("nope", { status: 422 }));

    const promise = defaultPostJson("https://github.com/x", {}, 10, fetchImpl);
    await expect(promise).rejects.toBeInstanceOf(LoginHttpError);
    await promise.catch((exc: LoginHttpError) => {
      expect(exc.status).toBe(422);
      expect(exc.body).toBe("nope");
    });
  });

  test("array JSON is rejected as non-object", async () => {
    const { fetchImpl } = recordingFetch(new Response("[1,2,3]", { status: 200 }));

    await expect(defaultPostJson("https://github.com/x", {}, 10, fetchImpl)).rejects.toThrow(
      AuthError,
    );
  });

  test("invalid JSON is rejected as non-object", async () => {
    const { fetchImpl } = recordingFetch(new Response("{not json", { status: 200 }));

    await expect(defaultPostJson("https://github.com/x", {}, 10, fetchImpl)).rejects.toThrow(
      AuthError,
    );
  });

  test("timeout maps to LoginTimeoutError", async () => {
    const timeout = new Error("aborted");
    timeout.name = "TimeoutError";
    const { fetchImpl } = recordingFetch(timeout);

    await expect(defaultPostJson("https://github.com/x", {}, 10, fetchImpl)).rejects.toBeInstanceOf(
      LoginTimeoutError,
    );
  });

  test("other network failure maps to LoginNetworkError with reason", async () => {
    const { fetchImpl } = recordingFetch(new Error("DNS lookup failed"));

    const promise = defaultPostJson("https://github.com/x", {}, 10, fetchImpl);
    await expect(promise).rejects.toBeInstanceOf(LoginNetworkError);
    await promise.catch((exc: LoginNetworkError) => {
      expect(exc.reason).toBe("DNS lookup failed");
    });
  });
});

describe("interruptibleSleep", () => {
  test("resolves after the delay and leaves no SIGINT listener", async () => {
    const before = process.listenerCount("SIGINT");
    await interruptibleSleep(0);
    expect(process.listenerCount("SIGINT")).toBe(before);
  });

  test("Ctrl-C rejects with LoginCancelledError and cleans up", async () => {
    const before = process.listenerCount("SIGINT");
    const pending = interruptibleSleep(60);
    process.emit("SIGINT");

    await expect(pending).rejects.toBeInstanceOf(LoginCancelledError);
    expect(process.listenerCount("SIGINT")).toBe(before);
  });
});

describe("createStdinReader", () => {
  test("yields lines then empty string at EOF", async () => {
    const reader = createStdinReader(Readable.from(["1\nghe.example.com\n"]));

    expect(await reader.readLine()).toBe("1");
    expect(await reader.readLine()).toBe("ghe.example.com");
    expect(await reader.readLine()).toBe("");
    reader.close();
  });
});
