import pkg from "../package.json" with { type: "json" };

/**
 * Resolve the package version, mirroring Python's `_package_version()`.
 *
 * Bun inlines this JSON import into the bundled CLI, so package.json is the
 * single source of truth. Falls back to "dev" if the field is somehow absent,
 * matching the Python `PackageNotFoundError` path.
 */
export function packageVersion(): string {
  const version: unknown = (pkg as { version?: unknown }).version;
  return typeof version === "string" && version ? version : "dev";
}
