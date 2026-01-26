export type Variants =
  | "primary"
  | "internal"
  | "error"
  | "disabled"
  | "readOnly";

type ClassNamesMap = Record<Variants, string | null>;

export const MIN_WIDTH_CLASS = "min-w-[14rem]";

export const wrapperClasses: ClassNamesMap = {
  primary: "input-normal",
  internal: null,
  error: "input-error",
  disabled: "input-disabled",
  readOnly: "bg-transparent border rounded-08",
} as const;

export const innerClasses: ClassNamesMap = {
  primary:
    "text-text-04 placeholder:!font-secondary-body placeholder:text-text-02",
  internal: null,
  error: null,
  disabled: "text-text-02",
  readOnly: null,
} as const;

export const iconClasses: ClassNamesMap = {
  primary: "stroke-text-03",
  internal: "stroke-text-03",
  error: "stroke-text-03",
  disabled: "stroke-text-01",
  readOnly: "stroke-text-01",
} as const;

export const textClasses: ClassNamesMap = {
  primary: "text-text-04",
  internal: "text-text-04",
  error: "text-text-04",
  disabled: "text-text-01",
  readOnly: "text-text-01",
} as const;
