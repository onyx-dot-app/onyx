import { Dispatch, SetStateAction } from "react";

export type InputType = "list" | "text" | "checkbox" | "select" | "number";

export type StringWithDescription = {
  value: string;
  name: string;
  description?: string;
};

export interface Option {
  label: string;
  name: string;
  description?: string;
  query?: string;
  optional?: boolean;
  hidden?: boolean;
}

export interface SelectOption extends Option {
  type: "select";
  default?: number;
  options?: StringWithDescription[];
}

export interface ListOption extends Option {
  type: "list";
  default?: string[];
}

export interface TextOption extends Option {
  type: "text";
  default?: string;
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

export interface ZipOption extends Option {
  type: "zip";
  default?: string;
}

export interface ConnectionConfiguration {
  description: string;
  subtext?: string;
  values: (
    | BooleanOption
    | ListOption
    | TextOption
    | NumberOption
    | SelectOption
    | FileOption
    | ZipOption
  )[];
}

export interface DynamicConnectionFormProps {
  config: ConnectionConfiguration;
  onSubmit: (values: any) => void;
  selectedFiles: File[];
  setSelectedFiles: Dispatch<SetStateAction<File[]>>;
  defaultValues: any;
  setName: Dispatch<SetStateAction<string>>;
  updateValues: (field: string, value: any) => void;
}
