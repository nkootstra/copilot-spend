import { describe, expect, test } from "bun:test";
import { fetchQuota } from "../src/api";
import { Auth } from "../src/auth";
import { APIError, NoSubscriptionError } from "../src/errors";

interface Call {
  url: string;
  init: RequestInit;
}

/** A fetch double that returns/throws scripted outcomes per call, recording args. */
function stubFetch(outcomes: Array<Response | Error>): {
  fetchImpl: typeof fetch;
  calls: Call[];
} {
  const calls: Call[] = [];
  let index = 0;
  const fetchImpl = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} });
    const outcome = outcomes[Math.min(index, outcomes.length - 1)];
    index += 1;
    if (outcome instanceof Error) {
      throw outcome;
    }
    return outcome as Response;
  }) as unknown as typeof fetch;
  return { fetchImpl, calls };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status });
}

function errorResponse(status: number, body = ""): Response {
  return new Response(body, { status });
}

function timeoutError(): Error {
  const err = new Error("timed out");
  err.name = "TimeoutError";
  return err;
}

const noopSleep = async (): Promise<void> => {};

describe("URL targeting", () => {
  test("GHE host targets api/v3 path", async () => {
    const auth = new Auth("t", "ghe.example.com");
    const { fetchImpl, calls } = stubFetch([jsonResponse({ ok: true })]);

    await fetchQuota(auth, { fetchImpl });

    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe("https://ghe.example.com/api/v3/copilot_internal/user");
  });

  test("github.com host targets api.github.com", async () => {
    const auth = new Auth("t", "github.com");
    const { fetchImpl, calls } = stubFetch([jsonResponse({ ok: true })]);

    await fetchQuota(auth, { fetchImpl });

    expect(calls[0]?.url).toBe("https://api.github.com/copilot_internal/user");
  });

  test("uses HTTPS", async () => {
    const auth = new Auth("t", "ghe.example.com");
    const { fetchImpl, calls } = stubFetch([jsonResponse({ ok: true })]);

    await fetchQuota(auth, { fetchImpl });

    expect(calls[0]?.url.startsWith("https://")).toBe(true);
  });
});

describe("success and headers", () => {
  test("returns parsed JSON on 200", async () => {
    const auth = new Auth("t", "ghe.example.com");
    const payload = { login: "u", copilot_plan: "business" };
    const { fetchImpl } = stubFetch([jsonResponse(payload)]);

    const result = await fetchQuota(auth, { fetchImpl });

    expect(result).toEqual(payload);
  });

  test("does not send copilot-integration-id header", async () => {
    const auth = new Auth("t", "ghe.example.com");
    const { fetchImpl, calls } = stubFetch([jsonResponse({ ok: true })]);

    await fetchQuota(auth, { fetchImpl });

    const headers = calls[0]?.init.headers as Record<string, string>;
    const keys = Object.keys(headers).map((k) => k.toLowerCase());
    expect(keys).not.toContain("copilot-integration-id");
  });

  test("native source uses OAuth token as Bearer directly", async () => {
    const auth = new Auth("ghu_oauth_secret", "ghe.example.com", "native");
    const { fetchImpl, calls } = stubFetch([jsonResponse({ ok: true })]);

    await fetchQuota(auth, { fetchImpl });

    const headers = calls[0]?.init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer ghu_oauth_secret");
  });

  test("opencode source uses OAuth token as Bearer directly", async () => {
    const auth = new Auth("gho_opencode_token", "ghe.example.com", "opencode");
    const { fetchImpl, calls } = stubFetch([jsonResponse({ ok: true })]);

    await fetchQuota(auth, { fetchImpl });

    const headers = calls[0]?.init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer gho_opencode_token");
  });

  test("includes User-Agent with version", async () => {
    const auth = new Auth("t", "ghe.example.com");
    const { fetchImpl, calls } = stubFetch([jsonResponse({ ok: true })]);

    await fetchQuota(auth, { fetchImpl });

    const headers = calls[0]?.init.headers as Record<string, string>;
    expect(headers["User-Agent"]?.startsWith("copilot-spend/")).toBe(true);
  });

  test("non-JSON response raises APIError", async () => {
    const auth = new Auth("t", "ghe.example.com");
    const { fetchImpl } = stubFetch([new Response("not json", { status: 200 })]);

    await expect(fetchQuota(auth, { fetchImpl })).rejects.toThrow(/non-JSON/);
  });

  test("non-object JSON raises APIError", async () => {
    const auth = new Auth("t", "ghe.example.com");
    const { fetchImpl } = stubFetch([new Response("[1,2,3]", { status: 200 })]);

    await expect(fetchQuota(auth, { fetchImpl })).rejects.toThrow(/non-object/);
  });
});

describe("HTTP error mapping", () => {
  test("401 with opencode source says opencode login", async () => {
    const auth = new Auth("t", "ghe.example.com", "opencode");
    const { fetchImpl } = stubFetch([errorResponse(401)]);

    await expect(fetchQuota(auth, { fetchImpl, sleep: noopSleep })).rejects.toThrow(
      /opencode login/i,
    );
  });

  test("401 with native source says copilot-spend login", async () => {
    const auth = new Auth("t", "ghe.example.com", "native");
    const { fetchImpl } = stubFetch([errorResponse(401)]);

    try {
      await fetchQuota(auth, { fetchImpl, sleep: noopSleep });
      throw new Error("expected throw");
    } catch (exc) {
      const message = (exc as Error).message.toLowerCase();
      expect(message).toContain("copilot-spend login");
      expect(message).not.toContain("opencode");
    }
  });

  test("403 with opencode source says opencode login", async () => {
    const auth = new Auth("t", "ghe.example.com", "opencode");
    const { fetchImpl } = stubFetch([errorResponse(403)]);

    await expect(fetchQuota(auth, { fetchImpl })).rejects.toThrow(/opencode login/i);
  });

  test("403 with native source says copilot-spend login", async () => {
    const auth = new Auth("t", "ghe.example.com", "native");
    const { fetchImpl } = stubFetch([errorResponse(403)]);

    await expect(fetchQuota(auth, { fetchImpl })).rejects.toThrow(/copilot-spend login/i);
  });

  test("404 raises NoSubscriptionError", async () => {
    const auth = new Auth("t", "ghe.example.com");
    const { fetchImpl } = stubFetch([errorResponse(404)]);

    await expect(fetchQuota(auth, { fetchImpl })).rejects.toThrow(NoSubscriptionError);
  });

  test("500 includes status and url", async () => {
    const auth = new Auth("t", "ghe.example.com");
    const { fetchImpl } = stubFetch([errorResponse(500), errorResponse(500)]);

    try {
      await fetchQuota(auth, { fetchImpl, sleep: noopSleep });
      throw new Error("expected throw");
    } catch (exc) {
      const message = (exc as Error).message;
      expect(message).toContain("500");
      expect(message).toContain("ghe.example.com");
    }
  });

  test("418 includes status, url, and body excerpt", async () => {
    const auth = new Auth("ghu_realistic_length_oauth_token", "ghe.example.com");
    const { fetchImpl } = stubFetch([errorResponse(418, '{"message":"teapot"}')]);

    try {
      await fetchQuota(auth, { fetchImpl });
      throw new Error("expected throw");
    } catch (exc) {
      const message = (exc as Error).message;
      expect(message).toContain("418");
      expect(message).toContain("ghe.example.com");
      expect(message).toContain("teapot");
    }
  });

  test("long error body is truncated with an ellipsis", async () => {
    const auth = new Auth("t", "ghe.example.com");
    const longBody = "x".repeat(900);
    const { fetchImpl } = stubFetch([errorResponse(418, longBody)]);

    try {
      await fetchQuota(auth, { fetchImpl });
      throw new Error("expected throw");
    } catch (exc) {
      const message = (exc as Error).message;
      expect(message).toContain("…");
      // 900-char body must not appear in full.
      expect(message).not.toContain("x".repeat(900));
    }
  });

  test("error messages do not contain bearer token", async () => {
    const auth = new Auth("hunter2-secret-token", "ghe.example.com");
    const body = '{"token":"hunter2-secret-token","status":"error"}';
    const { fetchImpl } = stubFetch([errorResponse(418, body)]);

    try {
      await fetchQuota(auth, { fetchImpl });
      throw new Error("expected throw");
    } catch (exc) {
      expect((exc as Error).message).not.toContain("hunter2-secret-token");
    }
  });
});

describe("network and timeout", () => {
  test("network error includes host", async () => {
    const auth = new Auth("t", "ghe.example.com");
    const { fetchImpl } = stubFetch([new Error("DNS lookup failed")]);

    await expect(fetchQuota(auth, { fetchImpl })).rejects.toThrow(/ghe\.example\.com/);
  });

  test("timeout mentions duration or timed out", async () => {
    const auth = new Auth("t", "ghe.example.com");
    const { fetchImpl } = stubFetch([timeoutError()]);

    await expect(fetchQuota(auth, { fetchImpl, timeout: 5.0 })).rejects.toThrow(/timed out/i);
  });
});

describe("retry behavior", () => {
  test("500 retries once then succeeds", async () => {
    const auth = new Auth("t", "ghe.example.com");
    const sleeps: number[] = [];
    const { fetchImpl, calls } = stubFetch([errorResponse(503), jsonResponse({ login: "u" })]);

    const result = await fetchQuota(auth, {
      fetchImpl,
      sleep: async (s) => {
        sleeps.push(s);
      },
    });

    expect(result).toEqual({ login: "u" });
    expect(calls).toHaveLength(2);
    expect(sleeps).toEqual([0.5]);
  });

  test("500 retries once then fails includes status of second failure", async () => {
    const auth = new Auth("t", "ghe.example.com");
    const sleeps: number[] = [];
    const { fetchImpl, calls } = stubFetch([errorResponse(503), errorResponse(502)]);

    try {
      await fetchQuota(auth, {
        fetchImpl,
        sleep: async (s) => {
          sleeps.push(s);
        },
      });
      throw new Error("expected throw");
    } catch (exc) {
      expect(calls).toHaveLength(2);
      expect(sleeps).toEqual([0.5]);
      expect((exc as Error).message).toContain("502");
    }
  });

  test("404 not retried", async () => {
    const auth = new Auth("t", "ghe.example.com");
    const sleeps: number[] = [];
    const { fetchImpl, calls } = stubFetch([errorResponse(404)]);

    await expect(
      fetchQuota(auth, {
        fetchImpl,
        sleep: async (s) => {
          sleeps.push(s);
        },
      }),
    ).rejects.toThrow(NoSubscriptionError);
    expect(calls).toHaveLength(1);
    expect(sleeps).toEqual([]);
  });

  test("401 not retried", async () => {
    const auth = new Auth("t", "ghe.example.com");
    const sleeps: number[] = [];
    const { fetchImpl, calls } = stubFetch([errorResponse(401)]);

    await expect(
      fetchQuota(auth, {
        fetchImpl,
        sleep: async (s) => {
          sleeps.push(s);
        },
      }),
    ).rejects.toThrow(APIError);
    expect(calls).toHaveLength(1);
    expect(sleeps).toEqual([]);
  });
});
