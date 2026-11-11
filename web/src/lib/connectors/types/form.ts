/** The schema a connector's creation form is rendered from. */
import type { CheckFindingKey } from "@/lib/connectors/checks/types";
import type { CredentialValues } from "@/lib/credentials/types";

export type InputType =
  | "list"
  | "text"
  | "select"
  | "multiselect"
  | "boolean"
  | "number"
  | "file";

export type StringWithDescription = {
  value: string;
  name: string;
  description?: string;
};

export interface Option {
  label: string | ((currentCredential: CredentialValues | null) => string);
  name: string;
  description?:
    | string
    | ((currentCredential: CredentialValues | null) => string);
  optional?: boolean;
  hidden?: boolean;
  visibleCondition?: (
    values: any,
    currentCredential: CredentialValues | null
  ) => boolean;
  wrapInCollapsible?: boolean;
  disabled?:
    | boolean
    | ((currentCredential: CredentialValues | null) => boolean);
}

export interface SelectOption extends Option {
  type: "select";
  options?: StringWithDescription[];
  default?: string;
}

export interface MultiSelectOption extends Option {
  type: "multiselect";
  options?: StringWithDescription[];
  default?: string[];
}

export interface ListOption extends Option {
  type: "list";
  default?: string[];
  /** Runs on the entries before they are sent, e.g. to join them into the
   * one string the config stores. */
  transform?: (values: string[]) => string[] | string;
  /** Example entry shown in each empty input. */
  placeholder?: string;
  /** Discovery finding whose options the field offers: stores the value, shows the label. Typed entries stay allowed. */
  optionsFinding?: CheckFindingKey;
  /** When true the field takes typed entries only, such as regex patterns. */
  plainListCondition?: (values: Record<string, unknown>) => boolean;
  /**
   * Beside the title: how many options a discovery check found, and a button
   * that lists them again. `label` is a key formatted with `count` and
   * `more` ("true" when the listing stopped at the backend's cap).
   */
  availableCount?: {
    finding: CheckFindingKey;
    checkId: string;
    label: string;
  };
}

export interface StringPairListOption extends Option {
  type: "string_pair_list";
  // Object keys each row serializes to, e.g. { leftKey: "source", rightKey: "target" }.
  leftKey: string;
  rightKey: string;
  default?: Record<string, string>[];
  leftLabel: string;
  rightLabel: string;
  leftPlaceholder?: string;
  rightPlaceholder?: string;
}

/** A key under `admin.connectorsList.subDescriptions` in the message catalog. */
export type TextSubDescriptionKey = "siteUrl";

export interface TextOption extends Option {
  type: "text";
  default?: string;
  initial?: string | ((currentCredential: CredentialValues | null) => string);
  isTextArea?: boolean;
  /** Monospace text, for code or queries. Text areas only. */
  mono?: boolean;
  /**
   * A button under the field that runs this capability check now, beside
   * the description. The description's lines show one per row.
   */
  testCheck?: { checkId: string; label: string };
  /** Example value shown in the empty input: a message key, or one picked by
   * the form's values (e.g. Confluence's site URL per Cloud or Data Center). */
  placeholder?: string | ((values: Record<string, unknown>) => string);
  /** Text below the input. It gets the connector's name as `connectorName`. */
  subDescription?: TextSubDescriptionKey;
}

export interface NumberOption extends Option {
  type: "number";
  default?: number;
}

/** A key under `admin.connectorsList.checkboxTabs` in the message catalog. */
export type CheckboxTabLabelKey = "confluenceCloud" | "confluenceDataCenter";

export interface BooleanOption extends Option {
  type: "checkbox";
  default?: boolean;
  /** The value the credential sets; the form uses it while the field is disabled. */
  initial?: (currentCredential: CredentialValues | null) => boolean | undefined;
  /** Shows the value as two tabs with these labels instead of a checkbox. */
  tabLabels?: { true: CheckboxTabLabelKey; false: CheckboxTabLabelKey };
  /** Shows a checkbox instead of the standard switch. */
  asCheckbox?: boolean;
}

export interface FileOption extends Option {
  type: "file";
  default?: string;
  /** Takes many files (tags) or one. @default true */
  multiple?: boolean;
  /** The picker's filter, as the HTML `accept` attribute, e.g. `".zip"`. */
  accept?: string;
}

export interface StringTabOption extends Option {
  type: "string_tab";
  default?: string;
  /** The description's arguments, read from the form; null hides the
   * description. With it, the description key is formatted when shown. */
  descriptionValues?: (
    values: Record<string, unknown>
  ) => Record<string, string> | null;
}

export type ConnectorValueField =
  | BooleanOption
  | ListOption
  | StringPairListOption
  | TextOption
  | NumberOption
  | SelectOption
  | MultiSelectOption
  | FileOption
  | StringTabOption;

export interface TabOption extends Omit<Option, "label"> {
  type: "tab";
  /** Heading above the tabs. Leave it out when the tab labels say enough. */
  label?: Option["label"];
  defaultTab?: string;
  tabs: {
    label: string;
    value: string;
    fields: ConnectorValueField[];
  }[];
  default?: [];
}

export interface ConnectionConfiguration {
  description: string;
  subtext?: string;
  initialConnectorName?: string; // a key in the credential to prepopulate the connector name field
  values: (ConnectorValueField | TabOption)[];
  advanced_values: (ConnectorValueField | TabOption)[];
  overrideDefaultFreq?: number;
  advancedValuesVisibleCondition?: (
    values: any,
    currentCredential: CredentialValues | null
  ) => boolean;
  /**
   * Config values that follow from the picked credential, such as its kind.
   * The form sets them whenever the credential changes. Each must also be a
   * field (usually hidden), so that the checks and the create request send it.
   */
  configFromCredential?: (
    credential: CredentialValues | null
  ) => Record<string, string | undefined>;
}
