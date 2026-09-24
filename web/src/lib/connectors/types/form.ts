/** The schema a connector's creation form is rendered from. */
import type { Credential } from "./credential";

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

export interface TextOption extends Option {
  type: "text";
  default?: string;
  initial?: string | ((currentCredential: Credential<any> | null) => string);
  isTextArea?: boolean;
}

export interface NumberOption extends Option {
  type: "number";
  default?: number;
}

export interface BooleanOption extends Option {
  type: "checkbox";
  default?: boolean;
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

export type TabSelectionValue = string | number | boolean | null;

export interface TabOption extends Option {
  type: "tab";
  defaultTab?: string;
  selectionField?: string;
  tabs: {
    label: string;
    value: string;
    selectionValue?: TabSelectionValue;
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
}
