export type Variants =
  | "primary"
  | "secondary"
  | "internal"
  | "error"
  | "disabled"
  | "readOnly";

type ClassNamesMap = Record<Variants, string | null>;

export const sizes = {
  md: "14rem",
} as const;

export const wrapperClasses: ClassNamesMap = {
  primary: "input-normal",
  secondary:
    "bg-transparent hover:bg-background-tint-02 active:bg-background-tint-00",
  internal: null,
  error: "input-error",
  disabled: "input-disabled opacity-50 cursor-not-allowed",
  readOnly: "bg-transparent border rounded-08",
} as const;

export const innerClasses: ClassNamesMap = {
  primary:
    "text-text-04 placeholder:!font-secondary-body placeholder:text-text-02",
  secondary: "text-text-04",
  internal: null,
  error: null,
  disabled: "text-text-02",
  readOnly: null,
} as const;

export const iconClasses: ClassNamesMap = {
  primary: "stroke-text-03",
  secondary: "stroke-text-03",
  internal: "stroke-text-03",
  error: "stroke-text-03",
  disabled: "stroke-text-01",
  readOnly: "stroke-text-01",
} as const;

export const textClasses: ClassNamesMap = {
  primary: "text-text-04",
  secondary: "text-text-04",
  internal: "text-text-04",
  error: "text-text-04",
  disabled: "text-text-01",
  readOnly: "text-text-01",
} as const;
