import type React from "react";

// ---------------------------------------------------------------------------
// Shared interaction helpers for row-shaped buttons (LineItemButton,
// AttachmentItemButton). A row renders as a focusable div (role="button")
// instead of a native <button> so interactive `rightChildren` don't nest a
// <button> inside a <button> — invalid HTML that breaks hydration. These
// helpers restore the native-control behavior that choice gives up.
// ---------------------------------------------------------------------------

// A caller's preventDefault() on Space arrives on keydown, but the click
// fires on keyup — a different event, so `defaultPrevented` can't carry the
// cancellation across. The composed keydown wrapper records it here instead,
// and the keyup handler honors and clears it.
const SPACE_CANCELED = "rowSpaceCanceled";

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
    delete e.currentTarget.dataset[SPACE_CANCELED];
  }
}

function handleRowKeyUp(e: React.KeyboardEvent<HTMLDivElement>) {
  if (e.target !== e.currentTarget) return;
  if (e.key === " ") {
    e.preventDefault();
    if (e.currentTarget.dataset[SPACE_CANCELED]) {
      delete e.currentTarget.dataset[SPACE_CANCELED];
      return;
    }
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
    if (e.defaultPrevented) {
      if (e.key === " " && e.type === "keydown") {
        e.currentTarget.dataset[SPACE_CANCELED] = "true";
      }
      return;
    }
    row(e);
  };
}

// Everything a click may legitimately land on without meaning "activate the
// row": nested action buttons and links, and the form controls an inline
// editor renders.
const NESTED_INTERACTIVE_SELECTOR =
  "button, a, input, textarea, select, label, " +
  '[role="button"], [role="checkbox"], [contenteditable="true"]';

// Ignore clicks originating from nested interactive children (e.g.
// `rightChildren` action buttons) so they don't also activate the row.
// preventDefault matters for the anchor mode: without it the row's native
// link still navigates after the nested action runs.
function guardNestedInteractiveClick(
  onClick: React.MouseEventHandler<HTMLElement> | undefined
): React.MouseEventHandler<HTMLElement> | undefined {
  if (!onClick) return undefined;
  return (e) => {
    const nested = (e.target as HTMLElement).closest(
      NESTED_INTERACTIVE_SELECTOR
    );
    if (nested && nested !== e.currentTarget) {
      e.preventDefault();
      return;
    }
    onClick(e);
  };
}

export {
  handleRowKeyDown,
  handleRowKeyUp,
  composeKeyHandler,
  guardNestedInteractiveClick,
};
