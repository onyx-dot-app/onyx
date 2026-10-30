import {
  LimitAction,
  PERIODS,
  type Period,
  type SpendingLimit,
  type SpendingLimitCard,
  type SpendingLimitRequest,
} from "@/lib/spendingLimits/types";

const CENTS_PER_DOLLAR = 100;

/** One editable BLOCK limit. Budgets are in the units the inputs show:
 *  dollars, and thousands of tokens. */
export interface DraftLimit {
  key: number;
  period: Period;
  /** null on an all-models row; on a model row, null until a model is picked. */
  modelConfigurationId: number | null;
  isModelRow: boolean;
  costDollars: number | null;
  tokenThousands: number | null;
  /** The saved row, for its usage and next reset. */
  saved: SpendingLimit | null;
}

export interface CardDraft {
  enabled: boolean;
  limits: DraftLimit[];
  /** Kept as loaded and sent back on save: the page can't edit them yet. */
  alertLimits: SpendingLimit[];
}

export type DraftLimitError = "budgetRequired" | "modelRequired" | "duplicate";

let nextKey = 0;

export function newDraftKey(): number {
  nextKey += 1;
  return nextKey;
}

export function toCardDraft(card: SpendingLimitCard): CardDraft {
  return {
    enabled: card.enabled,
    limits: card.limits
      .filter((limit) => limit.action === LimitAction.BLOCK)
      .map((limit) => ({
        key: newDraftKey(),
        period: limit.period,
        modelConfigurationId: limit.model_configuration_id,
        isModelRow: limit.model_configuration_id !== null,
        costDollars:
          limit.cost_budget_cents === null
            ? null
            : limit.cost_budget_cents / CENTS_PER_DOLLAR,
        tokenThousands: limit.token_budget,
        saved: limit,
      })),
    alertLimits: card.limits.filter(
      (limit) => limit.action === LimitAction.ALERT_ONLY
    ),
  };
}

export function emptyDraftLimit(
  isModelRow: boolean,
  used: DraftLimit[]
): DraftLimit {
  // An all-models row takes the first period no other all-models row uses.
  const taken = new Set(
    used.filter((limit) => !limit.isModelRow).map((limit) => limit.period)
  );
  const period = isModelRow
    ? PERIODS[PERIODS.length - 1]!
    : (PERIODS.find((p) => !taken.has(p)) ?? PERIODS[0]!);
  return {
    key: newDraftKey(),
    period,
    modelConfigurationId: null,
    isModelRow,
    costDollars: null,
    tokenThousands: null,
    saved: null,
  };
}

function bucketOf(limit: DraftLimit): string {
  return `${limit.modelConfigurationId ?? "all"}:${limit.period}`;
}

/** Errors keyed by draft key; an empty map means the card can be saved. */
export function validateDraft(draft: CardDraft): Map<number, DraftLimitError> {
  const errors = new Map<number, DraftLimitError>();
  const seen = new Set<string>();
  for (const limit of draft.limits) {
    if (limit.isModelRow && limit.modelConfigurationId === null) {
      errors.set(limit.key, "modelRequired");
      continue;
    }
    if (limit.costDollars === null && limit.tokenThousands === null) {
      errors.set(limit.key, "budgetRequired");
      continue;
    }
    const bucket = bucketOf(limit);
    if (seen.has(bucket)) {
      errors.set(limit.key, "duplicate");
      continue;
    }
    seen.add(bucket);
  }
  return errors;
}

export function toRequests(draft: CardDraft): SpendingLimitRequest[] {
  return [
    ...draft.limits.map((limit) => ({
      period: limit.period,
      model_configuration_id: limit.isModelRow
        ? limit.modelConfigurationId
        : null,
      token_budget: limit.tokenThousands,
      cost_budget_cents:
        limit.costDollars === null
          ? null
          : Math.round(limit.costDollars * CENTS_PER_DOLLAR),
      action: LimitAction.BLOCK,
      threshold_percent: null,
    })),
    ...draft.alertLimits.map((limit) => ({
      period: limit.period,
      model_configuration_id: limit.model_configuration_id,
      token_budget: limit.token_budget,
      cost_budget_cents: limit.cost_budget_cents,
      action: limit.action,
      threshold_percent: limit.threshold_percent,
    })),
  ];
}

/** Whether saving the draft would change the card. */
export function isDraftDirty(
  draft: CardDraft,
  card: SpendingLimitCard
): boolean {
  const asSent = (requests: SpendingLimitRequest[]) =>
    JSON.stringify(
      requests.map((request) => [
        request.period,
        request.model_configuration_id,
        request.token_budget,
        request.cost_budget_cents,
        request.action,
        request.threshold_percent,
      ])
    );
  return (
    draft.enabled !== card.enabled ||
    asSent(toRequests(draft)) !== asSent(toRequests(toCardDraft(card)))
  );
}
