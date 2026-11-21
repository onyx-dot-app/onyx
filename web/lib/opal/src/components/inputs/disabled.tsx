"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
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

interface InputRowContextValue extends InputRowState {
  /** The input is inside an input layout. */
  inRow: boolean;
}

const InputRowContext = createContext<InputRowContextValue>({
  disabled: false,
  hovered: false,
  inRow: false,
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
    <InputRowContext.Provider
      value={{ disabled, disabledTooltip, hovered, inRow: true }}
    >
      {children}
    </InputRowContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Row hover
// ---------------------------------------------------------------------------

/** Radix's default hover delay, which the app's other tooltips use. */
const ROW_HOVER_DELAY_MS = 700;

interface RowHover {
  hovered: boolean;
  onPointerEnter: () => void;
  onPointerLeave: () => void;
}

/**
 * The row's hover, for its input's tooltip. It turns on after the same delay
 * as a hover tooltip, and off at once when the pointer leaves.
 */
function useRowHover(): RowHover {
  const [hovered, setHovered] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function clearTimer() {
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }

  useEffect(() => clearTimer, []);

  return {
    hovered,
    onPointerEnter: () => {
      clearTimer();
      timer.current = setTimeout(() => setHovered(true), ROW_HOVER_DELAY_MS);
    },
    onPointerLeave: () => {
      clearTimer();
      setHovered(false);
    },
  };
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
 * - While its row is disabled with a `disabledTooltip`, the row's hover shows
 *   that reason.
 * - Otherwise the input's own `tooltip` shows on hover over the input.
 *
 * Inside a row the wrapper is always mounted, so a change of the row's state
 * or reason never remounts the input (an uncontrolled field keeps its text).
 */
function InputTooltip({ tooltip, children }: InputTooltipProps) {
  const row = useContext(InputRowContext);
  const [selfOpen, setSelfOpen] = useState(false);

  if (!row.inRow) {
    if (tooltip == null) return children;
    return <Tooltip tooltip={tooltip}>{children}</Tooltip>;
  }

  const rowReason = row.disabled ? row.disabledTooltip : undefined;
  const shown = rowReason ?? tooltip;
  const open = rowReason != null ? row.hovered : selfOpen && tooltip != null;
  return (
    <Tooltip tooltip={shown ?? ""} open={open} onOpenChange={setSelfOpen}>
      {children}
    </Tooltip>
  );
}

export {
  InputRowProvider,
  useRowHover,
  useInputDisabled,
  InputTooltip,
  type InputRowState,
  type InputTooltipProps,
};
