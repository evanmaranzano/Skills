const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

export function createAdapter() {
  return {
    name: "mock",
    capabilities: async () => ({}),
    search: async request => {
      if (request.provider === "slow") await sleep(2_000);
      return {
        provider: request.provider,
        sources: [{
          url: `https://${request.provider}.example.com/page`,
          title: `${request.query} on ${request.provider}`,
          snippet: `${request.query} on ${request.provider}`,
        }],
      };
    },
  };
}
