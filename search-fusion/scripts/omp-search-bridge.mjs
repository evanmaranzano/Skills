// Bun subprocess bridge for Node hosts that cannot import OMP's TypeScript
// package sources under node_modules. Credentials remain in OMP AuthStorage.

import { existsSync, readdirSync, readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

function searchModuleCandidates() {
  const relative = path.join("@oh-my-pi", "pi-coding-agent", "src", "web", "search", "index.ts");
  const home = os.homedir();
  const candidates = [
    process.env.OMP_SEARCH_MODULE,
    path.join(home, "node_modules", relative),
    path.join(home, ".bun", "install", "global", "node_modules", relative),
    path.join(path.dirname(process.execPath), "node_modules", relative),
    path.join(path.dirname(process.execPath), "..", "node_modules", relative),
  ].filter(Boolean);

  const cacheRoot = path.join(home, ".bun", "install", "cache", "@oh-my-pi");
  try {
    const cachedPackages = readdirSync(cacheRoot)
      .filter(name => name.startsWith("pi-coding-agent@"))
      .sort()
      .reverse();
    for (const packageName of cachedPackages) {
      candidates.push(path.join(cacheRoot, packageName, "src", "web", "search", "index.ts"));
    }
  } catch {
    // The global node_modules candidate is enough for normal OMP installs.
  }
  return candidates;
}

const modulePath = searchModuleCandidates().find(item => existsSync(item));
if (!modulePath) throw new Error("Cannot locate OMP web-search module; set OMP_SEARCH_MODULE");

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
const module = await import(pathToFileURL(modulePath).href);
if (typeof module.runSearchQuery !== "function") throw new Error("OMP search module has no runSearchQuery export");

const result = await module.runSearchQuery(input.params);
process.stdout.write(JSON.stringify(result));
