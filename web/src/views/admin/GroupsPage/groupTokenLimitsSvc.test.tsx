import { saveTokenLimits } from "@/views/admin/GroupsPage/svc";

describe("group token-limit persistence", () => {
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

  test.each([
    [
      "token",
      { tokenBudget: 0, periodDays: 1, costBudgetDollars: null },
      { token_budget: 0, cost_budget_cents: null },
    ],
    [
      "cost",
      { tokenBudget: null, periodDays: 1, costBudgetDollars: 0 },
      { token_budget: null, cost_budget_cents: 0 },
    ],
  ])(
    "preserves an invalid zero %s budget for API validation",
    async (_, limit, expected) => {
      fetchMock.mockResolvedValue({ ok: true } as Response);

      await saveTokenLimits(7, [limit], []);

      const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/api/admin/token-rate-limits/user-group/7");
      expect(JSON.parse(String(options.body))).toEqual({
        enabled: true,
        ...expected,
        period_hours: 24,
      });
    }
  );

  test("preserves limit identity when a middle row is removed", async () => {
    fetchMock.mockResolvedValue({ ok: true } as Response);
    const existing = [
      {
        token_id: 10,
        enabled: true,
        token_budget: 100,
        period_hours: 24,
        cost_budget_cents: null,
      },
      {
        token_id: 20,
        enabled: false,
        token_budget: 200,
        period_hours: 24,
        cost_budget_cents: null,
      },
      {
        token_id: 30,
        enabled: true,
        token_budget: 300,
        period_hours: 24,
        cost_budget_cents: null,
      },
    ];

    await saveTokenLimits(
      7,
      [
        {
          tokenId: 10,
          enabled: true,
          tokenBudget: 100,
          periodDays: 1,
          costBudgetDollars: null,
        },
        {
          tokenId: 30,
          enabled: true,
          tokenBudget: 300,
          periodDays: 1,
          costBudgetDollars: null,
        },
      ],
      existing
    );

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/admin/token-rate-limits/user-group/7/rate-limit/10",
      "/api/admin/token-rate-limits/user-group/7/rate-limit/30",
      "/api/admin/token-rate-limits/user-group/7/rate-limit/20",
    ]);
    expect(
      fetchMock.mock.calls.map(([, options]) => (options as RequestInit).method)
    ).toEqual(["PUT", "PUT", "DELETE"]);
  });
});
