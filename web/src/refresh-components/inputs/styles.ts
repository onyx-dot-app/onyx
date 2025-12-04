export type Variants = "main" | "internal" | "error" | "disabled";

type ClassNamesMap = Record<Variants, string | null>;

export const wrapperClasses: ClassNamesMap = {
  main: "input-normal",
  internal: null,
  error: "input-error",
  disabled: "input-disabled",
} as const;

export const innerClasses: ClassNamesMap = {
  main: "text-text-04 placeholder:!font-secondary-body placeholder:text-text-02",
  internal: null,
  error: null,
  disabled: "text-text-02",
} as const;

export const iconClasses: ClassNamesMap = {
  main: "stroke-text-03",
  internal: "stroke-text-03",
  error: "stroke-text-03",
  disabled: "stroke-text-01",
} as const;

export const textClasses: ClassNamesMap = {
  main: "text-text-04",
  internal: "text-text-04",
  error: "text-text-04",
  disabled: "text-text-01",
} as const;
