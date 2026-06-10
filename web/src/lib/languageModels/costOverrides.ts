"use client";

import useSWR from "swr";
import type { ScopedMutator } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";

/**
 * Admin-set negotiated per-model rate, overriding the built-in price book.
 * Rates are USD per MILLION tokens. Keyed on (provider, model); provider is ""
 * for a provider-agnostic override.
 */
export interface CostOverride {
  model: string;
  provider: string;
  input_cost_per_mtok: number;
  output_cost_per_mtok: number;
  cache_read_cost_per_mtok: number | null; // null = bill cache at the input rate
  updated_at: string | null;
}

/** PUT body — an idempotent upsert keyed on (provider, model). */
export interface CostOverrideUpsert {
  model: string;
  provider?: string; // "" / omitted = provider-agnostic
  input_cost_per_mtok: number;
  output_cost_per_mtok: number;
  cache_read_cost_per_mtok: number | null;
}

/**
 * Lists existing cost overrides via `GET /api/admin/cost-overrides` (admin).
 * Mutate `SWR_KEYS.costOverrides` after a write to revalidate.
 */
export function useCostOverrides() {
  const { data, error, isLoading, mutate } = useSWR<CostOverride[]>(
    SWR_KEYS.costOverrides,
    errorHandlingFetcher,
    { revalidateOnFocus: false },
  );

  return {
    costOverrides: data,
    isLoading,
    error,
    refetch: mutate,
  };
}

/**
 * Upserts a cost override. PUT is idempotent — re-sending an existing model
 * updates its rates rather than erroring.
 * @throws Error with the API detail message on failure.
 */
export async function upsertCostOverride(
  body: CostOverrideUpsert,
): Promise<CostOverride> {
  const response = await fetch(SWR_KEYS.costOverrides, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error(await extractError(response));
  }

  return response.json();
}

/**
 * Deletes a cost override by model name. A 404 (already gone) is swallowed —
 * the caller's intent (override absent) is satisfied either way.
 * @throws Error with the API detail message on non-404 failures.
 */
export async function deleteCostOverride(
  model: string,
  provider: string = "",
): Promise<void> {
  // Keep "/" as real path separators (backend route is {model:path}) but encode
  // each segment, so slash-containing model ids (e.g. "bedrock/...") delete.
  const encodedModel = model
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  const query = provider ? `?provider=${encodeURIComponent(provider)}` : "";
  const response = await fetch(
    `${SWR_KEYS.costOverrides}/${encodedModel}${query}`,
    { method: "DELETE" },
  );

  if (response.ok || response.status === 404) {
    return;
  }

  throw new Error(await extractError(response));
}

/** Revalidate the overrides list after a mutation. */
export async function refreshCostOverrides(
  mutate: ScopedMutator,
): Promise<void> {
  await mutate(SWR_KEYS.costOverrides);
}

/** Pull the backend's `detail`/`error_code`, falling back to the status text. */
async function extractError(response: Response): Promise<string> {
  try {
    const data = await response.json();
    return data.detail || data.error_code || response.statusText;
  } catch {
    return response.statusText;
  }
}
