"use client";

import useSWR from "swr";
import type { ScopedMutator } from "swr";
import { errorHandlingFetcher, parseErrorDetail } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  CostOverride,
  CostOverrideCreate,
  CostOverrideUpdate,
} from "@/lib/languageModels/types";

/**
 * Lists existing cost overrides via `GET /api/admin/cost-overrides` (admin).
 * Mutate `SWR_KEYS.costOverrides` after a write to revalidate.
 */
export function useCostOverrides() {
  const { data, error, isLoading, mutate } = useSWR<CostOverride[]>(
    SWR_KEYS.costOverrides,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );

  return {
    costOverrides: data,
    isLoading,
    error,
    refetch: mutate,
  };
}

async function sendOverride(
  url: string,
  method: "POST" | "PUT",
  body: CostOverrideCreate | CostOverrideUpdate
): Promise<CostOverride> {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error(await parseErrorDetail(response, response.statusText));
  }

  return response.json();
}

/**
 * Creates an override for a model configuration that has none.
 * @throws Error with the API detail message on failure, including a 409 when
 * the configuration already has an override.
 */
export async function createCostOverride(
  body: CostOverrideCreate
): Promise<CostOverride> {
  return sendOverride(SWR_KEYS.costOverrides, "POST", body);
}

/**
 * Sets an existing override's rates, and moves it to `body.model_configuration_id`
 * when that is another model.
 * @throws Error with the API detail message on failure, including a 409 when
 * the target model already has an override.
 */
export async function updateCostOverride(
  modelConfigurationId: number,
  body: CostOverrideUpdate
): Promise<CostOverride> {
  return sendOverride(
    `${SWR_KEYS.costOverrides}/${modelConfigurationId}`,
    "PUT",
    body
  );
}

/**
 * Deletes a model configuration's override. A 404 (already gone) is swallowed —
 * the caller's intent (override absent) is satisfied either way.
 * @throws Error with the API detail message on non-404 failures.
 */
export async function deleteCostOverride(
  modelConfigurationId: number
): Promise<void> {
  const response = await fetch(
    `${SWR_KEYS.costOverrides}/${modelConfigurationId}`,
    { method: "DELETE" }
  );

  if (response.ok || response.status === 404) {
    return;
  }

  throw new Error(await parseErrorDetail(response, response.statusText));
}

/** Revalidate the overrides list after a mutation. */
export async function refreshCostOverrides(
  mutate: ScopedMutator
): Promise<void> {
  await mutate(SWR_KEYS.costOverrides);
}
