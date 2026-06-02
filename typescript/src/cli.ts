import { fetchQuota } from "./api";
import type { Auth } from "./auth";
import { resolveAuth } from "./auth";
import { APIError, AuthError, NoSubscriptionError } from "./errors";
import { runLogin, runLogout } from "./login";
import { render, renderJson } from "./output";
import { scrub } from "./paths";
import { type Spend, parseQuota } from "./quota";
import { packageVersion } from "./version";

type Writer = (text: string) => void;

/**
 * Injectable collaborators for the CLI. Defaults wire the real implementations;
 * tests substitute fakes here instead of monkeypatching module bindings (which
 * ESM forbids), keeping behavior verifiable through the public `main` interface.
 */
export interface CliDeps {
  resolveAuth: () => Auth;
  fetchQuota: (auth: Auth) => Promise<Record<string, unknown>>;
  parseQuota: (payload: Record<string, unknown>) => Spend;
  render: (spend: Spend, now: Date) => string;
  renderJson: (spend: Spend) => string;
  runLogin: () => Promise<number>;
  runLogout: () => number;
  now: () => Date;
  stdout: Writer;
  stderr: Writer;
  exit: (code: number) => void;
}

function withDefaults(deps: Partial<CliDeps>): CliDeps {
  return {
    resolveAuth: deps.resolveAuth ?? resolveAuth,
    fetchQuota: deps.fetchQuota ?? fetchQuota,
    parseQuota: deps.parseQuota ?? parseQuota,
    render: deps.render ?? render,
    renderJson: deps.renderJson ?? renderJson,
    runLogin: deps.runLogin ?? runLogin,
    runLogout: deps.runLogout ?? runLogout,
    now: deps.now ?? (() => new Date()),
    stdout: deps.stdout ?? ((text) => void process.stdout.write(text)),
    stderr: deps.stderr ?? ((text) => void process.stderr.write(text)),
    exit: deps.exit ?? ((code) => process.exit(code)),
  };
}

type Command = "login" | "logout" | "whoami";

type ParseResult =
  | { kind: "version" }
  | { kind: "help" }
  | { kind: "command"; command: Command | null; json: boolean }
  | { kind: "error"; message: string };

function parseArgs(argv: string[]): ParseResult {
  let json = false;
  const positionals: string[] = [];

  for (const arg of argv) {
    if (arg === "--version") {
      return { kind: "version" };
    }
    if (arg === "-h" || arg === "--help") {
      return { kind: "help" };
    }
    if (arg === "--json") {
      json = true;
      continue;
    }
    if (arg.startsWith("-")) {
      return { kind: "error", message: `unrecognized arguments: ${arg}` };
    }
    positionals.push(arg);
  }

  const [first, ...rest] = positionals;
  if (first === undefined) {
    return { kind: "command", command: null, json };
  }
  if (first === "login" || first === "logout" || first === "whoami") {
    if (rest.length > 0) {
      return { kind: "error", message: `unrecognized arguments: ${rest.join(" ")}` };
    }
    return { kind: "command", command: first, json };
  }
  return { kind: "error", message: `argument command: invalid choice: '${first}'` };
}

function usageText(): string {
  return [
    "Usage: copilot-spend [--json] [command]",
    "",
    "Print your current-period GitHub Copilot spend and reset date.",
    "",
    "Commands:",
    "  login     Authenticate via GitHub OAuth device flow (github.com or GHE).",
    "  logout    Remove copilot-spend's stored credentials.",
    "  whoami    Print the current login, host, credential source, and Copilot plan.",
    "",
    "Options:",
    "  --json        Print the current spend as JSON (stable schema).",
    "  --version     Show the version and exit.",
    "  -h, --help    Show this help message and exit.",
    "",
  ].join("\n");
}

/**
 * Resolve credentials, or report an AuthError to stderr and return null so the
 * caller returns exit code 2. Non-auth errors propagate. Shared by the
 * show-quota and whoami flows, which both open the same way.
 */
function resolveAuthOrReport(deps: CliDeps): Auth | null {
  try {
    return deps.resolveAuth();
  } catch (exc) {
    if (exc instanceof AuthError) {
      deps.stderr(`${exc.message}\n`);
      return null;
    }
    throw exc;
  }
}

async function runShowQuota(deps: CliDeps, asJson: boolean): Promise<number> {
  const auth = resolveAuthOrReport(deps);
  if (auth === null) {
    return 2;
  }

  let payload: Record<string, unknown>;
  try {
    payload = await deps.fetchQuota(auth);
  } catch (exc) {
    if (exc instanceof NoSubscriptionError) {
      deps.stderr(`no Copilot quota on this account: ${exc.message}\n`);
      return 4;
    }
    if (exc instanceof APIError) {
      deps.stderr(`${scrub(exc.message, auth.token)}\n`);
      return 3;
    }
    throw exc;
  }

  let spend: Spend;
  try {
    spend = deps.parseQuota(payload);
  } catch (exc) {
    if (exc instanceof NoSubscriptionError) {
      deps.stderr(`no Copilot quota on this account: ${exc.message}\n`);
      return 4;
    }
    throw exc;
  }

  try {
    if (asJson) {
      deps.stdout(`${deps.renderJson(spend)}\n`);
    } else {
      deps.stdout(`${deps.render(spend, deps.now())}\n`);
    }
  } catch (exc) {
    const message = exc instanceof Error ? exc.message : String(exc);
    deps.stderr(`${scrub(`unexpected error rendering output: ${message}`, auth.token)}\n`);
    return 1;
  }

  return 0;
}

async function runWhoami(deps: CliDeps): Promise<number> {
  const auth = resolveAuthOrReport(deps);
  if (auth === null) {
    return 2;
  }

  let payload: Record<string, unknown> | null = null;
  try {
    payload = await deps.fetchQuota(auth);
  } catch (exc) {
    if (exc instanceof NoSubscriptionError) {
      // Identity is still meaningful without a quota — print what we have.
      payload = null;
    } else if (exc instanceof APIError) {
      deps.stderr(`${scrub(exc.message, auth.token)}\n`);
      return 3;
    } else {
      throw exc;
    }
  }

  let login = "";
  let plan = "";
  let billing = "";
  if (payload !== null) {
    login = payload.login ? String(payload.login) : "";
    plan = payload.copilot_plan ? String(payload.copilot_plan) : "";
    if (payload.token_based_billing === true) {
      billing = "token-based";
    } else if (payload.token_based_billing === false) {
      billing = "premium-requests";
    }
  }

  const lines = [`host:   ${auth.host}`, `source: ${auth.source}`];
  if (login) {
    lines.unshift(`login:  ${login}`);
  }
  if (plan) {
    lines.push(`plan:   ${plan}`);
  } else if (payload === null) {
    lines.push("plan:   (no Copilot quota on this account)");
  }
  if (billing) {
    lines.push(`billing: ${billing}`);
  }

  deps.stdout(`${lines.join("\n")}\n`);
  return 0;
}

async function dispatch(argv: string[], deps: CliDeps): Promise<number> {
  const parsed = parseArgs(argv);

  if (parsed.kind === "version") {
    deps.stdout(`copilot-spend ${packageVersion()}\n`);
    return 0;
  }
  if (parsed.kind === "help") {
    deps.stdout(usageText());
    return 0;
  }
  if (parsed.kind === "error") {
    deps.stderr(`copilot-spend: error: ${parsed.message}\n`);
    return 2;
  }

  if (parsed.command === "login") {
    return deps.runLogin();
  }
  if (parsed.command === "logout") {
    return deps.runLogout();
  }
  if (parsed.command === "whoami") {
    return runWhoami(deps);
  }
  return runShowQuota(deps, parsed.json);
}

export async function main(
  argv: string[] = process.argv.slice(2),
  depsInit: Partial<CliDeps> = {},
): Promise<number> {
  return dispatch(argv, withDefaults(depsInit));
}

export async function entrypoint(
  argv: string[] = process.argv.slice(2),
  depsInit: Partial<CliDeps> = {},
): Promise<void> {
  const deps = withDefaults(depsInit);
  try {
    deps.exit(await dispatch(argv, deps));
  } catch (exc) {
    if (process.env.COPILOT_SPEND_DEBUG === "1") {
      throw exc;
    }
    const message = exc instanceof Error ? exc.message : String(exc);
    deps.stderr(`unexpected error: ${message} (set COPILOT_SPEND_DEBUG=1 for a full traceback)\n`);
    deps.exit(1);
  }
}
