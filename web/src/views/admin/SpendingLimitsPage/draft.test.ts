import {
  LimitAction,
  Period,
  type SpendingLimit,
  type SpendingLimitCard,
} from "@/lib/spendingLimits/types";
import {
  emptyDraftLimit,
  isDraftDirty,
  toCardDraft,
  toRequests,
  validateDraft,
} from "@/views/admin/SpendingLimitsPage/draft";

function limit(overrides: Partial<SpendingLimit>): SpendingLimit {
  return {
    id: 1,
    period: Period.DAILY,
    model_configuration_id: null,
    model_name: null,
    token_budget: null,
    cost_budget_cents: 500,
    action: LimitAction.BLOCK,
    threshold_percent: null,
    reset_at: "2026-11-01T00:00:00+00:00",
    used_tokens: null,
    used_cost_cents: null,
    ...overrides,
  };
}

const card: SpendingLimitCard = {
  enabled: true,
  limits: [
    limit({ id: 1 }),
    limit({
      id: 2,
      period: Period.MONTHLY,
      model_configuration_id: 7,
      model_name: "Opus",
      cost_budget_cents: null,
      token_budget: 100,
    }),
    limit({
      id: 3,
      action: LimitAction.ALERT_ONLY,
      cost_budget_cents: null,
      threshold_percent: 80,
    }),
  ],
};

test("a card round-trips through its draft unchanged, alert rows included", () => {
  const draft = toCardDraft(card);

  expect(draft.limits.map((l) => l.isModelRow)).toEqual([false, true]);
  expect(draft.limits[0]!.costDollars).toBe(5);
  expect(draft.alertLimits.map((l) => l.id)).toEqual([3]);
  expect(isDraftDirty(draft, card)).toBe(false);
  expect(toRequests(draft)).toEqual([
    {
      period: Period.DAILY,
      model_configuration_id: null,
      token_budget: null,
      cost_budget_cents: 500,
      action: LimitAction.BLOCK,
      threshold_percent: null,
    },
    {
      period: Period.MONTHLY,
      model_configuration_id: 7,
      token_budget: 100,
      cost_budget_cents: null,
      action: LimitAction.BLOCK,
      threshold_percent: null,
    },
    {
      period: Period.DAILY,
      model_configuration_id: null,
      token_budget: null,
      cost_budget_cents: null,
      action: LimitAction.ALERT_ONLY,
      threshold_percent: 80,
    },
  ]);
});

test("validation flags a missing budget, a missing model and a reused period", () => {
  const draft = toCardDraft(card);
  const noBudget = { ...emptyDraftLimit(false, draft.limits) };
  const noModel = { ...emptyDraftLimit(true, draft.limits), costDollars: 1 };
  const duplicate = { ...draft.limits[0]!, key: 999 };
  const errors = validateDraft({
    ...draft,
    limits: [...draft.limits, noBudget, noModel, duplicate],
  });

  expect(errors.get(noBudget.key)).toBe("budgetRequired");
  expect(errors.get(noModel.key)).toBe("modelRequired");
  expect(errors.get(duplicate.key)).toBe("duplicate");
  expect(errors.size).toBe(3);
});

test("a new all-models limit takes the first period not already used", () => {
  const draft = toCardDraft(card);

  expect(emptyDraftLimit(false, draft.limits).period).toBe(Period.WEEKLY);
});

test("toggling the card or editing a budget makes the draft dirty", () => {
  const draft = toCardDraft(card);

  expect(isDraftDirty({ ...draft, enabled: false }, card)).toBe(true);
  expect(
    isDraftDirty(
      {
        ...draft,
        limits: [{ ...draft.limits[0]!, costDollars: 6 }, draft.limits[1]!],
      },
      card
    )
  ).toBe(true);
});
