import type { ConnectionConfiguration } from "@/lib/connectors/types";
import type { ValidSources } from "@/lib/connectors/types/source";
import { listConfigValue, withoutFormOnlyFields } from "@/lib/connectors/utils";

type ConfigField = ConnectionConfiguration["values"][number];
type ConfigValueField = Exclude<ConfigField, { type: "tab" }>;

/** Every config field, tab contents included. Tab selectors are form
 * controls, not config. */
export function configFields(fields: ConfigField[]): ConfigValueField[] {
  return fields.flatMap((field) =>
    field.type === "tab"
      ? field.tabs.flatMap((tab) => configFields(tab.fields))
      : [field]
  );
}

function configFieldNames(fields: ConfigField[]): string[] {
  return configFields(fields).map((field) => field.name);
}

/**
 * The connector config an unsaved form holds, for a draft check run or plan.
 * It takes only the configuration's own fields without the form-only ones
 * (the realm), and drops blank list entries as the create request does.
 */
export function connectorFormState(
  source: ValidSources,
  configuration: ConnectionConfiguration,
  values: Record<string, unknown>
): Record<string, unknown> {
  const names: string[] = configFieldNames([
    ...configuration.values,
    ...configuration.advanced_values,
  ]);
  const state: Record<string, unknown> = Object.fromEntries(
    names
      .filter((name) => values[name] !== undefined)
      .map((name) => {
        const value: unknown = values[name];
        if (!Array.isArray(value)) return [name, value];
        const entries = value.filter(
          (item) => typeof item !== "string" || item.trim() !== ""
        );
        return [
          name,
          entries.every((entry): entry is string => typeof entry === "string")
            ? listConfigValue(configuration, name, entries)
            : entries,
        ];
      })
  );
  return withoutFormOnlyFields(source, state);
}
