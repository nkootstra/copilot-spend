import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { chmodSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { AuthError } from "../src/errors";
import {
  assertSafeParent,
  authPath,
  configDir,
  deleteSecretFile,
  scrub,
  writeSecretFile,
} from "../src/paths";
import { isolateEnv, isPosix, makeTmpDir, removeTmpDir } from "./helpers";

const ENV_KEYS = ["COPILOT_SPEND_CONFIG_DIR", "XDG_CONFIG_HOME"];

let tmp: string;
let restoreEnv: () => void;

beforeEach(() => {
  restoreEnv = isolateEnv(ENV_KEYS);
  tmp = makeTmpDir();
});

afterEach(() => {
  removeTmpDir(tmp);
  restoreEnv();
});

function mode(path: string): number {
  return statSync(path).mode & 0o777;
}

describe("configDir", () => {
  test("defaults to ~/.config/copilot-spend", () => {
    expect(configDir()).toBe(join(homedir(), ".config", "copilot-spend"));
  });

  test("respects XDG_CONFIG_HOME", () => {
    process.env.XDG_CONFIG_HOME = tmp;
    expect(configDir()).toBe(join(tmp, "copilot-spend"));
  });

  test("override wins over XDG_CONFIG_HOME", () => {
    const override = join(tmp, "override");
    process.env.XDG_CONFIG_HOME = join(tmp, "xdg");
    process.env.COPILOT_SPEND_CONFIG_DIR = override;
    expect(configDir()).toBe(override);
  });
});

describe("authPath", () => {
  test("uses configDir", () => {
    process.env.COPILOT_SPEND_CONFIG_DIR = tmp;
    expect(authPath()).toBe(join(tmp, "auth.json"));
  });
});

describe("writeSecretFile", () => {
  test.skipIf(!isPosix)("sets 0600 on the file", () => {
    const target = join(tmp, "cfg", "auth.json");
    writeSecretFile(target, { hello: "world" });
    expect(mode(target)).toBe(0o600);
  });

  test.skipIf(!isPosix)("sets 0700 on the parent", () => {
    const cfg = join(tmp, "cfg");
    writeSecretFile(join(cfg, "auth.json"), { k: "v" });
    expect(mode(cfg)).toBe(0o700);
  });

  test("round-trips the payload", () => {
    const target = join(tmp, "auth.json");
    const payload = { "github-copilot": { token: "ghu_xxx", host: "github.com" } };
    writeSecretFile(target, payload);
    expect(JSON.parse(readFileSync(target, "utf-8"))).toEqual(payload);
  });

  test("cleans up the temp file and leaves no partial target on write failure", () => {
    // A pre-existing directory at the target path makes the final rename fail
    // (EISDIR), exercising the cleanup branch through real behavior.
    const target = join(tmp, "auth.json");
    mkdirSync(target);

    expect(() => writeSecretFile(target, { k: "v" })).toThrow();

    const leftovers = readdirSync(tmp).filter((name) => name.startsWith(".tmp-"));
    expect(leftovers).toEqual([]);
  });

  test.skipIf(!isPosix)("rewrites loose permissions to 0600", () => {
    const target = join(tmp, "auth.json");
    writeFileSync(target, "{}");
    chmodSync(target, 0o644);

    writeSecretFile(target, { k: "v" });

    expect(mode(target)).toBe(0o600);
  });
});

describe("deleteSecretFile", () => {
  test("missing file is a no-op", () => {
    expect(() => deleteSecretFile(join(tmp, "nope.json"))).not.toThrow();
  });

  test("removes an existing file", () => {
    const f = join(tmp, "x.json");
    writeFileSync(f, "{}");
    deleteSecretFile(f);
    expect(readdirSync(tmp)).not.toContain("x.json");
  });
});

describe("assertSafeParent", () => {
  test.skipIf(!isPosix)("accepts a 0700 directory owned by us", () => {
    const parent = join(tmp, "cfg");
    mkdirSync(parent);
    chmodSync(parent, 0o700);
    expect(() => assertSafeParent(parent)).not.toThrow();
  });

  test("missing directory is OK", () => {
    expect(() => assertSafeParent(join(tmp, "not-yet"))).not.toThrow();
  });

  test.skipIf(!isPosix)("rejects a group-writable directory", () => {
    const parent = join(tmp, "cfg");
    mkdirSync(parent);
    chmodSync(parent, 0o770);
    expect(() => assertSafeParent(parent)).toThrow(AuthError);
    try {
      assertSafeParent(parent);
    } catch (exc) {
      expect((exc as Error).message).toContain("chmod 700");
    }
  });

  test.skipIf(!isPosix)("rejects a world-writable directory", () => {
    const parent = join(tmp, "cfg");
    mkdirSync(parent);
    chmodSync(parent, 0o707);
    expect(() => assertSafeParent(parent)).toThrow(AuthError);
  });
});

describe("scrub", () => {
  test("replaces a single token", () => {
    expect(scrub("hello ghu_secret world", "ghu_secret")).toBe("hello <redacted-token> world");
  });

  test("handles null and multiple tokens", () => {
    expect(scrub("ghu_aaa and sess_bbb", "ghu_aaa", null, "sess_bbb")).toBe(
      "<redacted-token> and <redacted-token>",
    );
  });

  test("no match returns input unchanged", () => {
    expect(scrub("nothing here", "ghu_xxx")).toBe("nothing here");
  });

  test("skips an empty-string token", () => {
    expect(scrub("hello", "")).toBe("hello");
  });

  test("replaces every occurrence of a token", () => {
    expect(scrub("a ghu_x b ghu_x c", "ghu_x")).toBe("a <redacted-token> b <redacted-token> c");
  });
});
