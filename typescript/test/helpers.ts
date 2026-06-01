import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

/** Create a fresh temp directory; returns its path. Caller cleans up. */
export function makeTmpDir(): string {
  return mkdtempSync(join(tmpdir(), "copilot-spend-test-"));
}

/** Remove a temp directory tree, ignoring errors. */
export function removeTmpDir(dir: string): void {
  rmSync(dir, { recursive: true, force: true });
}

/** True on POSIX platforms where file-permission semantics apply. */
export const isPosix = process.platform !== "win32";

/**
 * Snapshot and clear the environment variables that steer config resolution,
 * mirroring the autouse `_clear_env` fixture in the Python suite. Returns a
 * restore function.
 */
export function isolateEnv(keys: string[]): () => void {
  const saved = new Map<string, string | undefined>();
  for (const key of keys) {
    saved.set(key, process.env[key]);
    delete process.env[key];
  }
  return () => {
    for (const [key, value] of saved) {
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
  };
}
