import * as Yup from "yup";
import type { AccessTypeGroupSelectorFormType } from "@/components/admin/connectors/AccessTypeGroupSelector";
import type { ConnectorGroupRestrictionFormValues } from "@/lib/connectors/accessType";
import type {
  ConfigurableSources,
  IndexAttemptStage,
  IndexAttemptStageMetric,
  ValidSources,
} from "@/lib/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { connectorConfigs } from "@/lib/connectors/connectors";
import { credentialDisplayNames } from "@/lib/connectors/credentials";
import { FILE_TYPE_DEFINITIONS, TypedFile } from "@/lib/connectors/fileTypes";
import {
  PIPELINE_ORDER,
  STAGE_BAR_COLORS,
} from "@/lib/connectors/stageMetrics/constants";
import {
  ConnectorCredentialPairStatus,
  FileTypeCategory,
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

const buildInitialValuesForFields = (
  fields: ConnectorField[]
): Record<string, any> =>
  fields.reduce<Record<string, any>>((acc, field) => {
    if (field.type === "select") {
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
  AccessTypeGroupSelectorFormType &
  ConnectorGroupRestrictionFormValues {
  const configuration = connectorConfigs[connector];

  return {
    name: "",
    groups: [],
    access_type: "public",
    restrict_access_to_groups: false,
    restriction_group_ids: [],
    ...buildInitialValuesForFields(configuration.values),
    ...buildInitialValuesForFields(configuration.advanced_values),
  };
}

export function createConnectorValidationSchema(
  connector: ConfigurableSources,
  requireGroups: boolean = false
): Yup.ObjectSchema<Record<string, any>> {
  const configuration = connectorConfigs[connector];

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
    ...[...configuration.values, ...configuration.advanced_values].reduce<
      Record<string, any>
    >((acc, field) => {
      let schema: any =
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
    }, {}),
    // These are advanced settings
    indexingStart: Yup.string().nullable(),
    pruneFreq: Yup.number().min(
      0.083,
      "Prune frequency must be at least 0.083 hours (5 minutes)"
    ),
    refreshFreq: Yup.number().min(
      1,
      "Refresh frequency must be at least 1 minute"
    ),
  });

  return object;
}

// ---------------------------------------------------------------------------
// Credentials
// ---------------------------------------------------------------------------

export function getDisplayNameForCredentialKey(key: string): string {
  return credentialDisplayNames[key] || key;
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

export function isTypedFileField(fieldKey: string): boolean {
  // Define which fields should be typed files
  const typedFileFields = new Set([
    "sp_private_key",
    "onedrive_private_key",
    "outlook_private_key",
    "teams_private_key",
  ]);
  return typedFileFields.has(fieldKey);
}

// Get the appropriate file type definition for a field
export function getFileTypeDefinitionForField(
  fieldKey: string
): FileTypeCategory | null {
  const fieldToTypeMap: Record<string, FileTypeCategory> = {
    sp_private_key: FileTypeCategory.SHAREPOINT_PFX_FILE,
    onedrive_private_key: FileTypeCategory.ONEDRIVE_PFX_FILE,
    // The same PFX bundle rules apply to every Microsoft app registration.
    outlook_private_key: FileTypeCategory.SHAREPOINT_PFX_FILE,
    teams_private_key: FileTypeCategory.SHAREPOINT_PFX_FILE,
  };

  return fieldToTypeMap[fieldKey] || null;
}

// ---------------------------------------------------------------------------
// Connector-credential pairs
// ---------------------------------------------------------------------------

/** The cc-pair detail key; also the key `mutate` callers invalidate. */
export function buildCCPairInfoUrl(ccPairId: string | number) {
  return SWR_KEYS.ccPair(ccPairId);
}

export function buildSimilarCredentialInfoURL(
  source_type: ValidSources,
  get_editable: boolean = false
) {
  return SWR_KEYS.similarCredentials(source_type, get_editable);
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
