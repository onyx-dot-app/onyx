// Stateful pill color matrix, mirroring Opal `select-light`
// (web/lib/opal/src/core/interactive/stateful/styles.css:228-316). Classes are literal token
// strings so NativeWind's compiler sees them. Touch has no hover, so the web hover cells are
// dropped and the matrix is rest/active/disabled; `active` = pressed. `fg` (label) and `icon` are
// kept separate because the empty state tints them differently, exactly as web does.
export type SelectState = "empty" | "selected";

export type SelectVariant = "select-light";

export type SelectColorState = "rest" | "active" | "disabled";

interface SelectColorCell {
  bg: string;
  fg: string;
  icon: string;
}

type SelectColorMatrix = Record<
  SelectVariant,
  Record<SelectState, Record<SelectColorState, SelectColorCell>>
>;

export const SELECT_COLORS: SelectColorMatrix = {
  "select-light": {
    empty: {
      rest: {
        bg: "bg-transparent",
        fg: "text-text-04",
        icon: "text-text-03",
      },
      active: {
        bg: "bg-background-neutral-00",
        fg: "text-text-05",
        icon: "text-text-05",
      },
      disabled: {
        bg: "bg-transparent",
        fg: "text-text-01",
        icon: "text-text-01",
      },
    },
    selected: {
      rest: {
        bg: "bg-transparent",
        fg: "text-action-link-05",
        icon: "text-action-link-05",
      },
      active: {
        bg: "bg-background-tint-00",
        fg: "text-action-link-05",
        icon: "text-action-link-05",
      },
      disabled: {
        bg: "bg-transparent",
        fg: "text-action-link-03",
        icon: "text-action-link-03",
      },
    },
  },
};

export function resolveSelectState(
  disabled: boolean,
  pressed: boolean,
): SelectColorState {
  if (disabled) return "disabled";
  if (pressed) return "active";
  return "rest";
}
