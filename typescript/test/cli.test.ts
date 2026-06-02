import { describe, expect, test } from "bun:test";
import { Auth } from "../src/auth";
import { type CliDeps, entrypoint, main } from "../src/cli";
import { APIError, AuthError, NoSubscriptionError } from "../src/errors";
import type { Spend } from "../src/quota";
import { isolateEnv } from "./helpers";

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

function makeSpend(overrides: Partial<Spend> = {}): Spend {
  return {
    login: "alice",
    plan: "business",
    entitlement: 300,
    consumed: 100,
    billablePrus: 0,
    freeRemainingPrus: 200,
    dollarsOwed: 0.0,
    dollarsEntitlement: 12.0,
    dollarsFreeRemaining: 8.0,
    reset: null,
    tokenBasedBilling: false,
    unlimited: false,
    hasQuota: true,
    overagePermitted: false,
    overageCount: 0,
    ...overrides,
  };
}

const nativeAuth = new Auth("t", "github.com", "native");

/** Deps that silence the real streams; individual tests override what they assert. */
function quietDeps(overrides: Partial<CliDeps> = {}): Partial<CliDeps> {
  return { stdout: () => {}, stderr: () => {}, ...overrides };
}

describe("argument parsing", () => {
  test("--version prints the package name and exits 0", async () => {
    const out = collector();
    const rc = await main(["--version"], quietDeps({ stdout: out.write }));

    expect(rc).toBe(0);
    expect(out.text).toContain("copilot-spend");
  });

  test("--help prints usage and exits 0", async () => {
    const out = collector();
    const rc = await main(["--help"], quietDeps({ stdout: out.write }));

    expect(rc).toBe(0);
    expect(out.text).toContain("Usage:");
    expect(out.text).toContain("login");
    expect(out.text).toContain("whoami");
  });

  test("unknown command exits 2", async () => {
    const err = collector();
    const rc = await main(["nope"], quietDeps({ stderr: err.write }));

    expect(rc).toBe(2);
    expect(err.text).toContain("invalid choice");
  });

  test("unrecognized option exits 2", async () => {
    const rc = await main(["--bogus"], quietDeps());
    expect(rc).toBe(2);
  });

  test("extra positional after a subcommand exits 2", async () => {
    const err = collector();
    const rc = await main(["whoami", "extra"], quietDeps({ stderr: err.write }));

    expect(rc).toBe(2);
    expect(err.text).toContain("unrecognized arguments");
  });
});

describe("command dispatch", () => {
  test("login dispatches to runLogin and returns its code", async () => {
    let called = false;
    const rc = await main(
      ["login"],
      quietDeps({
        runLogin: async () => {
          called = true;
          return 0;
        },
      }),
    );

    expect(rc).toBe(0);
    expect(called).toBe(true);
  });

  test("login propagates a non-zero code", async () => {
    const rc = await main(["login"], quietDeps({ runLogin: async () => 2 }));
    expect(rc).toBe(2);
  });

  test("logout dispatches to runLogout", async () => {
    let called = false;
    const rc = await main(
      ["logout"],
      quietDeps({
        runLogout: () => {
          called = true;
          return 0;
        },
      }),
    );

    expect(rc).toBe(0);
    expect(called).toBe(true);
  });

  test("bare invocation runs show-quota in text mode", async () => {
    const out = collector();
    const rc = await main(
      [],
      quietDeps({
        stdout: out.write,
        resolveAuth: () => nativeAuth,
        fetchQuota: async () => ({}),
        parseQuota: () => makeSpend(),
        render: () => "RENDERED-TEXT",
      }),
    );

    expect(rc).toBe(0);
    expect(out.text).toContain("RENDERED-TEXT");
  });
});

describe("--json", () => {
  test("emits parseable JSON from the real renderer", async () => {
    const out = collector();
    const rc = await main(
      ["--json"],
      quietDeps({
        stdout: out.write,
        resolveAuth: () => nativeAuth,
        fetchQuota: async () => ({}),
        parseQuota: () => makeSpend({ consumed: 100 }),
      }),
    );

    expect(rc).toBe(0);
    const parsed = JSON.parse(out.text);
    expect(parsed.login).toBe("alice");
    expect(parsed.consumed_prus).toBe(100);
  });

  test("routes through renderJson, not render", async () => {
    const out = collector();
    let jsonUsed = false;
    await main(
      ["--json"],
      quietDeps({
        stdout: out.write,
        resolveAuth: () => nativeAuth,
        fetchQuota: async () => ({}),
        parseQuota: () => makeSpend(),
        renderJson: () => {
          jsonUsed = true;
          return "{}";
        },
        render: () => "SHOULD-NOT-APPEAR",
      }),
    );

    expect(jsonUsed).toBe(true);
    expect(out.text).not.toContain("SHOULD-NOT-APPEAR");
  });
});

describe("show-quota exit codes", () => {
  test("auth error exits 2", async () => {
    const err = collector();
    const rc = await main(
      [],
      quietDeps({
        stderr: err.write,
        resolveAuth: () => {
          throw new AuthError("no creds");
        },
      }),
    );

    expect(rc).toBe(2);
    expect(err.text).toContain("no creds");
  });

  test("APIError exits 3 and scrubs the token", async () => {
    const err = collector();
    const rc = await main(
      [],
      quietDeps({
        stderr: err.write,
        resolveAuth: () => new Auth("hunter2-token", "github.com", "native"),
        fetchQuota: async () => {
          throw new APIError("upstream said hunter2-token is bad");
        },
      }),
    );

    expect(rc).toBe(3);
    expect(err.text).not.toContain("hunter2-token");
  });

  test("NoSubscriptionError from fetch exits 4", async () => {
    const err = collector();
    const rc = await main(
      [],
      quietDeps({
        stderr: err.write,
        resolveAuth: () => nativeAuth,
        fetchQuota: async () => {
          throw new NoSubscriptionError("no quota");
        },
      }),
    );

    expect(rc).toBe(4);
    expect(err.text).toContain("no Copilot quota");
  });

  test("NoSubscriptionError from parse exits 4", async () => {
    const rc = await main(
      [],
      quietDeps({
        resolveAuth: () => nativeAuth,
        fetchQuota: async () => ({}),
        parseQuota: () => {
          throw new NoSubscriptionError("no quota");
        },
      }),
    );

    expect(rc).toBe(4);
  });

  test("render failure exits 1 and scrubs the token", async () => {
    const err = collector();
    const rc = await main(
      [],
      quietDeps({
        stderr: err.write,
        resolveAuth: () => new Auth("hunter2-token", "github.com", "native"),
        fetchQuota: async () => ({}),
        parseQuota: () => makeSpend(),
        render: () => {
          throw new Error("boom with hunter2-token inside");
        },
      }),
    );

    expect(rc).toBe(1);
    expect(err.text).toContain("unexpected error rendering output");
    expect(err.text).not.toContain("hunter2-token");
  });
});

describe("whoami", () => {
  test("prints login, host, source, and plan", async () => {
    const out = collector();
    const rc = await main(
      ["whoami"],
      quietDeps({
        stdout: out.write,
        resolveAuth: () => nativeAuth,
        fetchQuota: async () => ({ login: "alice", copilot_plan: "business" }),
      }),
    );

    expect(rc).toBe(0);
    expect(out.text).toContain("login:");
    expect(out.text).toContain("alice");
    expect(out.text).toContain("host:");
    expect(out.text).toContain("github.com");
    expect(out.text).toContain("source:");
    expect(out.text).toContain("native");
    expect(out.text).toContain("plan:");
    expect(out.text).toContain("business");
  });

  test("prints token-based billing mode", async () => {
    const out = collector();
    const rc = await main(
      ["whoami"],
      quietDeps({
        stdout: out.write,
        resolveAuth: () => nativeAuth,
        fetchQuota: async () => ({
          login: "alice",
          copilot_plan: "business",
          token_based_billing: true,
        }),
      }),
    );

    expect(rc).toBe(0);
    expect(out.text).toContain("billing:");
    expect(out.text).toContain("token-based");
  });

  test("prints identity even without a subscription", async () => {
    const out = collector();
    const rc = await main(
      ["whoami"],
      quietDeps({
        stdout: out.write,
        resolveAuth: () => new Auth("t", "ghe.example.com", "opencode"),
        fetchQuota: async () => {
          throw new NoSubscriptionError("no quota");
        },
      }),
    );

    expect(rc).toBe(0);
    expect(out.text).toContain("ghe.example.com");
    expect(out.text).toContain("opencode");
    expect(out.text).toContain("no Copilot quota");
  });

  test("auth error exits 2", async () => {
    const err = collector();
    const rc = await main(
      ["whoami"],
      quietDeps({
        stderr: err.write,
        resolveAuth: () => {
          throw new AuthError("no creds");
        },
      }),
    );

    expect(rc).toBe(2);
    expect(err.text).toContain("no creds");
  });

  test("APIError exits 3 and scrubs the token", async () => {
    const err = collector();
    const rc = await main(
      ["whoami"],
      quietDeps({
        stderr: err.write,
        resolveAuth: () => new Auth("hunter2-token", "github.com", "native"),
        fetchQuota: async () => {
          throw new APIError("upstream said hunter2-token is bad");
        },
      }),
    );

    expect(rc).toBe(3);
    expect(err.text).not.toContain("hunter2-token");
  });
});

/** Records the last code passed to exit(); a block body keeps Biome happy. */
function exitRecorder(): { exit: (code: number) => void; readonly code: number } {
  let last = -1;
  return {
    exit: (code: number) => {
      last = code;
    },
    get code() {
      return last;
    },
  };
}

describe("entrypoint", () => {
  test("passes the resolved exit code through to exit()", async () => {
    const recorder = exitRecorder();
    await entrypoint(["--version"], quietDeps({ exit: recorder.exit }));
    expect(recorder.code).toBe(0);
  });

  test("honors a non-zero code (unknown command)", async () => {
    const recorder = exitRecorder();
    await entrypoint(["nope"], quietDeps({ exit: recorder.exit }));
    expect(recorder.code).toBe(2);
  });

  test("catches an unexpected error and exits 1", async () => {
    const restoreEnv = isolateEnv(["COPILOT_SPEND_DEBUG"]);
    const err = collector();
    const recorder = exitRecorder();
    try {
      await entrypoint(
        [],
        quietDeps({
          stderr: err.write,
          exit: recorder.exit,
          resolveAuth: () => {
            throw new Error("kaboom");
          },
        }),
      );
    } finally {
      restoreEnv();
    }

    expect(recorder.code).toBe(1);
    expect(err.text).toContain("unexpected error");
    expect(err.text).toContain("COPILOT_SPEND_DEBUG");
  });

  test("re-raises under COPILOT_SPEND_DEBUG=1", async () => {
    const restoreEnv = isolateEnv(["COPILOT_SPEND_DEBUG"]);
    process.env.COPILOT_SPEND_DEBUG = "1";
    try {
      await expect(
        entrypoint(
          [],
          quietDeps({
            exit: () => {},
            resolveAuth: () => {
              throw new Error("kaboom");
            },
          }),
        ),
      ).rejects.toThrow("kaboom");
    } finally {
      restoreEnv();
    }
  });
});
