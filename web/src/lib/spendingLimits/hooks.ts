import useSWR from "swr";
import type { SelectOption } from "@opal/components";
import { useAdminLanguageModels } from "@/lib/languageModels/hooks";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  GroupSpendingLimitCards,
  SpendingLimitsResponse,
} from "@/lib/spendingLimits/types";

export function useSpendingLimits() {
  return useSWR<SpendingLimitsResponse>(
    SWR_KEYS.spendingLimits,
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError }
  );
}

/** Pass null to skip the fetch, e.g. for a caller who can't read the group. */
export function useGroupSpendingLimits(groupId: number | null) {
  return useSWR<GroupSpendingLimitCards>(
    groupId === null ? null : SWR_KEYS.groupSpendingLimits(groupId),
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError }
  );
}

/** Visible chat models across every provider, as select options keyed by
 *  model configuration id. */
export function useModelOptions(): SelectOption[] {
  const { llmProviders } = useAdminLanguageModels();
  return (llmProviders ?? []).flatMap((provider) =>
    provider.model_configurations
      .filter(
        (model) =>
          model.id !== undefined &&
          model.is_visible &&
          model.supports_chat !== false
      )
      .map((model) => ({
        value: String(model.id),
        title: model.effectiveDisplayName,
        description: provider.name ?? provider.provider,
      }))
  );
}
