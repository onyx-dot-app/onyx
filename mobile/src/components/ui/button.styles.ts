// Classes are literal token strings so NativeWind's compiler sees them.
// No `hover` state: touch has no hover equivalent, so the matrix is rest/active/disabled.
import type {
  InteractiveProminence,
  InteractiveVariant,
  TextFont,
} from "@onyx-ai/shared/contracts";

export type ButtonSize = "lg" | "md" | "sm" | "xs" | "2xs" | "fit";

export type ButtonWidth = "fit" | "full";

export type ButtonInteraction = "rest" | "active";

export type ButtonColorState = "rest" | "active" | "disabled";

interface ButtonColorCell {
  bg: string;
  fg: string;
  // Tracks `fg`: a bare `@apply border` is `currentColor` in Tailwind v4.
  border: string;
}

type ButtonColorMatrix = Record<
  InteractiveVariant,
  Record<InteractiveProminence, Record<ButtonColorState, ButtonColorCell>>
>;

// Full Record by type: a new shared variant/prominence won't compile until its cells exist.
export const BUTTON_COLORS: ButtonColorMatrix = {
  default: {
    primary: {
      rest: {
        bg: "bg-theme-primary-05",
        fg: "text-text-inverted-05",
        border: "",
      },
      active: {
        bg: "bg-theme-primary-06",
        fg: "text-text-inverted-05",
        border: "",
      },
      disabled: {
        bg: "bg-background-neutral-04",
        fg: "text-text-inverted-04",
        border: "",
      },
    },
    secondary: {
      rest: {
        bg: "bg-background-tint-01",
        fg: "text-text-03",
        border: "border border-text-03",
      },
      active: {
        bg: "bg-background-tint-00",
        fg: "text-text-05",
        border: "border border-text-05",
      },
      disabled: {
        bg: "bg-background-neutral-03",
        fg: "text-text-01",
        border: "border border-text-01",
      },
    },
    tertiary: {
      rest: { bg: "bg-transparent", fg: "text-text-03", border: "" },
      active: { bg: "bg-background-tint-00", fg: "text-text-05", border: "" },
      disabled: { bg: "bg-transparent", fg: "text-text-01", border: "" },
    },
    internal: {
      rest: { bg: "bg-transparent", fg: "text-text-03", border: "" },
      active: { bg: "bg-background-tint-00", fg: "text-text-05", border: "" },
      disabled: { bg: "bg-transparent", fg: "text-text-01", border: "" },
    },
  },
  action: {
    primary: {
      rest: { bg: "bg-action-link-05", fg: "text-text-light-05", border: "" },
      active: { bg: "bg-action-link-06", fg: "text-text-light-05", border: "" },
      disabled: { bg: "bg-action-link-02", fg: "text-text-01", border: "" },
    },
    secondary: {
      rest: {
        bg: "bg-background-tint-01",
        fg: "text-action-text-link-05",
        border: "border border-action-text-link-05",
      },
      active: {
        bg: "bg-background-tint-00",
        fg: "text-action-text-link-05",
        border: "border border-action-text-link-05",
      },
      disabled: {
        bg: "bg-background-neutral-02",
        fg: "text-action-link-03",
        border: "border border-action-link-03",
      },
    },
    tertiary: {
      rest: {
        bg: "bg-transparent",
        fg: "text-action-text-link-05",
        border: "",
      },
      active: {
        bg: "bg-background-tint-00",
        fg: "text-action-text-link-05",
        border: "",
      },
      disabled: { bg: "bg-transparent", fg: "text-action-link-03", border: "" },
    },
    internal: {
      rest: {
        bg: "bg-transparent",
        fg: "text-action-text-link-05",
        border: "",
      },
      active: {
        bg: "bg-background-tint-00",
        fg: "text-action-text-link-05",
        border: "",
      },
      disabled: { bg: "bg-transparent", fg: "text-action-link-03", border: "" },
    },
  },
  danger: {
    primary: {
      rest: { bg: "bg-action-danger-05", fg: "text-text-light-05", border: "" },
      active: {
        bg: "bg-action-danger-06",
        fg: "text-text-light-05",
        border: "",
      },
      disabled: { bg: "bg-action-danger-02", fg: "text-text-01", border: "" },
    },
    secondary: {
      rest: {
        bg: "bg-background-tint-01",
        fg: "text-action-text-danger-05",
        border: "border border-action-text-danger-05",
      },
      active: {
        bg: "bg-background-tint-00",
        fg: "text-action-text-danger-05",
        border: "border border-action-text-danger-05",
      },
      disabled: {
        bg: "bg-background-neutral-02",
        fg: "text-action-danger-03",
        border: "border border-action-danger-03",
      },
    },
    tertiary: {
      rest: {
        bg: "bg-transparent",
        fg: "text-action-text-danger-05",
        border: "",
      },
      active: {
        bg: "bg-background-tint-00",
        fg: "text-action-text-danger-05",
        border: "",
      },
      disabled: {
        bg: "bg-transparent",
        fg: "text-action-danger-03",
        border: "",
      },
    },
    internal: {
      rest: {
        bg: "bg-transparent",
        fg: "text-action-text-danger-05",
        border: "",
      },
      active: {
        bg: "bg-background-tint-00",
        fg: "text-action-text-danger-05",
        border: "",
      },
      disabled: {
        bg: "bg-transparent",
        fg: "text-action-danger-03",
        border: "",
      },
    },
  },
};

interface ButtonSizeSpec {
  height: string; // `""` = content height, for `fit`
  minWidth: string; // keeps icon-only buttons square
  padding: string;
  rounding: string;
  font: TextFont;
  iconPad: string;
  iconSize: number;
}

export const BUTTON_SIZES: Record<ButtonSize, ButtonSizeSpec> = {
  lg: {
    height: "h-36",
    minWidth: "min-w-36",
    padding: "p-8",
    rounding: "rounded-12",
    font: "main-ui-body",
    iconPad: "p-2",
    iconSize: 16,
  },
  md: {
    height: "h-28",
    minWidth: "min-w-28",
    padding: "p-4",
    rounding: "rounded-08",
    font: "secondary-body",
    iconPad: "p-2",
    iconSize: 16,
  },
  sm: {
    height: "h-24",
    minWidth: "min-w-24",
    padding: "p-4",
    rounding: "rounded-08",
    font: "secondary-body",
    iconPad: "p-0",
    iconSize: 16,
  },
  xs: {
    height: "h-20",
    minWidth: "min-w-20",
    padding: "p-2",
    rounding: "rounded-08",
    font: "secondary-body",
    iconPad: "p-2",
    iconSize: 12,
  },
  "2xs": {
    height: "h-16",
    minWidth: "min-w-16",
    padding: "p-2",
    rounding: "rounded-04",
    font: "secondary-body",
    iconPad: "p-0",
    iconSize: 12,
  },
  fit: {
    height: "",
    minWidth: "",
    padding: "p-0",
    rounding: "rounded-08",
    font: "secondary-body",
    iconPad: "p-2",
    iconSize: 16,
  },
};

export function resolveButtonState(
  disabled: boolean,
  interaction: ButtonInteraction,
  pressed: boolean,
): ButtonColorState {
  if (disabled) return "disabled";
  if (interaction === "active" || pressed) return "active";
  return "rest";
}
