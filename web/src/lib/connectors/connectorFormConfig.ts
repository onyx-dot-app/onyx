import type { ConnectionConfiguration } from "@/lib/connectors/types";

/** Create-form values that the create request sends outside the config. */
const NON_CONFIG_FORM_KEYS: ReadonlySet<string> = new Set([
  "name",
  "groups",
  "access_type",
  "restrict_access_to_groups",
  "restriction_group_ids",
  "pruneFreq",
  "indexingStart",
  "refreshFreq",
  "auto_sync_options",
]);

function isString<T>(item: T): item is T & string {
  return typeof item === "string";
}

function withoutBlankStrings<T>(items: readonly T[]): T[] {
  return items.filter((item) => typeof item !== "string" || item.trim() !== "");
}

/**
 * The `connector_specific_config` that the create form sends for its values.
 * The capability-check draft runs send the same object, so that creation can
 * reuse their results.
 *
 * Tab controls are left out, empty strings are removed from lists, and a
 * top-level field's `transform` is applied.
 */
export function buildConnectorSpecificConfig(
  values: Record<string, unknown>,
  configuration: ConnectionConfiguration
): Record<string, unknown> {
  const formControlFieldNames = new Set(
    [...configuration.values, ...configuration.advanced_values]
      .filter((field) => field.type === "tab")
      .map((field) => field.name)
  );
  const config: Record<string, unknown> = {};
  for (const [key, rawValue] of Object.entries(values)) {
    if (NON_CONFIG_FORM_KEYS.has(key) || formControlFieldNames.has(key)) {
      continue;
    }
    const value = Array.isArray(rawValue)
      ? withoutBlankStrings(rawValue)
      : rawValue;
    const field = configuration.values.find((option) => option.name === key);
    if (
      field !== undefined &&
      field.type === "list" &&
      field.transform &&
      Array.isArray(value)
    ) {
      config[key] = field.transform(value.filter(isString));
    } else {
      config[key] = value;
    }
  }
  return config;
}
