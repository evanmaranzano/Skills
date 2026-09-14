import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const cache = new Map();

export function loadJson(specifier, importMetaUrl) {
  const pathname = fileURLToPath(new URL(specifier, importMetaUrl));
  if (!cache.has(pathname)) {
    const raw = readFileSync(pathname, "utf8");
    cache.set(pathname, {
      data: JSON.parse(raw),
      digest: createHash("sha256").update(raw).digest("hex").slice(0, 16),
    });
  }
  return cache.get(pathname).data;
}

export function configDigest(specifier, importMetaUrl) {
  loadJson(specifier, importMetaUrl);
  const pathname = fileURLToPath(new URL(specifier, importMetaUrl));
  return cache.get(pathname).digest;
}
