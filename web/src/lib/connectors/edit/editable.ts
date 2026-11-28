import { connectorConfigs } from "@/lib/connectors/connectors";
import type { ConfigurableSources } from "@/lib/connectors/types/source";

/**
 * Whether the create form, and so the edit form, supports the source. Built-in
 * pairs such as the Ingestion API have no form.
 */
export function isEditableSource(
  source: string
): source is ConfigurableSources {
  return Object.hasOwn(connectorConfigs, source);
}
