import type React from "react";

// ---------------------------------------------------------------------------
// Shared interaction helpers for row-shaped buttons (LineItemButton,
// AttachmentItemButton). A row renders as a focusable div (role="button")
// instead of a native <button> so interactive `rightChildren` don't nest a
// <button> inside a <button> — invalid HTML that breaks hydration. These
// helpers restore the native-control behavior that choice gives up.
// ---------------------------------------------------------------------------

// Mirrors native <button> activation (Enter fires on keydown, Space on keyup).
// Guarded so keystrokes on nested interactive children (e.g. `rightChildren`
// action buttons) don't also activate the row.
function handleRowKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
  if (e.target !== e.currentTarget) return;
  if (e.key === "Enter") {
    e.preventDefault();
    e.currentTarget.click();
  } else if (e.key === " ") {
    e.preventDefault();
  }
}

function handleRowKeyUp(e: React.KeyboardEvent<HTMLDivElement>) {
  if (e.target !== e.currentTarget) return;
  if (e.key === " ") {
    e.preventDefault();
    e.currentTarget.click();
  }
}

// The caller's handler runs first and can stop the row's own activation with
// `preventDefault()` — the order a native control gives you. Composed rather
// than replaced, because a row that accepts a handler and then overwrites it
// is the same silent drop these components exist to avoid.
function composeKeyHandler(
  caller: React.KeyboardEventHandler<HTMLDivElement> | undefined,
  row: React.KeyboardEventHandler<HTMLDivElement>
): React.KeyboardEventHandler<HTMLDivElement> {
  if (!caller) return row;
  return (e) => {
    caller(e);
    if (!e.defaultPrevented) row(e);
  };
}

// Ignore clicks originating from nested interactive children (e.g.
// `rightChildren` action buttons) so they don't also activate the row.
function guardNestedInteractiveClick(
  onClick: React.MouseEventHandler<HTMLElement> | undefined
): React.MouseEventHandler<HTMLElement> | undefined {
  if (!onClick) return undefined;
  return (e) => {
    const nested = (e.target as HTMLElement).closest(
      'button, a, [role="button"]'
    );
    if (nested && nested !== e.currentTarget) return;
    onClick(e);
  };
}

export {
  handleRowKeyDown,
  handleRowKeyUp,
  composeKeyHandler,
  guardNestedInteractiveClick,
};
