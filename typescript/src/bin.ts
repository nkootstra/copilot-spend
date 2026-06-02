// Bundled CLI entrypoint. Kept separate from cli.ts so importing the module
// (e.g. from tests) never triggers argument parsing or process.exit.
import { entrypoint } from "./cli";

void entrypoint();
