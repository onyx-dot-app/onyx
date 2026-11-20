"use client";

import { createContext, useContext } from "react";
import { Tooltip } from "@opal/components/tooltip/components";
import type { RichStr } from "@opal/types";

// ---------------------------------------------------------------------------
// Row context
// ---------------------------------------------------------------------------

interface InputRowState {
  /** The row is disabled, so the input inside it is too. */
  disabled: boolean;
  /** Why the row is disabled. Shown beside the input while the row is hovered. */
  disabledTooltip?: string | RichStr;
  /** The pointer is over the row. */
  hovered: boolean;
}

const InputRowContext = createContext<InputRowState>({
  disabled: false,
  hovered: false,
});

interface InputRowProviderProps extends InputRowState {
  children?: React.ReactNode;
}

/**
 * Passes an input layout's `disabled` and `disabledTooltip` to the inputs it
 * wraps. `InputHorizontal` and `InputVertical` render it.
 */
function InputRowProvider({
  disabled,
  disabledTooltip,
  hovered,
  children,
}: InputRowProviderProps) {
  return (
    <InputRowContext.Provider value={{ disabled, disabledTooltip, hovered }}>
      {children}
    </InputRowContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Input hooks
// ---------------------------------------------------------------------------

/** The input is disabled by its own prop or by its row. */
function useInputDisabled(disabled: boolean | undefined): boolean {
  const row = useContext(InputRowContext);
  return Boolean(disabled) || row.disabled;
}

// ---------------------------------------------------------------------------
// InputTooltip
// ---------------------------------------------------------------------------

interface InputTooltipProps {
  /** The input's own tooltip, shown in any state. */
  tooltip?: string | RichStr;
  /**
   * The input's root. Must be a single element that takes a ref, as for
   * `Tooltip`.
   */
  children: React.ReactElement;
}

/**
 * The tooltip of an Opal input, anchored to the input.
 *
 * - In a row with a `disabledTooltip`, the row's hover opens it: the reason
 *   while the row is disabled, else the input's own `tooltip`.
 * - Otherwise the input's own `tooltip` shows on hover over the input.
 *
 * The wrapper stays mounted, so a change of state does not remount the input.
 */
function InputTooltip({ tooltip, children }: InputTooltipProps) {
  const row = useContext(InputRowContext);

  if (row.disabledTooltip != null) {
    const shown = row.disabled ? row.disabledTooltip : tooltip;
    return (
      <Tooltip tooltip={shown ?? ""} open={row.hovered && shown != null}>
        {children}
      </Tooltip>
    );
  }
  if (tooltip == null) return children;
  return <Tooltip tooltip={tooltip}>{children}</Tooltip>;
}

export {
  InputRowProvider,
  useInputDisabled,
  InputTooltip,
  type InputRowState,
  type InputTooltipProps,
};
