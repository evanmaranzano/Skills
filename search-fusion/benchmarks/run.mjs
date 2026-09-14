import { mkdirSync, writeFileSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { runSearchFusion } from "../scripts/search-fusion.mjs";

const here = fileURLToPath(new URL(".", import.meta.url));
const queries = JSON.parse(readFileSync(path.join(here, "queries.json"), "utf8"));

const ARMS = {
  "single": { providerCount: 1, maxSubqueries: 1, depth: "quick", maxFallbackCalls: 0 },
  "multi-query": { providerCount: 1, depth: "verify", maxFallbackCalls: 0 },
  "fusion": {},
};

function summarize(output) {
  const evidence = output.coverage?.evidence ?? {};
  const retrieval = output.coverage?.retrieval ?? {};
  return {
    status: output.status,
    stopReason: output.stopReason,
    calls: output.attempts?.length ?? 0,
    providers: output.providers?.used?.length ?? 0,
    failures: output.providers?.failures?.length ?? 0,
    urls: retrieval.uniqueCanonicalUrls ?? 0,
    domains: retrieval.uniqueDomains ?? 0,
    families: retrieval.uniqueFamilies ?? 0,
    entitiesCovered: (evidence.requiredFacets ?? []).filter(f => f.status === "covered").length,
    entitiesTotal: (evidence.requiredFacets ?? []).length,
    gaps: output.coverage?.gaps ?? [],
    top1: output.results?.[0]?.url ?? null,
    elapsedMs: output.observability?.elapsedMs ?? null,
  };
}

async function runArm(query, armName, armOptions, snapshotDir) {
  const startedAt = Date.now();
  try {
    const output = await runSearchFusion(query.query, {
      adapter: "omp",
      top: 8,
      timeoutMs: 150_000,
      ...armOptions,
    });
    const file = path.join(snapshotDir, `${query.id}.${armName}.json`);
    writeFileSync(file, JSON.stringify(output, null, 2), "utf8");
    return summarize(output);
  } catch (error) {
    return { status: "error", error: String(error?.message ?? error).slice(0, 200), elapsedMs: Date.now() - startedAt };
  }
}

async function main() {
  const runId = new Date().toISOString().replace(/[:.]/g, "-");
  const snapshotDir = path.join(here, "snapshots", runId);
  mkdirSync(snapshotDir, { recursive: true });

  const only = process.argv[2] ? new Set(process.argv[2].split(",")) : null;
  const selected = only ? queries.filter(query => only.has(query.id)) : queries;

  const report = [];
  for (const query of selected) {
    const arms = await Promise.all(
      Object.entries(ARMS).map(([armName, armOptions]) => runArm(query, armName, armOptions, snapshotDir)),
    );
    report.push({ id: query.id, category: query.category, query: query.query, arms: Object.fromEntries(Object.keys(ARMS).map((name, index) => [name, arms[index]])) });
    console.log(`done: ${query.id}`);
  }

  const reportFile = path.join(snapshotDir, "report.json");
  writeFileSync(reportFile, JSON.stringify({ runId, report }, null, 2), "utf8");

  for (const row of report) {
    console.log(`\n${row.id} (${row.category})`);
    for (const [arm, summary] of Object.entries(row.arms)) {
      console.log(`  ${arm.padEnd(12)} calls=${summary.calls ?? "-"} providers=${summary.providers ?? "-"} urls=${summary.urls ?? "-"} entities=${summary.entitiesCovered ?? "-"}/${summary.entitiesTotal ?? "-"} status=${summary.status} ${summary.top1 ?? summary.error ?? ""}`);
    }
  }
  console.log(`\nsnapshots: ${snapshotDir}`);
}

await main();
