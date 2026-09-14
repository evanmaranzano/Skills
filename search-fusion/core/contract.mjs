/**
 * Portable Search Fusion contract.
 *
 * Core modules depend only on these shapes. A host adapter must normalize
 * whatever native search tools it exposes into this contract.
 */
export const CAPABILITY_LEVELS = ["L0", "L1", "L2", "L3"];
export const RANK_SEMANTICS = ["ranked", "citation-order", "unknown"];

/**
 * @typedef {Object} SearchCapabilities
 * @property {string} harness Human-readable host harness name.
 * @property {"L0"|"L1"|"L2"|"L3"} level Capability level.
 * @property {boolean} providerPin Whether the host can pin one retrieval provider.
 * @property {boolean} parallelSearch Whether provider/tool calls can safely run in parallel.
 * @property {boolean} structuredSources Whether returned sources are structured instead of terminal text.
 * @property {boolean} fetch Whether the adapter can fetch page content by URL.
 * @property {string[]} providers Provider/tool IDs available through this adapter.
 * @property {string[]} [autoOrder] Optional host native fallback order, if observable.
 * @property {Record<string, string[]>} [roles] Provider ID -> capability roles.
 * @property {Record<string, "ranked"|"citation-order"|"unknown">} [rankSemantics]
 * @property {Record<string, unknown>} [metadata] Non-sensitive host diagnostics.
 */

/**
 * @typedef {Object} SearchRequest
 * @property {string} query
 * @property {string} [provider]
 * @property {"day"|"week"|"month"|"year"} [recency]
 * @property {number} [limit]
 * @property {number} [timeoutMs]
 * @property {AbortSignal} [signal]

/**
 * @typedef {Object} SearchSource
 * @property {string} url
 * @property {string} [title]
 * @property {string} [snippet]
 * @property {string} [publishedAt]
 * @property {string} [publishedDate]
 * @property {number} [ageSeconds]
 * @property {string} [author]
 */

/**
 * @typedef {Object} SearchResponse
 * @property {string} provider
 * @property {SearchSource[]} sources
 * @property {string} [answer]
 * @property {string[]} [citations]
 * @property {string[]} [searchQueries]
 * @property {Object} [metadata]
 */

/**
 * @typedef {Object} FetchResponse
 * @property {string} url
 * @property {string} [title]
 * @property {string} content
 * @property {string} [contentType]
 * @property {Object} [metadata]
 */

/**
 * @typedef {Object} SearchAdapter
 * @property {string} name
 * @property {() => Promise<SearchCapabilities>|SearchCapabilities} capabilities
 * @property {(request: SearchRequest) => Promise<SearchResponse>} search
 * @property {(url: string) => Promise<FetchResponse>} [fetch]
 */
