import { existsSync, readFileSync, statSync } from "node:fs";
import { isIP } from "node:net";
import { homedir } from "node:os";
import { join } from "node:path";
import { AuthError } from "./errors";
import { authPath } from "./paths";

export { AuthError } from "./errors";

// opencode stores its credentials here; we read them as a fallback so users who
// already ran `opencode login` don't have to authenticate again.
const AUTH_PATH = join(homedir(), ".local", "share", "opencode", "auth.json");

const isPosix = process.platform !== "win32";

// stat group/other permission bits — S_IRWXG | S_IRWXO.
const GROUP_OR_OTHER = 0o077;

// RFC 1123 hostname: dot-separated labels, each 1-63 chars of [A-Za-z0-9-],
// not starting or ending with a hyphen. Total length <= 253.
const HOSTNAME_LABEL = "[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?";
const HOSTNAME_RE = new RegExp(`^${HOSTNAME_LABEL}(?:\\.${HOSTNAME_LABEL})*$`);

export type AuthSource = "native" | "opencode";

export class Auth {
  readonly token: string;
  readonly host: string;
  readonly source: AuthSource;

  constructor(token: string, host: string, source: AuthSource = "opencode") {
    this.token = token;
    this.host = host;
    this.source = source;
  }

  /** Redact the token in any string/console representation. */
  toString(): string {
    return `Auth(token=<redacted>, host=${JSON.stringify(this.host)}, source=${JSON.stringify(this.source)})`;
  }

  [Symbol.for("nodejs.util.inspect.custom")](): string {
    return this.toString();
  }
}

function ipv4ToInt(host: string): number | null {
  const parts = host.split(".");
  if (parts.length !== 4) {
    return null;
  }
  let result = 0;
  for (const part of parts) {
    if (part === "" || !/^\d{1,3}$/.test(part)) {
      return null;
    }
    const n = Number(part);
    if (n > 255) {
      return null;
    }
    result = (result << 8) | n;
  }
  return result >>> 0;
}

function inCidr(ip: number, base: string, prefix: number): boolean {
  const baseInt = ipv4ToInt(base);
  if (baseInt === null) {
    return false;
  }
  const mask = prefix === 0 ? 0 : (0xffffffff << (32 - prefix)) >>> 0;
  return (ip & mask) >>> 0 === (baseInt & mask) >>> 0;
}

// IPv4 ranges treated as non-public: private, loopback, link-local, reserved,
// multicast, and unspecified — the union of Python's ipaddress predicates.
const RESERVED_IPV4: ReadonlyArray<readonly [string, number]> = [
  ["0.0.0.0", 8],
  ["10.0.0.0", 8],
  ["100.64.0.0", 10],
  ["127.0.0.0", 8],
  ["169.254.0.0", 16],
  ["172.16.0.0", 12],
  ["192.0.0.0", 24],
  ["192.0.2.0", 24],
  ["192.168.0.0", 16],
  ["198.18.0.0", 15],
  ["198.51.100.0", 24],
  ["203.0.113.0", 24],
  ["224.0.0.0", 4],
  ["240.0.0.0", 4],
];

function isReservedIpv4Int(ip: number): boolean {
  return RESERVED_IPV4.some(([base, prefix]) => inCidr(ip, base, prefix));
}

// IPv4 literals are the only IP form that can reach the HOSTNAME_RE gate in
// isValidHost — every IPv6 literal contains a colon, which HOSTNAME_RE rejects
// outright, so a separate IPv6 reserved-range check could never change the
// result. (Python's ipaddress-based check is dead the same way for the same
// reason.) We therefore only classify IPv4 here and let the hostname regex
// reject all IPv6 literals.
function isPrivateIpLiteral(host: string): boolean {
  if (isIP(host) === 4) {
    const ip = ipv4ToInt(host);
    return ip !== null && isReservedIpv4Int(ip);
  }
  return false;
}

export function isValidHost(host: string): boolean {
  if (!host || host.length > 253) {
    return false;
  }
  if (isPrivateIpLiteral(host)) {
    return false;
  }
  return HOSTNAME_RE.test(host);
}

export function normalizeHost(raw: string): string {
  let host = raw.trim();
  for (const prefix of ["https://", "http://"]) {
    if (host.startsWith(prefix)) {
      host = host.slice(prefix.length);
      break;
    }
  }
  return host.replace(/\/+$/, "").trim();
}

function warnIfPermissive(path: string): void {
  if (!isPosix) {
    return;
  }
  if (process.env.COPILOT_SPEND_QUIET === "1") {
    return;
  }
  let mode: number;
  try {
    mode = statSync(path).mode;
  } catch {
    return;
  }
  if (mode & GROUP_OR_OTHER) {
    const ownerOctal = `0o${(mode & 0o7777).toString(8)}`;
    process.stderr.write(
      `warning: ${path} permissions are ${ownerOctal} — the file holds a long-lived Copilot token; consider \`chmod 600\`. Set COPILOT_SPEND_QUIET=1 to silence.\n`,
    );
  }
}

interface AuthFileMessages {
  malformed: (detail: string) => string;
  notObject: string;
}

function loadAuthData(path: string, messages: AuthFileMessages): Record<string, unknown> {
  warnIfPermissive(path);

  let raw: string;
  try {
    raw = readFileSync(path, "utf-8");
  } catch (exc) {
    const reason = exc instanceof Error ? exc.message : String(exc);
    throw new AuthError(messages.malformed(reason));
  }

  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch (exc) {
    const reason = exc instanceof Error ? exc.message : String(exc);
    throw new AuthError(messages.malformed(reason));
  }

  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    throw new AuthError(messages.notObject);
  }
  return data as Record<string, unknown>;
}

function copilotEntry(data: Record<string, unknown>, badEntry: string): Record<string, unknown> {
  const entry = data["github-copilot"] || {};
  if (typeof entry !== "object" || entry === null || Array.isArray(entry)) {
    throw new AuthError(badEntry);
  }
  return entry as Record<string, unknown>;
}

function readOpencode(path: string): Auth | null {
  if (!existsSync(path)) {
    return null;
  }

  const data = loadAuthData(path, {
    malformed: (detail) => `opencode auth file is malformed JSON at ${path}: ${detail}`,
    notObject: `opencode auth file at ${path} is not a JSON object.`,
  });
  const entry = copilotEntry(
    data,
    `opencode auth file at ${path} has a malformed github-copilot entry.`,
  );

  const token = entry.access;
  if (!token || typeof token !== "string") {
    throw new AuthError(`No GitHub Copilot token in ${path}. Run \`opencode login\` first.`);
  }

  let enterpriseRaw = entry.enterpriseUrl;
  if (enterpriseRaw === undefined || enterpriseRaw === null) {
    enterpriseRaw = "";
  }
  if (typeof enterpriseRaw !== "string") {
    throw new AuthError(`opencode auth file at ${path} has a non-string enterpriseUrl field.`);
  }

  const enterprise = normalizeHost(enterpriseRaw);
  let host: string;
  if (!enterprise) {
    host = "github.com";
  } else if (!isValidHost(enterprise)) {
    throw new AuthError(
      `enterpriseUrl in ${path} is not a valid hostname: ${JSON.stringify(enterpriseRaw)}. Expected a bare hostname like \`ghe.example.com\`.`,
    );
  } else {
    host = enterprise;
  }

  return new Auth(token, host, "opencode");
}

function readNative(path: string): Auth | null {
  if (!existsSync(path)) {
    return null;
  }

  const data = loadAuthData(path, {
    malformed: (detail) =>
      `copilot-spend auth file is malformed JSON at ${path}: ${detail}. Run \`copilot-spend login\` to recreate it.`,
    notObject: `copilot-spend auth file at ${path} is not a JSON object.`,
  });
  const entry = copilotEntry(
    data,
    `copilot-spend auth file at ${path} has a malformed github-copilot entry.`,
  );

  const token = entry.token;
  if (!token || typeof token !== "string") {
    throw new AuthError(`No GitHub Copilot token in ${path}. Run \`copilot-spend login\`.`);
  }

  const hostRaw = entry.host === undefined ? "" : entry.host;
  if (typeof hostRaw !== "string") {
    throw new AuthError(`copilot-spend auth file at ${path} has a non-string host field.`);
  }

  const host = normalizeHost(hostRaw) || "github.com";
  if (host !== "github.com" && !isValidHost(host)) {
    throw new AuthError(`host in ${path} is not a valid hostname: ${JSON.stringify(hostRaw)}.`);
  }

  return new Auth(token, host, "native");
}

export interface ResolveAuthOptions {
  nativePath?: string;
  opencodePath?: string;
}

export function resolveAuth(options: ResolveAuthOptions = {}): Auth {
  const nativePath = options.nativePath ?? authPath();
  const opencodePath = options.opencodePath ?? AUTH_PATH;

  const native = readNative(nativePath);
  if (native !== null) {
    return native;
  }

  const opencode = readOpencode(opencodePath);
  if (opencode !== null) {
    return opencode;
  }

  throw new AuthError(
    "No credentials found. Run `copilot-spend login` to authenticate, " +
      "or install opencode and run `opencode login`.",
  );
}
