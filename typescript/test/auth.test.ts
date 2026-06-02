import { afterEach, beforeEach, describe, expect, spyOn, test } from "bun:test";
import { chmodSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { Auth, AuthError, isValidHost, normalizeHost, resolveAuth } from "../src/auth";
import { isPosix, isolateEnv, makeTmpDir, removeTmpDir } from "./helpers";

let tmp: string;
let restoreEnv: () => void;

beforeEach(() => {
  restoreEnv = isolateEnv(["COPILOT_SPEND_CONFIG_DIR", "XDG_CONFIG_HOME", "COPILOT_SPEND_QUIET"]);
  tmp = makeTmpDir();
});

afterEach(() => {
  removeTmpDir(tmp);
  restoreEnv();
});

function write(path: string, payload: unknown): void {
  const text = typeof payload === "string" ? payload : JSON.stringify(payload);
  writeFileSync(path, text, "utf-8");
  if (isPosix) {
    chmodSync(path, 0o600);
  }
}

function missingNative(): string {
  return join(tmp, "no-native.json");
}

describe("opencode resolution", () => {
  test("ghe host from enterpriseUrl", () => {
    const authFile = join(tmp, "auth.json");
    write(authFile, { "github-copilot": { access: "tok", enterpriseUrl: "ghe.example.com" } });

    const auth = resolveAuth({ nativePath: missingNative(), opencodePath: authFile });

    expect(auth.token).toBe("tok");
    expect(auth.host).toBe("ghe.example.com");
    expect(auth.source).toBe("opencode");
  });

  test("defaults to github.com when enterpriseUrl absent", () => {
    const authFile = join(tmp, "auth.json");
    write(authFile, { "github-copilot": { access: "tok" } });

    const auth = resolveAuth({ nativePath: missingNative(), opencodePath: authFile });

    expect(auth.host).toBe("github.com");
  });

  test("defaults to github.com when enterpriseUrl empty", () => {
    const authFile = join(tmp, "auth.json");
    write(authFile, { "github-copilot": { access: "tok", enterpriseUrl: "" } });

    const auth = resolveAuth({ nativePath: missingNative(), opencodePath: authFile });

    expect(auth.host).toBe("github.com");
  });

  test("normalizes https prefix and trailing slash", () => {
    const authFile = join(tmp, "auth.json");
    write(authFile, {
      "github-copilot": { access: "tok", enterpriseUrl: "https://ghe.example.com/" },
    });

    const auth = resolveAuth({ nativePath: missingNative(), opencodePath: authFile });

    expect(auth.host).toBe("ghe.example.com");
  });

  test("normalizes http prefix", () => {
    const authFile = join(tmp, "auth.json");
    write(authFile, {
      "github-copilot": { access: "tok", enterpriseUrl: "http://internal.ghe.example/" },
    });

    const auth = resolveAuth({ nativePath: missingNative(), opencodePath: authFile });

    expect(auth.host).toBe("internal.ghe.example");
  });
});

describe("error paths", () => {
  test("missing file raises pointing at login", () => {
    const missing = join(tmp, "missing.json");

    expect(() => resolveAuth({ nativePath: missingNative(), opencodePath: missing })).toThrow(
      /copilot-spend login/,
    );
  });

  test("malformed JSON raises", () => {
    const authFile = join(tmp, "auth.json");
    write(authFile, "{not json");

    expect(() => resolveAuth({ nativePath: missingNative(), opencodePath: authFile })).toThrow(
      /malformed JSON/i,
    );
  });

  test("missing token raises", () => {
    const authFile = join(tmp, "auth.json");
    write(authFile, { "github-copilot": { enterpriseUrl: "ghe.example.com" } });

    expect(() => resolveAuth({ nativePath: missingNative(), opencodePath: authFile })).toThrow(
      /copilot token/i,
    );
  });

  test("empty token raises", () => {
    const authFile = join(tmp, "auth.json");
    write(authFile, { "github-copilot": { access: "" } });

    expect(() => resolveAuth({ nativePath: missingNative(), opencodePath: authFile })).toThrow(
      AuthError,
    );
  });

  test("invalid hostname rejected", () => {
    const authFile = join(tmp, "auth.json");
    write(authFile, { "github-copilot": { access: "tok", enterpriseUrl: "attacker@evil.com" } });

    expect(() => resolveAuth({ nativePath: missingNative(), opencodePath: authFile })).toThrow(
      /hostname/i,
    );
  });

  test("hostname with port rejected", () => {
    const authFile = join(tmp, "auth.json");
    write(authFile, { "github-copilot": { access: "tok", enterpriseUrl: "ghe.example.com:8080" } });

    expect(() => resolveAuth({ nativePath: missingNative(), opencodePath: authFile })).toThrow(
      AuthError,
    );
  });

  test("hostname with path after strip rejected", () => {
    const authFile = join(tmp, "auth.json");
    write(authFile, {
      "github-copilot": { access: "tok", enterpriseUrl: "https://ghe.example.com/oops" },
    });

    expect(() => resolveAuth({ nativePath: missingNative(), opencodePath: authFile })).toThrow(
      AuthError,
    );
  });
});

describe("Auth redaction", () => {
  test("string representation redacts token", () => {
    const auth = new Auth("super-secret-token-value", "ghe.example.com");

    const text = String(auth);

    expect(text).not.toContain("super-secret-token-value");
    expect(text).toContain("<redacted>");
    expect(text).toContain("ghe.example.com");
  });

  test("console/inspect representation redacts token", () => {
    const auth = new Auth("super-secret-token-value", "ghe.example.com");

    const text = Bun.inspect(auth);

    expect(text).not.toContain("super-secret-token-value");
    expect(text).toContain("<redacted>");
  });
});

describe("permission warnings", () => {
  test.skipIf(!isPosix)("permissive file emits warning", () => {
    const authFile = join(tmp, "auth.json");
    writeFileSync(authFile, JSON.stringify({ "github-copilot": { access: "tok" } }), "utf-8");
    chmodSync(authFile, 0o644);
    const writeSpy = spyOn(process.stderr, "write").mockReturnValue(true);

    resolveAuth({ nativePath: missingNative(), opencodePath: authFile });

    const err = writeSpy.mock.calls.map((c) => String(c[0])).join("");
    writeSpy.mockRestore();
    expect(err.toLowerCase()).toContain("warning");
    expect(err).toContain("chmod 600");
  });

  test.skipIf(!isPosix)("strict mode no warning", () => {
    const authFile = join(tmp, "auth.json");
    writeFileSync(authFile, JSON.stringify({ "github-copilot": { access: "tok" } }), "utf-8");
    chmodSync(authFile, 0o600);
    const writeSpy = spyOn(process.stderr, "write").mockReturnValue(true);

    resolveAuth({ nativePath: missingNative(), opencodePath: authFile });

    const err = writeSpy.mock.calls.map((c) => String(c[0])).join("");
    writeSpy.mockRestore();
    expect(err).toBe("");
  });

  test.skipIf(!isPosix)("warning suppressed by quiet env", () => {
    const authFile = join(tmp, "auth.json");
    writeFileSync(authFile, JSON.stringify({ "github-copilot": { access: "tok" } }), "utf-8");
    chmodSync(authFile, 0o644);
    process.env.COPILOT_SPEND_QUIET = "1";
    const writeSpy = spyOn(process.stderr, "write").mockReturnValue(true);

    resolveAuth({ nativePath: missingNative(), opencodePath: authFile });

    const err = writeSpy.mock.calls.map((c) => String(c[0])).join("");
    writeSpy.mockRestore();
    expect(err).toBe("");
  });

  test.skipIf(!isPosix)("warning mentions quiet env", () => {
    const authFile = join(tmp, "auth.json");
    writeFileSync(authFile, JSON.stringify({ "github-copilot": { access: "tok" } }), "utf-8");
    chmodSync(authFile, 0o644);
    const writeSpy = spyOn(process.stderr, "write").mockReturnValue(true);

    resolveAuth({ nativePath: missingNative(), opencodePath: authFile });

    const err = writeSpy.mock.calls.map((c) => String(c[0])).join("");
    writeSpy.mockRestore();
    expect(err).toContain("COPILOT_SPEND_QUIET");
  });
});

describe("multi-source resolution", () => {
  test("native file wins over opencode", () => {
    const nativeFile = join(tmp, "native.json");
    const opencodeFile = join(tmp, "opencode.json");
    write(nativeFile, { "github-copilot": { token: "ghu_native", host: "github.com" } });
    write(opencodeFile, { "github-copilot": { access: "gho_opencode" } });

    const auth = resolveAuth({ nativePath: nativeFile, opencodePath: opencodeFile });

    expect(auth.token).toBe("ghu_native");
    expect(auth.source).toBe("native");
  });

  test("native missing falls to opencode", () => {
    const opencodeFile = join(tmp, "opencode.json");
    write(opencodeFile, { "github-copilot": { access: "gho_opencode" } });

    const auth = resolveAuth({ nativePath: missingNative(), opencodePath: opencodeFile });

    expect(auth.source).toBe("opencode");
    expect(auth.token).toBe("gho_opencode");
  });

  test("both missing raises pointing at login", () => {
    expect(() =>
      resolveAuth({
        nativePath: join(tmp, "no-native.json"),
        opencodePath: join(tmp, "no-opencode.json"),
      }),
    ).toThrow(/copilot-spend login/);
  });

  test("native malformed does not fall to opencode", () => {
    const nativeFile = join(tmp, "native.json");
    const opencodeFile = join(tmp, "opencode.json");
    write(nativeFile, "{broken");
    write(opencodeFile, { "github-copilot": { access: "gho_opencode" } });

    expect(() => resolveAuth({ nativePath: nativeFile, opencodePath: opencodeFile })).toThrow(
      /copilot-spend/i,
    );
  });

  test("native missing token raises", () => {
    const nativeFile = join(tmp, "native.json");
    write(nativeFile, { "github-copilot": { host: "github.com" } });

    expect(() => resolveAuth({ nativePath: nativeFile, opencodePath: missingNative() })).toThrow(
      AuthError,
    );
  });

  test("native empty host defaults to github.com", () => {
    const nativeFile = join(tmp, "native.json");
    write(nativeFile, { "github-copilot": { token: "ghu_xxx", host: "" } });

    const auth = resolveAuth({ nativePath: nativeFile, opencodePath: missingNative() });

    expect(auth.host).toBe("github.com");
  });

  test("native ghe host", () => {
    const nativeFile = join(tmp, "native.json");
    write(nativeFile, { "github-copilot": { token: "ghu_xxx", host: "ghe.example.com" } });

    const auth = resolveAuth({ nativePath: nativeFile, opencodePath: missingNative() });

    expect(auth.host).toBe("ghe.example.com");
    expect(auth.source).toBe("native");
  });

  test.skipIf(!isPosix)("native uses paths authPath by default", () => {
    const cfg = join(tmp, "cfg");
    process.env.COPILOT_SPEND_CONFIG_DIR = cfg;
    mkdirSync(cfg, { recursive: true });
    chmodSync(cfg, 0o700);
    const nativeFile = join(cfg, "auth.json");
    write(nativeFile, { "github-copilot": { token: "ghu_default", host: "github.com" } });

    const auth = resolveAuth({ opencodePath: join(tmp, "no-opencode.json") });

    expect(auth.token).toBe("ghu_default");
    expect(auth.source).toBe("native");
  });
});

describe("isValidHost — SSRF host validation", () => {
  test.each([
    "127.0.0.1",
    "10.0.0.1",
    "192.168.1.1",
    "172.16.0.1",
    "169.254.169.254",
    "0.0.0.0",
    "::1",
  ])("rejects private IP literal %s", (ip) => {
    expect(isValidHost(ip)).toBe(false);
  });

  test.each(["github.com", "ghe.example.com", "api.github.com", "internal.ghe.example"])(
    "accepts ordinary hostname %s",
    (host) => {
      expect(isValidHost(host)).toBe(true);
    },
  );
});

describe("normalizeHost", () => {
  test("strips scheme and trailing slash", () => {
    expect(normalizeHost("https://ghe.example.com/")).toBe("ghe.example.com");
    expect(normalizeHost("http://ghe.example.com")).toBe("ghe.example.com");
    expect(normalizeHost("ghe.example.com")).toBe("ghe.example.com");
  });
});
