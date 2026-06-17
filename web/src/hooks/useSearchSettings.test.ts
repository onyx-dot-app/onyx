import { secondaryRefreshInterval } from "@/lib/indexing/hooks";
import type { EmbeddingModelResponse } from "@/lib/indexing/interfaces";

const embeddingModelResponse: EmbeddingModelResponse = {
  model_name: "text-embedding-3-small",
  model_dim: 1536,
  normalize: true,
  query_prefix: null,
  passage_prefix: null,
  provider_type: null,
  api_key: null,
  api_url: null,
  index_name: null,
};

describe("secondaryRefreshInterval", () => {
  test("returns 5000 when a migration is in flight", () => {
    expect(secondaryRefreshInterval(embeddingModelResponse)).toBe(5000);
  });

  test("returns 60000 when there is no secondary model", () => {
    expect(secondaryRefreshInterval(null)).toBe(60000);
  });

  test("returns 60000 before SWR has loaded data", () => {
    expect(secondaryRefreshInterval(undefined)).toBe(60000);
  });
});
