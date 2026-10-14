import {
  BuildLlmSelection,
  getDefaultLlmSelection,
  MinimalLlmProvider,
  providerHasVisibleModel,
  toLlmSelection,
} from "@/app/craft/onboarding/constants";
import { DefaultModel } from "@/lib/languageModels/types";
import {
  readStorageItem,
  writeStorageItem,
} from "@/app/craft/utils/localStorage";

// Model-picker preferences are keyed per user (mirroring the onboarding-seen
// flag) so picks don't leak across accounts on a shared browser. Without a
// user id, reads fall back to defaults and writes are dropped.

function llmSelectionKey(userId: string): string {
  return `onyx:craftLlmSelection:${userId}`;
}

function recommendedOnlyKey(userId: string): string {
  return `onyx:craftRecommendedModelsOnly:${userId}`;
}

export function getStoredRecommendedModelsOnly(
  userId: string | undefined
): boolean {
  if (!userId) return true;
  return readStorageItem(recommendedOnlyKey(userId)) !== "false";
}

export function setStoredRecommendedModelsOnly(
  userId: string | undefined,
  value: boolean
): void {
  if (!userId) return;
  writeStorageItem(recommendedOnlyKey(userId), String(value));
}

export function setStoredLlmSelection(
  userId: string | undefined,
  selection: BuildLlmSelection
): void {
  if (!userId) return;
  writeStorageItem(llmSelectionKey(userId), JSON.stringify(selection));
}

function getStoredLlmSelection(
  userId: string,
  llmProviders: MinimalLlmProvider[]
): BuildLlmSelection | null {
  const raw = readStorageItem(llmSelectionKey(userId));
  if (!raw) return null;
  let stored: unknown;
  try {
    stored = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof stored !== "object" || stored === null) return null;
  const { providerId, provider, modelName } =
    stored as Partial<BuildLlmSelection>;
  if (typeof modelName !== "string") return null;
  // Only honor the stored pick if it's still among the user's options.
  const match = llmProviders.find(
    (candidate) =>
      candidate.id === providerId &&
      candidate.provider === provider &&
      providerHasVisibleModel(candidate, modelName)
  );
  return match ? toLlmSelection(match, modelName) : null;
}

// The user's last pick when still available, else the workspace default.
export function getPreferredLlmSelection(
  userId: string | undefined,
  llmProviders: MinimalLlmProvider[] | undefined,
  configuredDefaults: (DefaultModel | null | undefined)[] = []
): BuildLlmSelection | null {
  if (!llmProviders) return null;
  return (
    (userId ? getStoredLlmSelection(userId, llmProviders) : null) ??
    getDefaultLlmSelection(llmProviders, configuredDefaults)
  );
}
