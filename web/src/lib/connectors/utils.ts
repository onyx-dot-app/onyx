import * as Yup from "yup";
import {
  SOURCE_METADATA_MAP,
  type PartialSourceMetadata,
} from "@/lib/connectors/constants";
import {
  type SourceMetadata,
  ValidSources,
  type ConfigurableSources,
} from "@/lib/connectors/types/source";
import type {
  ConnectorAccessFormValues,
  ConnectorGroupRestrictionFormValues,
} from "@/lib/connectors/accessType";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  connectorConfigs,
  MIN_PRUNE_FREQ_HOURS,
  MIN_REFRESH_FREQ_MINUTES,
} from "@/lib/connectors/connectors";
import credentialBoundFields from "@/lib/connectors/credentialBoundFields.json";
import { getCredentialSpec, realmFields } from "@/lib/credentials/utils";
import { FILE_TYPE_DEFINITIONS, TypedFile } from "@/lib/connectors/fileTypes";
import {
  ConnectorCredentialPairStatus,
  FileTypeCategory,
  OneDriveScope,
} from "@/lib/connectors/types";
import type {
  ConnectionConfiguration,
  GmailConfig,
} from "@/lib/connectors/types";

// ---------------------------------------------------------------------------
// Connector configuration
// ---------------------------------------------------------------------------

export function isLoadState(connector_name: string): boolean {
  // TODO: centralize connector metadata like this somewhere instead of hardcoding it here
  const loadStateConnectors = ["web", "xenforo", "file", "airtable"];
  if (loadStateConnectors.includes(connector_name)) {
    return true;
  }

  return false;
}

type ConnectorField = ConnectionConfiguration["values"][number];

/** A connector form's fields, split by whether they are bound to the credential. */
export interface CredentialBoundFieldSplit {
  /** The bound fields of `values`, in their order. */
  values: ConnectorField[];
  /** The bound fields of `advanced_values`, in their order. */
  advancedValues: ConnectorField[];
  /** The configuration without the bound fields. */
  rest: ConnectionConfiguration;
}

/**
 * Source to the names of its credential-bound fields: the fields of the
 * backend `CredentialBinding` model, whose valid values depend on the account
 * behind the credential. `backend/scripts/generate_credential_bound_fields.py`
 * writes the file, and a backend test keeps it equal to the models.
 */
const CREDENTIAL_BOUND_FIELDS: Partial<Record<ValidSources, string[]>> =
  credentialBoundFields;

/**
 * The source's form-only fields: the account's realm (its site, host or
 * subdomain), one per realm field of the credential spec, under the same key.
 * The realm lives in the credential only. The form uses it to filter the saved
 * accounts and to fill in a new account, and never sends it as connector
 * config (see `withoutFormOnlyFields`).
 */
export function formOnlyFieldNames(source: ValidSources): string[] {
  const spec = getCredentialSpec(source);
  return spec ? realmFields(spec).map(([key]) => key) : [];
}

/**
 * The connector config without the source's form-only fields. Every request
 * that sends form values as `connector_specific_config` (create, check runs
 * and plans, binding checks) goes through it.
 */
export function withoutFormOnlyFields<V>(
  source: ValidSources,
  config: Readonly<Record<string, V>>
): Record<string, V> {
  const formOnly: ReadonlySet<string> = new Set(formOnlyFieldNames(source));
  return Object.fromEntries(
    Object.entries(config).filter(([name]) => !formOnly.has(name))
  );
}

function withoutBlankEntries(items: readonly unknown[]): unknown[] {
  return items.filter((item) => typeof item !== "string" || item.trim() !== "");
}

/**
 * The form keys that are not connector config: the configuration's tab
 * controls, and `extraNames` (e.g. the typed account).
 */
export function connectorFormControlFieldNames(
  configuration: ConnectionConfiguration,
  extraNames: readonly string[] = []
): Set<string> {
  return new Set([
    ...[...configuration.values, ...configuration.advanced_values]
      .filter((field) => field.type === "tab")
      .map((field) => field.name),
    ...extraNames,
  ]);
}

/**
 * The `connector_specific_config` that Create sends for the form's config
 * values: without form controls and form-only fields, without blank list
 * entries, and with each field's `transform` applied.
 */
export function connectorConfigFromForm(
  source: ValidSources,
  configuration: ConnectionConfiguration,
  values: Readonly<Record<string, unknown>>,
  formControlFieldNames: ReadonlySet<string>
): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  for (const [key, raw] of Object.entries(values)) {
    if (formControlFieldNames.has(key)) continue;
    const value: unknown = Array.isArray(raw) ? withoutBlankEntries(raw) : raw;
    const field = configuration.values.find((field) => field.name === key);
    config[key] =
      field && "transform" in field && field.transform
        ? field.transform(value as string[])
        : value;
  }
  return withoutFormOnlyFields(source, config);
}

/**
 * The names of the source's credential-bound config fields: the backend
 * binding fields, then the form-only realm fields. The create form shows them
 * above the credential section and filters the saved accounts with them.
 */
export function credentialBoundFieldNames(source: ValidSources): string[] {
  return [
    ...new Set([
      ...(CREDENTIAL_BOUND_FIELDS[source] ?? []),
      ...formOnlyFieldNames(source),
    ]),
  ];
}

/**
 * Takes the credential-bound fields out of a configuration, so the create form
 * can show them above the credential section. Only top-level fields move. A
 * bound field inside a tab is not supported: it stays with its tab, and no
 * source has one now.
 */
export function splitCredentialBoundFields(
  source: ValidSources,
  configuration: ConnectionConfiguration
): CredentialBoundFieldSplit {
  const boundNames = new Set(credentialBoundFieldNames(source));
  const isBound = (field: ConnectorField) => boundNames.has(field.name);
  return {
    values: configuration.values.filter(isBound),
    advancedValues: configuration.advanced_values.filter(isBound),
    rest: {
      ...configuration,
      values: configuration.values.filter((field) => !isBound(field)),
      advanced_values: configuration.advanced_values.filter(
        (field) => !isBound(field)
      ),
    },
  };
}

interface ConnectorValidationMessages {
  oneDriveUsersRequired?: string;
  specificGroupsRequired?: string;
  /** A string-pair row with an empty left key. */
  stringPairEmptyKey?: string;
  /** Two string-pair rows with the same left key. */
  stringPairDuplicateKey?: string;
}

/** Each row's trimmed value under `leftKey`, or "" when it has none. */
function stringPairLeftKeys(
  rows: unknown[] | undefined,
  leftKey: string
): string[] {
  return (rows ?? []).map((row) => {
    const entry: [string, unknown] | undefined =
      typeof row === "object" && row !== null
        ? Object.entries(row).find(([key]) => key === leftKey)
        : undefined;
    return String(entry?.[1] ?? "").trim();
  });
}

/**
 * A string-pair list, such as URL rewrite rules. Each row needs a left key,
 * and no two rows may share one, as the InputKeyValue editor shows.
 */
function stringPairListSchema(
  leftKey: string,
  messages: ConnectorValidationMessages
): Yup.Schema {
  return Yup.array()
    .of(Yup.object())
    .test(
      "non-empty-keys",
      messages.stringPairEmptyKey ?? "Key cannot be empty",
      (rows) => stringPairLeftKeys(rows, leftKey).every((key) => key !== "")
    )
    .test(
      "unique-keys",
      messages.stringPairDuplicateKey ?? "Duplicate key",
      (rows) => {
        const keys: string[] = stringPairLeftKeys(rows, leftKey);
        return new Set(keys).size === keys.length;
      }
    );
}

const buildInitialValuesForFields = (
  fields: ConnectorField[]
): Record<string, any> =>
  fields.reduce<Record<string, any>>((acc, field) => {
    if (field.type === "tab") {
      acc[field.name] = field.defaultTab ?? field.tabs[0]?.value ?? "";
      Object.assign(
        acc,
        buildInitialValuesForFields(field.tabs.flatMap((tab) => tab.fields))
      );
    } else if (field.type === "select") {
      acc[field.name] = null;
    } else if (field.type === "list") {
      acc[field.name] = field.default || [];
    } else if (field.type === "multiselect") {
      acc[field.name] = field.default || [];
    } else if (field.type === "checkbox") {
      acc[field.name] = field.default ?? false;
    } else if (field.default !== undefined) {
      acc[field.name] = field.default;
    }
    return acc;
  }, {});

export function createConnectorInitialValues(
  connector: ConfigurableSources
): Record<string, any> &
  ConnectorAccessFormValues &
  ConnectorGroupRestrictionFormValues {
  const configuration = connectorConfigs[connector];

  return {
    name: "",
    groups: [],
    group_roles: {},
    data_access_group_ids: [],
    access_type: "public",
    restrict_access_to_groups: false,
    restriction_group_ids: [],
    ...buildInitialValuesForFields(configuration.values),
    ...buildInitialValuesForFields(configuration.advanced_values),
  };
}

export function createConnectorValidationSchema(
  connector: ConfigurableSources,
  requireGroups: boolean = false,
  messages: ConnectorValidationMessages = {}
): Yup.ObjectSchema<Record<string, any>> {
  const configuration = connectorConfigs[connector];
  const fields = [...configuration.values, ...configuration.advanced_values];

  const fieldSchemas = fields.reduce<Record<string, Yup.Schema>>(
    (acc, field) => {
      let schema: Yup.Schema =
        field.type === "select"
          ? Yup.string()
          : field.type === "list"
            ? Yup.array().of(Yup.string())
            : field.type === "multiselect"
              ? Yup.array().of(Yup.string())
              : field.type === "string_pair_list"
                ? stringPairListSchema(field.leftKey, messages)
                : field.type === "checkbox"
                  ? Yup.boolean()
                  : field.type === "file"
                    ? Yup.mixed()
                    : Yup.string();

      if (!field.optional) {
        schema = schema.required(`${field.label} is required`);
      }

      acc[field.name] = schema;
      return acc;
    },
    {}
  );

  if (connector === ValidSources.OneDrive) {
    fieldSchemas.users = Yup.array()
      .of(Yup.string().trim().required())
      .when("indexing_scope", {
        is: OneDriveScope.Specific,
        then: (schema) => schema.min(1, messages.oneDriveUsersRequired),
      });
  }

  const object = Yup.object().shape({
    access_type: Yup.string().required("Access Type is required"),
    name: Yup.string().required("Connector Name is required"),
    groups: Yup.array()
      .of(Yup.number())
      .when("access_type", ([accessType], schema) =>
        requireGroups && accessType !== "sync"
          ? schema.min(1, "Select at least one group you manage")
          : schema
      ),
    // Specific Groups with none picked would let no group read the
    // documents.
    data_access_group_ids: Yup.array()
      .of(Yup.number())
      .when("access_type", ([accessType], schema) =>
        accessType === "private"
          ? schema.min(1, messages.specificGroupsRequired)
          : schema
      ),
    ...fieldSchemas,
    // These are advanced settings
    indexingStart: Yup.string().nullable(),
    pruneFreq: Yup.number().min(
      MIN_PRUNE_FREQ_HOURS,
      "Prune frequency must be at least 0.083 hours (5 minutes)"
    ),
    refreshFreq: Yup.number().min(
      MIN_REFRESH_FREQ_MINUTES,
      "Refresh frequency must be at least 1 minute"
    ),
  });

  return object;
}

// ---------------------------------------------------------------------------
// Typed file uploads
// ---------------------------------------------------------------------------

export function createTypedFile(
  file: File,
  fieldKey: string,
  typeDefinitionKey: FileTypeCategory
): TypedFile {
  const typeDefinition = FILE_TYPE_DEFINITIONS[typeDefinitionKey];
  if (!typeDefinition) {
    throw new Error(`Unknown file type definition: ${typeDefinitionKey}`);
  }

  return new TypedFile(file, typeDefinition, fieldKey);
}

// ---------------------------------------------------------------------------
// Connector-credential pairs
// ---------------------------------------------------------------------------

/** The cc-pair detail key; also the key `mutate` callers invalidate. */
export function buildCCPairInfoUrl(ccPairId: string | number) {
  return SWR_KEYS.ccPair(ccPairId);
}

export function getTooltipMessage(
  isInvalid: boolean,
  isDeleting: boolean,
  isIndexing: boolean,
  isDisabled: boolean
): string | undefined {
  if (isInvalid) {
    return "Connector is in an invalid state. Please update the credentials or configuration before re-indexing.";
  }
  if (isDeleting) {
    return "Cannot index while connector is deleting";
  }
  if (isIndexing) {
    return "Indexing is already in progress";
  }
  if (isDisabled) {
    return "Connector must be re-enabled before indexing";
  }
  return undefined;
}

/**
 * Returns true if the status is not currently active (i.e. paused or invalid), but not deleting
 */
export function statusIsNotCurrentlyActive(
  status: ConnectorCredentialPairStatus
): boolean {
  return (
    status === ConnectorCredentialPairStatus.PAUSED ||
    status === ConnectorCredentialPairStatus.INVALID
  );
}

// ---------------------------------------------------------------------------
// Gmail
// ---------------------------------------------------------------------------

export const gmailConnectorNameBuilder = (values: GmailConfig) =>
  "GmailConnector";

// ---------------------------------------------------------------------------
// Source metadata
// ---------------------------------------------------------------------------

function fillSourceMetadata(
  partialMetadata: PartialSourceMetadata,
  internalName: ValidSources
): SourceMetadata {
  return {
    internalName: partialMetadata.baseSourceType || internalName,
    ...partialMetadata,
    adminUrl: `/admin/connectors/${internalName}`,
  };
}

export function getSourceMetadata(sourceType: ValidSources): SourceMetadata {
  const partialMetadata = SOURCE_METADATA_MAP[sourceType];

  // Fallback to not_applicable if sourceType not found in map
  if (!partialMetadata) {
    return fillSourceMetadata(
      SOURCE_METADATA_MAP[ValidSources.NotApplicable],
      ValidSources.NotApplicable
    );
  }

  return fillSourceMetadata(partialMetadata, sourceType);
}

export function listSourceMetadata(): SourceMetadata[] {
  /* This gives back all the viewable / common sources, primarily for
  display in the Add Connector page */
  const entries = Object.entries(SOURCE_METADATA_MAP)
    .filter(
      ([source, _]) =>
        source !== "not_applicable" &&
        source !== "ingestion_api" &&
        source !== "mock_connector" &&
        // use the "regular" slack connector when listing
        source !== "federated_slack" &&
        // user_file is for internal use (projects), not the Add Connector page
        source !== "user_file" &&
        // craft_file backs the Craft user library, which has its own upload UI
        source !== "craft_file"
    )
    .map(([source, metadata]) => {
      return fillSourceMetadata(metadata, source as ValidSources);
    });
  return entries;
}

export function getSourceDocLink(sourceType: ValidSources): string | null {
  return SOURCE_METADATA_MAP[sourceType].docs || null;
}

export function isValidSource(sourceType: string): boolean {
  return Object.keys(SOURCE_METADATA_MAP).includes(sourceType);
}

export function getSourceDisplayName(sourceType: ValidSources): string | null {
  return getSourceMetadata(sourceType).displayName;
}

/** The configured sources, one entry per source type. */
export function getConfiguredSources(
  availableSources: ValidSources[]
): Array<SourceMetadata & { originalName: string; uniqueKey: string }> {
  const seen = new Set<string>();
  const result: Array<
    SourceMetadata & { originalName: string; uniqueKey: string }
  > = [];

  for (const sourceName of availableSources) {
    const cleanName = sourceName.replace("federated_", "") as ValidSources;
    if (seen.has(cleanName)) continue;
    seen.add(cleanName);

    const metadata = getSourceMetadata(cleanName);
    if (metadata.internalName === ValidSources.NotApplicable) continue;

    result.push({
      ...metadata,
      originalName: sourceName,
      uniqueKey: cleanName,
    });
  }
  return result;
}
