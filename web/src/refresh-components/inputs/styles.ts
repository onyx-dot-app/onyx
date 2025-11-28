export type Variants = "main" | "internal" | "error" | "disabled";

type ClassNamesMap = Record<Variants, string[]>;

export const wrapperClasses: ClassNamesMap = {
  main: [
    "bg-background-neutral-00",
    "border",
    "hover:border-border-02",
    "active:!border-border-05",
    "focus-within-nonactive:border-border-05 focus-within-nonactive:focus-shadow",
  ],
  internal: [],
  error: ["bg-background-neutral-00", "border", "border-status-error-05"],
  disabled: ["bg-background-neutral-03", "border", "cursor-not-allowed"],
} as const;

export const innerClasses: ClassNamesMap = {
  main: [
    "text-text-04 placeholder:!font-secondary-body placeholder:text-text-02",
  ],
  internal: [],
  error: [],
  disabled: ["text-text-02"],
} as const;

export const iconClasses: ClassNamesMap = {
  main: ["stroke-text-03"],
  internal: ["stroke-text-03"],
  error: ["stroke-text-03"],
  disabled: ["stroke-text-01"],
} as const;

export const textClasses: ClassNamesMap = {
  main: ["text-text-04"],
  internal: ["text-text-04"],
  error: ["text-text-04"],
  disabled: ["text-text-01"],
} as const;
