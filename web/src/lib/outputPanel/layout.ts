/**
 * The width rules of an output panel beside a chat, shared by Craft's
 * workspace and the chat page: the panel takes a share of the workspace, the
 * chat keeps `MIN_CHAT_WIDTH`, and a workspace too narrow for both shows the
 * panel over the chat.
 */

export const MIN_CHAT_WIDTH = 400;
// Room at the end of the panel's header for the size and close controls
export const OUTPUT_PANEL_HEADER_CONTROL_WIDTH = 76;
export const MIN_OUTPUT_WIDTH = 280;
// Room at the workspace's top end for the chat's right panel toggle: its
// 12px inset, as Craft's toggle, its 28px button and a 4px gap. The chat's
// header and the panel's size button keep out of it.
export const PANEL_TOGGLE_RESERVE = 44;
// The panel's share of the workspace before the user resizes it
export const DEFAULT_PANEL_PROPORTION = 0.5;

// Closed, beside the chat, or over it
export type OutputPanelMode = "closed" | "medium" | "full";

interface OutputPanelGeometry {
  // Too narrow for the chat and the panel side by side
  narrow: boolean;
  // The panel's share of the workspace at medium size, within the limits
  proportion: number;
  mediumWidth: number;
}

/** The medium panel's width in a workspace, from a stored proportion. */
export function outputPanelLayout(
  workspaceWidth: number,
  proportion: number
): OutputPanelGeometry {
  const narrow =
    workspaceWidth > 0 && workspaceWidth < MIN_CHAT_WIDTH + MIN_OUTPUT_WIDTH;
  const minimum = workspaceWidth > 0 ? MIN_OUTPUT_WIDTH / workspaceWidth : 0.5;
  const maximum =
    workspaceWidth > 0 ? 1 - MIN_CHAT_WIDTH / workspaceWidth : 0.5;
  const bounded = narrow
    ? 0.5
    : Math.max(minimum, Math.min(maximum, proportion));
  return {
    narrow,
    proportion: bounded,
    mediumWidth: workspaceWidth * bounded,
  };
}

/** The proportion for a panel width, kept within the width limits. */
export function proportionForWidth(
  width: number,
  workspaceWidth: number
): number {
  return (
    Math.max(
      MIN_OUTPUT_WIDTH,
      Math.min(workspaceWidth - MIN_CHAT_WIDTH, width)
    ) / workspaceWidth
  );
}
