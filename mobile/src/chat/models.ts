/*
 * The `GET /llm/persona/{id}/providers` contract and the logic for turning it into picker rows,
 * mirroring the part of web/src/lib/languageModels/options.ts that mobile needs.
 *
 * These types cover only the fields the picker and the send path read. The endpoint returns more
 * per model — reasoning efforts, token limits, temperature defaults — that mobile has no UI for.
 */
export interface ModelConfiguration {
  // Null for a model the admin never saved a configuration row for. Such a model can still be
  // sent, just by name rather than by the preferred id.
  id: number | null;
  name: string;
  is_visible: boolean;
  display_name: string | null;
  custom_display_name: string | null;
}

export interface LlmProvider {
  id: number;
  // `name` is the admin's label for this provider instance, `provider` is the vendor slug like
  // "openai". The send body's `model_provider` carries the label, not the slug.
  name: string | null;
  provider: string;
  provider_display_name: string;
  model_configurations: ModelConfiguration[];
}

// The backend names the default by provider + model name, never by model_configuration_id, so
// resolving it back to an option means matching both.
export interface DefaultModel {
  provider_id: number;
  model_name: string;
}

export interface LlmProvidersResponse {
  providers: LlmProvider[];
  default_text: DefaultModel | null;
}

export interface ModelOption {
  // Preferred key for the send body; the backend treats it as authoritative because provider
  // display names aren't unique.
  modelConfigurationId: number | null;
  modelProvider: string;
  modelVersion: string;
  providerDisplayName: string;
  displayName: string;
}

export interface LlmOverride {
  model_configuration_id: number | null;
  model_provider: string;
  model_version: string;
}

export interface ModelOptionGroup {
  providerDisplayName: string;
  options: ModelOption[];
}

function effectiveDisplayName(model: ModelConfiguration): string {
  return model.custom_display_name || model.display_name || model.name;
}

/*
 * The endpoint does not pre-filter on `is_visible`, so the client has to. `currentModelName` is
 * kept whatever its visibility, or a model the admin has since hidden would vanish from the
 * picker while still being the one in use, leaving nothing selected.
 */
export function buildModelOptions(
  providers: LlmProvider[],
  currentModelName?: string,
): ModelOption[] {
  const seen = new Set<string>();
  const options: ModelOption[] = [];

  for (const provider of providers) {
    for (const model of provider.model_configurations) {
      if (!model.is_visible && model.name !== currentModelName) continue;
      const key =
        model.id != null
          ? `id:${model.id}`
          : `${provider.provider}:${model.name}`;
      if (seen.has(key)) continue;
      seen.add(key);

      options.push({
        modelConfigurationId: model.id,
        modelProvider: provider.name ?? "",
        modelVersion: model.name,
        providerDisplayName: provider.name || provider.provider_display_name,
        displayName: effectiveDisplayName(model),
      });
    }
  }

  return options;
}

export function groupModelOptions(options: ModelOption[]): ModelOptionGroup[] {
  const groups: ModelOptionGroup[] = [];
  for (const option of options) {
    const existing = groups.find(
      (group) => group.providerDisplayName === option.providerDisplayName,
    );
    if (existing) existing.options.push(option);
    else
      groups.push({
        providerDisplayName: option.providerDisplayName,
        options: [option],
      });
  }
  return groups;
}

export function resolveDefaultOption(
  providers: LlmProvider[],
  defaultText: DefaultModel | null,
  options: ModelOption[],
): ModelOption | null {
  if (!defaultText) return null;
  const provider = providers.find(
    (candidate) => candidate.id === defaultText.provider_id,
  );
  if (!provider) return null;
  return (
    options.find(
      (option) =>
        option.modelVersion === defaultText.model_name &&
        option.modelProvider === (provider.name ?? ""),
    ) ?? null
  );
}

export function isSameModelOption(a: ModelOption, b: ModelOption): boolean {
  if (a.modelConfigurationId != null || b.modelConfigurationId != null) {
    return a.modelConfigurationId === b.modelConfigurationId;
  }
  return (
    a.modelProvider === b.modelProvider && a.modelVersion === b.modelVersion
  );
}

export function toLlmOverride(option: ModelOption): LlmOverride {
  return {
    model_configuration_id: option.modelConfigurationId,
    model_provider: option.modelProvider,
    model_version: option.modelVersion,
  };
}
