import { randomBytes } from "node:crypto";
import {
  chmodSync,
  closeSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  renameSync,
  rmSync,
  statSync,
  writeSync,
} from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { AuthError } from "./errors";

const isPosix = process.platform !== "win32";

// stat.S_IWGRP | stat.S_IWOTH — group-write and world-write bits.
const GROUP_OR_WORLD_WRITE = 0o022;

export function configDir(): string {
  const override = process.env.COPILOT_SPEND_CONFIG_DIR;
  if (override) {
    return override;
  }
  const xdg = process.env.XDG_CONFIG_HOME;
  if (xdg) {
    return join(xdg, "copilot-spend");
  }
  return join(homedir(), ".config", "copilot-spend");
}

export function authPath(): string {
  return join(configDir(), "auth.json");
}

function octalMode(mode: number): string {
  return `0o${(mode & 0o7777).toString(8)}`;
}

export function assertSafeParent(parent: string): void {
  if (!isPosix) {
    return;
  }
  if (!existsSync(parent)) {
    return;
  }

  let info: ReturnType<typeof statSync>;
  try {
    info = statSync(parent);
  } catch (exc) {
    const reason = exc instanceof Error ? exc.message : String(exc);
    throw new AuthError(`Cannot stat config directory ${parent}: ${reason}`);
  }

  const uid = process.getuid?.();
  if (uid !== undefined && info.uid !== uid) {
    throw new AuthError(
      `Refusing to use config directory ${parent}: owned by uid ${info.uid}, expected ${uid}. Set COPILOT_SPEND_CONFIG_DIR or XDG_CONFIG_HOME to a directory you own.`,
    );
  }

  if (info.mode & GROUP_OR_WORLD_WRITE) {
    throw new AuthError(
      `Refusing to use config directory ${parent}: mode ${octalMode(info.mode)} grants group or ` +
        `world write. Run \`chmod 700 ${parent}\`.`,
    );
  }
}

export function writeSecretFile(path: string, payload: unknown): void {
  const parent = dirname(path);
  assertSafeParent(parent);
  mkdirSync(parent, { recursive: true });
  if (isPosix) {
    chmodSync(parent, 0o700);
  }

  const tmp = join(parent, `.tmp-${process.pid}-${randomBytes(8).toString("hex")}.json`);
  let fd: number | undefined;
  try {
    fd = openSync(tmp, "wx", 0o600);
    if (isPosix) {
      chmodSync(tmp, 0o600);
    }
    writeSync(fd, JSON.stringify(payload, null, 2));
    fsyncSync(fd);
    closeSync(fd);
    fd = undefined;
    renameSync(tmp, path);
  } catch (exc) {
    if (fd !== undefined) {
      try {
        closeSync(fd);
      } catch {
        // best-effort close before cleanup
      }
    }
    rmSync(tmp, { force: true });
    throw exc;
  }
}

export function deleteSecretFile(path: string): void {
  rmSync(path, { force: true });
}

export function scrub(text: string, ...tokens: (string | null | undefined)[]): string {
  let result = text;
  for (const token of tokens) {
    if (token) {
      result = result.split(token).join("<redacted-token>");
    }
  }
  return result;
}
