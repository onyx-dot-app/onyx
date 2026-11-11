import {
  LimitAction,
  PERIODS,
  type Period,
  type SpendingLimit,
  type SpendingLimitCard,
  type SpendingLimitRequest,
} from "@/lib/spendingLimits/types";

const CENTS_PER_DOLLAR = 100;
/** The API's largest token budget, in thousands of tokens. */
export const MAX_TOKEN_BUDGET_THOUSANDS = 1_000_000_000;

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

export type DraftLimitError =
  | "budgetRequired"
  | "budgetOutOfRange"
  | "modelRequired"
  | "duplicate";

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

function savedBucketOf(limit: SpendingLimit): string {
  return `${limit.model_configuration_id ?? "all"}:${limit.period}`;
}

/** Points each draft row at its row in a refetched card, so usage stays
 *  current while unsaved edits stay. A replace elsewhere gives the rows new
 *  ids, so a row is matched by id, then by bucket. Returns the same draft
 *  when nothing changed. */
export function withSavedFrom(
  draft: CardDraft,
  card: SpendingLimitCard
): CardDraft {
  const blocks = card.limits.filter(
    (limit) => limit.action === LimitAction.BLOCK
  );
  const byId = new Map(blocks.map((limit) => [limit.id, limit]));
  const byBucket = new Map(
    blocks.map((limit) => [savedBucketOf(limit), limit])
  );
  let changed = false;
  const limits = draft.limits.map((limit) => {
    const saved =
      limit.saved === null
        ? undefined
        : (byId.get(limit.saved.id) ??
          byBucket.get(savedBucketOf(limit.saved)));
    if (saved === undefined || saved === limit.saved) return limit;
    changed = true;
    return { ...limit, saved };
  });
  return changed ? { ...draft, limits } : draft;
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

/** The cents to send. An unedited budget goes back exactly as stored, so
 *  fractional cents survive a save. */
function costCents(limit: DraftLimit): number | null {
  if (limit.costDollars === null) return null;
  const saved = limit.saved?.cost_budget_cents ?? null;
  if (saved !== null && limit.costDollars === saved / CENTS_PER_DOLLAR) {
    return saved;
  }
  return Math.round(limit.costDollars * CENTS_PER_DOLLAR);
}

/** Budgets the API would reject: cost that rounds to zero cents, or tokens
 *  outside its range. */
function isBudgetOutOfRange(limit: DraftLimit): boolean {
  const cents = costCents(limit);
  const tokens = limit.tokenThousands;
  return (
    (cents !== null && cents <= 0) ||
    (tokens !== null && (tokens < 1 || tokens > MAX_TOKEN_BUDGET_THOUSANDS))
  );
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
    if (isBudgetOutOfRange(limit)) {
      errors.set(limit.key, "budgetOutOfRange");
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

function asRequest(limit: SpendingLimit): SpendingLimitRequest {
  return {
    period: limit.period,
    model_configuration_id: limit.model_configuration_id,
    token_budget: limit.token_budget,
    cost_budget_cents: limit.cost_budget_cents,
    action: limit.action,
    threshold_percent: limit.threshold_percent,
  };
}

export function toRequests(draft: CardDraft): SpendingLimitRequest[] {
  return [
    ...draft.limits.map((limit) => ({
      period: limit.period,
      model_configuration_id: limit.isModelRow
        ? limit.modelConfigurationId
        : null,
      token_budget: limit.tokenThousands,
      cost_budget_cents: costCents(limit),
      action: LimitAction.BLOCK,
      threshold_percent: null,
    })),
    ...draft.alertLimits.map(asRequest),
  ];
}

/** What the card stores, without usage or reset times. It changes only when
 *  the stored limits change, not on every refetch. */
export function cardSignature(card: SpendingLimitCard): string {
  return JSON.stringify([card.enabled, card.limits.map(asRequest)]);
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
