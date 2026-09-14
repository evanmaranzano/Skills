#!/usr/bin/env node

import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { runCli } from "./search-fusion.mjs";

const selfPath = fileURLToPath(import.meta.url);
if (path.resolve(process.argv[1] ?? "") === selfPath) {
  process.stderr.write("search_fusion.mjs is deprecated; use search-fusion.mjs\n");
  await runCli(process.argv.slice(2));
}
