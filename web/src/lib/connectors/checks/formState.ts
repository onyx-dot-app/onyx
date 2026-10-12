import type { ConnectionConfiguration } from "@/lib/connectors/types";

type ConfigField = ConnectionConfiguration["values"][number];

/** Every config field name, tab contents included; tab selectors are form
 * controls, not config. */
function configFieldNames(fields: ConfigField[]): string[] {
  return fields.flatMap((field) =>
    field.type === "tab"
      ? field.tabs.flatMap((tab) => configFieldNames(tab.fields))
      : [field.name]
  );
}

/**
 * The connector config an unsaved form holds, for a draft check run. It
 * takes only the configuration's own fields, and drops blank list entries
 * as the create request does.
 */
export function connectorFormState(
  configuration: ConnectionConfiguration,
  values: Record<string, unknown>
): Record<string, unknown> {
  const names: string[] = configFieldNames([
    ...configuration.values,
    ...configuration.advanced_values,
  ]);
  return Object.fromEntries(
    names
      .filter((name) => values[name] !== undefined)
      .map((name) => {
        const value: unknown = values[name];
        return [
          name,
          Array.isArray(value)
            ? value.filter(
                (item) => typeof item !== "string" || item.trim() !== ""
              )
            : value,
        ];
      })
  );
}
