import isEqual from "lodash/isEqual";
import { toWireAccess } from "@/lib/connectors/accessType";
import type {
  CCPairFullInfo,
  ConnectionConfiguration,
  ConnectorValueField,
  TabOption,
} from "@/lib/connectors/types";
import type {
  ConfigurableSources,
  ValidSources,
} from "@/lib/connectors/types/source";
import {
  connectorConfigFromForm,
  connectorFormControlFieldNames,
  createConnectorInitialValues,
} from "@/lib/connectors/utils";
import { NEW_ACCOUNT_FIELD } from "@/views/admin/connectors/AddConnectorPage/newAccount";
import type { AccessType } from "@/lib/types";
import type { ConnectorEditProposal } from "@/lib/connectors/edit/types";

export type ConnectorFormValues = ReturnType<
  typeof createConnectorInitialValues
>;

/** Access types whose data-access groups decide who reads the documents. */
export function usesDataAccessGroups(accessType: AccessType): boolean {
  return accessType === "private" || accessType === "sync_restricted";
}

// The API sends dates as strings, although the type says `Date`.
function isoOf(value: Date | string | null): string | null {
  if (value === null) return null;
  return value instanceof Date ? value.toISOString() : value;
}

/** Whether the stored config holds a non-empty value for the field. */
function storesValue(config: Record<string, unknown>, name: string): boolean {
  const value = config[name];
  if (value === null || value === undefined || value === "") return false;
  return !Array.isArray(value) || value.length > 0;
}

/**
 * The tab whose fields hold stored values. With none, a tab that takes no
 * input (e.g. "Everything"), else the form's default tab.
 */
function tabFor(
  field: TabOption,
  config: Record<string, unknown>
): string | null {
  const stored = config[field.name];
  if (typeof stored === "string") return stored;
  const withValues = field.tabs.find((option) =>
    option.fields.some((tabField) => storesValue(config, tabField.name))
  );
  const withoutInput = field.tabs.find((option) =>
    option.fields.every((tabField) => tabField.type === "string_tab")
  );
  return (withValues ?? withoutInput)?.value ?? null;
}

function tabValues(
  fields: (ConnectorValueField | TabOption)[],
  config: Record<string, unknown>
): Record<string, string> {
  const values: Record<string, string> = {};
  for (const field of fields) {
    if (field.type !== "tab") continue;
    const tab = tabFor(field, config);
    if (tab !== null) values[field.name] = tab;
  }
  return values;
}

/**
 * The form's reader settings for the pair's access. A private pair's readers
 * are its data-access groups; a sync-restricted pair is "sync" with the
 * restriction on. The manage groups are not part of an edit.
 */
function accessValues(
  accessType: AccessType,
  dataAccessGroupIds: number[]
): Pick<
  ConnectorFormValues,
  | "access_type"
  | "data_access_group_ids"
  | "restrict_access_to_groups"
  | "restriction_group_ids"
> {
  if (accessType === "sync_restricted") {
    return {
      access_type: "sync",
      data_access_group_ids: [],
      restrict_access_to_groups: true,
      restriction_group_ids: dataAccessGroupIds,
    };
  }
  return {
    access_type: accessType,
    data_access_group_ids: accessType === "private" ? dataAccessGroupIds : [],
    restrict_access_to_groups: false,
    restriction_group_ids: [],
  };
}

/**
 * The create form's values for the pair's current state: the stored config
 * over the form defaults, the pair's name, schedule and access, and the tab
 * that holds the stored values.
 */
export function editInitialValues(
  source: ConfigurableSources,
  configuration: ConnectionConfiguration,
  ccPair: CCPairFullInfo,
  dataAccessGroupIds: number[]
): ConnectorFormValues {
  const config: Record<string, unknown> =
    ccPair.connector.connector_specific_config ?? {};
  const { refresh_freq, prune_freq, indexing_start } = ccPair.connector;
  const indexingStart = isoOf(indexing_start);
  return {
    ...createConnectorInitialValues(source),
    ...tabValues(
      [...configuration.values, ...configuration.advanced_values],
      config
    ),
    ...config,
    ...accessValues(ccPair.access_type, dataAccessGroupIds),
    name: ccPair.name,
    refreshFreq: refresh_freq === null ? undefined : refresh_freq / 60,
    pruneFreq: prune_freq === null ? undefined : prune_freq / 3600,
    // The date picker holds "YYYY-MM-DD".
    indexingStart: indexingStart === null ? "" : indexingStart.slice(0, 10),
  };
}

export interface EditProposalInput {
  values: ConnectorFormValues;
  /** The values `editInitialValues` gave the form. */
  initialValues: ConnectorFormValues;
  configuration: ConnectionConfiguration;
  ccPair: CCPairFullInfo;
  credentialId: number;
}

/**
 * The config to propose: the config the create form would send, with each
 * value the admin did not change taken from the stored config. A form
 * default for a key the stored config lacks is left out. So an unchanged
 * form proposes the stored config exactly.
 */
function proposedConfig({
  values,
  initialValues,
  configuration,
  ccPair,
}: EditProposalInput): Record<string, unknown> {
  const stored: Record<string, unknown> =
    ccPair.connector.connector_specific_config ?? {};
  const source = ccPair.connector.source;
  const built = formConfig(source, values, configuration);
  const builtInitial = formConfig(source, initialValues, configuration);
  const config: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(built)) {
    const unchanged = isEqual(value, builtInitial[key]);
    if (!unchanged) {
      config[key] = value;
    } else if (Object.hasOwn(stored, key)) {
      config[key] = stored[key];
    }
  }
  return config;
}

/** Create-form values that the create request sends outside the config. */
const NON_CONFIG_FORM_KEYS: ReadonlySet<string> = new Set([
  "name",
  "groups",
  "group_roles",
  "data_access_group_ids",
  "access_type",
  "restrict_access_to_groups",
  "restriction_group_ids",
  "pruneFreq",
  "indexingStart",
  "refreshFreq",
  "auto_sync_options",
]);

/** The config the create form would send for these values. */
function formConfig(
  source: ValidSources,
  values: ConnectorFormValues,
  configuration: ConnectionConfiguration
): Record<string, unknown> {
  const configValues = Object.fromEntries(
    Object.entries(values).filter(([key]) => !NON_CONFIG_FORM_KEYS.has(key))
  );
  return connectorConfigFromForm(
    source,
    configuration,
    configValues,
    connectorFormControlFieldNames(configuration, [NEW_ACCOUNT_FIELD])
  );
}

function sortedUnique(ids: number[]): number[] {
  return Array.from(new Set(ids)).sort((a, b) => a - b);
}

/** The data-access groups of the form's access settings. */
function proposedDataAccessGroupIds(values: ConnectorFormValues): number[] {
  const wire = toWireAccess(values.access_type, {
    restrict_access_to_groups: values.restrict_access_to_groups,
    restriction_group_ids: values.restriction_group_ids,
  });
  if (wire.access_type === "sync_restricted") {
    return sortedUnique(wire.restriction_group_ids);
  }
  return wire.access_type === "private"
    ? sortedUnique(values.data_access_group_ids)
    : [];
}

function proposedSeconds(
  value: number | undefined,
  initial: number | undefined,
  stored: number | null,
  secondsPerUnit: number
): number | null {
  if (value === initial) return stored;
  // The backend stores whole seconds; empty takes the default.
  return value === undefined ? null : Math.round(value * secondsPerUnit);
}

function proposedIndexingStart(
  value: string | undefined,
  initial: string | undefined,
  stored: Date | string | null
): string | null {
  if (value === initial) return isoOf(stored);
  // As at creation: the picked day at midnight UTC.
  return value ? new Date(value).toISOString() : null;
}

/** The plan request for the edited form: the pair's full proposed state. */
export function buildEditProposal(
  input: EditProposalInput
): ConnectorEditProposal {
  const { values, initialValues, ccPair, credentialId } = input;
  const wire = toWireAccess(values.access_type, {
    restrict_access_to_groups: values.restrict_access_to_groups,
    restriction_group_ids: values.restriction_group_ids,
  });
  return {
    connector_specific_config: proposedConfig(input),
    access_type: wire.access_type,
    data_access_group_ids: proposedDataAccessGroupIds(values),
    credential_id: credentialId,
    indexing_start: proposedIndexingStart(
      values.indexingStart,
      initialValues.indexingStart,
      ccPair.connector.indexing_start
    ),
    name: values.name,
    refresh_freq: proposedSeconds(
      values.refreshFreq,
      initialValues.refreshFreq,
      ccPair.connector.refresh_freq,
      60
    ),
    prune_freq: proposedSeconds(
      values.pruneFreq,
      initialValues.pruneFreq,
      ccPair.connector.prune_freq,
      3600
    ),
  };
}
