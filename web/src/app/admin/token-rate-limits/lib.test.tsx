import {
  deleteTokenRateLimit,
  insertGlobalTokenRateLimit,
  insertGroupTokenRateLimit,
  insertUserTokenRateLimit,
  updateTokenRateLimit,
} from "@/app/admin/token-rate-limits/lib";
import type { TokenRateLimitArgs } from "@/app/admin/token-rate-limits/types";

const tokenRateLimit: TokenRateLimitArgs = {
  enabled: true,
  token_budget: 1,
  period_hours: 24,
  cost_budget_cents: null,
};
const ERROR_DETAIL = "Database unavailable";

const mutationCases: [string, () => Promise<void>][] = [
  ["global create", () => insertGlobalTokenRateLimit(tokenRateLimit)],
  ["user create", () => insertUserTokenRateLimit(tokenRateLimit)],
  ["group create", () => insertGroupTokenRateLimit(tokenRateLimit, 1)],
  ["update", () => updateTokenRateLimit(1, tokenRateLimit)],
  ["delete", () => deleteTokenRateLimit(1)],
];

describe("token rate limit mutations", () => {
  const originalFetch = global.fetch;
  const fetchMock = jest.fn();

  beforeAll(() => {
    global.fetch = fetchMock;
  });

  afterEach(() => {
    fetchMock.mockReset();
  });

  afterAll(() => {
    global.fetch = originalFetch;
  });

  test.each(mutationCases)(
    "%s throws the backend detail",
    async (_, mutate) => {
      fetchMock.mockResolvedValue({
        ok: false,
        json: jest.fn().mockResolvedValue({ detail: ERROR_DETAIL }),
      } as unknown as Response);

      await expect(mutate()).rejects.toThrow(ERROR_DETAIL);
    }
  );

  test("resolves after a successful response", async () => {
    fetchMock.mockResolvedValue({ ok: true } as Response);

    await expect(
      insertGlobalTokenRateLimit(tokenRateLimit)
    ).resolves.toBeUndefined();
  });
});
