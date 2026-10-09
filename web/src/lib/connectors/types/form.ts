/** The schema a connector's creation form is rendered from. */
import type { Credential } from "@/lib/credentials/types";

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
  label: string | ((currentCredential: Credential<any> | null) => string);
  name: string;
  description?:
    | string
    | ((currentCredential: Credential<any> | null) => string);
  query?: string;
  optional?: boolean;
  hidden?: boolean;
  visibleCondition?: (
    values: any,
    currentCredential: Credential<any> | null
  ) => boolean;
  wrapInCollapsible?: boolean;
  disabled?: boolean | ((currentCredential: Credential<any> | null) => boolean);
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
  transform?: (values: string[]) => string[];
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
  initial?: string | ((currentCredential: Credential<any> | null) => string);
  isTextArea?: boolean;
  /** Example value shown in the empty input. */
  placeholder?: string;
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
  initial?: (currentCredential: Credential<any> | null) => boolean | undefined;
  /** Shows the value as two tabs with these labels instead of a checkbox. */
  tabLabels?: { true: CheckboxTabLabelKey; false: CheckboxTabLabelKey };
  /** Shows a checkbox instead of the standard switch. */
  asCheckbox?: boolean;
}

export interface FileOption extends Option {
  type: "file";
  default?: string;
}

export interface StringTabOption extends Option {
  type: "string_tab";
  default?: string;
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
    currentCredential: Credential<any> | null
  ) => boolean;
  /**
   * Config values that follow from the picked credential, such as its kind.
   * The form sets them whenever the credential changes. Each must also be a
   * field (usually hidden), so that the checks and the create request send it.
   */
  configFromCredential?: (
    credential: Credential<unknown> | null
  ) => Record<string, string | undefined>;
}
