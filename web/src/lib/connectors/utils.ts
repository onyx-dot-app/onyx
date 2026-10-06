import * as Yup from "yup";
import type {
  ConnectorAccessFormValues,
  ConnectorGroupRestrictionFormValues,
} from "@/lib/connectors/accessType";
import { ValidSources } from "@/lib/connectors/types/source";
import type { IndexAttemptStage, IndexAttemptStageMetric } from "@/lib/types";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  connectorConfigs,
  MIN_PRUNE_FREQ_HOURS,
  MIN_REFRESH_FREQ_MINUTES,
} from "@/lib/connectors/connectors";
import credentialBoundFields from "@/lib/connectors/credentialBoundFields.json";
import { FILE_TYPE_DEFINITIONS, TypedFile } from "@/lib/connectors/fileTypes";
import {
  PIPELINE_ORDER,
  STAGE_BAR_COLORS,
} from "@/lib/connectors/stageMetrics/constants";
import {
  ConnectorCredentialPairStatus,
  FileTypeCategory,
  OneDriveScope,
} from "@/lib/connectors/types";
import type {
  ConnectionConfiguration,
  GmailConfig,
  SortMode,
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
 * Takes the credential-bound fields out of a configuration, so the create form
 * can show them above the credential section. Only top-level fields move. A
 * bound field inside a tab is not supported: it stays with its tab, and no
 * source has one now.
 */
export function splitCredentialBoundFields(
  source: ValidSources,
  configuration: ConnectionConfiguration
): CredentialBoundFieldSplit {
  const boundNames = new Set(CREDENTIAL_BOUND_FIELDS[source] ?? []);
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
                ? Yup.array().of(Yup.object())
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
// Stage metrics
// ---------------------------------------------------------------------------

// Sort per-batch stages according to the current sort mode. Pipeline order is
// the canonical enum declaration order; time-taken sorts descending by
// total duration so the long pole sits first.
export function sortPerBatchStages(
  stages: IndexAttemptStageMetric[],
  sortMode: SortMode
): IndexAttemptStageMetric[] {
  const sorted = [...stages];
  if (sortMode === "pipeline") {
    sorted.sort(
      (a, b) => (PIPELINE_ORDER[a.stage] ?? 0) - (PIPELINE_ORDER[b.stage] ?? 0)
    );
  } else {
    sorted.sort((a, b) => b.total_duration_ms - a.total_duration_ms);
  }
  return sorted;
}

export function colorClassForStage(stage: IndexAttemptStage): string {
  const idx = PIPELINE_ORDER[stage] ?? 0;
  return STAGE_BAR_COLORS[idx % STAGE_BAR_COLORS.length]!;
}

// ---------------------------------------------------------------------------
// Gmail
// ---------------------------------------------------------------------------

export const gmailConnectorNameBuilder = (values: GmailConfig) =>
  "GmailConnector";
