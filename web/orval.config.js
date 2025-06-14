module.exports = {
  onyx: {
    input: {
      target: "openapi/openapi.json",
    },
    output: {
      mode: "tags-split",
      target: "src/lib/generated/onyx-api/api.ts",
      schemas: "src/lib/generated/onyx-api/model",
      client: "swr",
      httpClient: "fetch",
      baseUrl: "http://localhost:3000",
      override: {
        mutator: {
          path: "./src/lib/orvalFetcher.ts",
          name: "orvalFetch",
        },
      },
    },
  },
};
