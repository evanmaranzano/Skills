export async function runSearchQuery(params) {
  if (params.query === "fail-auth") {
    return {
      content: [{ type: "text", text: "Error: Exa authorization failed (401). Check API key or base URL." }],
      details: { response: { provider: "none", sources: [] }, error: "Exa authorization failed (401). Check API key or base URL." },
    };
  }
  if (params.query === "empty-ok") {
    return { content: [], details: { response: { provider: params.provider, sources: [] } } };
  }
  return {
    content: [],
    details: {
      response: {
        provider: params.provider === "exa" ? "gemini" : params.provider,
        sources: [{ url: "https://example.com/result", title: params.query, snippet: params.query }],
      },
    },
  };
}
