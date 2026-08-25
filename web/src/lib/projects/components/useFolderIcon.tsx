"use client";

import { useState } from "react";
import { Button, SidebarTab } from "@opal/components";
import type { IconFunctionComponent } from "@opal/types";
import { SvgFolder, SvgFolderOpen, SvgFolderPartialOpen } from "@opal/icons";
import { noProp } from "@/lib/utils";

/**
 * The folder glyph for a project row: open or closed by fold state, previewing
 * the partial-open folder on hover, and toggling the fold on click without
 * letting the click reach the row underneath.
 *
 * After a click the preview stays off until the pointer leaves, so the icon does
 * not preview the state the user just left.
 *
 * Shared by both project rows so the glyph cannot drift between them. The state
 * lives here and the returned render function is stateless on purpose:
 * `SidebarTab` reconciles `icon` by function identity, so a stateful component
 * would remount whenever `open` changed and reset the preview mid-hover.
 */
export function useFolderIcon(
  open: boolean,
  onToggle: () => void
): IconFunctionComponent {
  const [hovering, setHovering] = useState(false);
  const [previewEnabled, setPreviewEnabled] = useState(true);

  const Glyph =
    hovering && previewEnabled
      ? SvgFolderPartialOpen
      : open
        ? SvgFolderOpen
        : SvgFolder;

  return () => (
    /* Deliberately not an Opal `Button`. This was a div, promoted to a button
       for its semantics alone — focusable, with a role and keyboard handling.
       It wants none of the chrome Opal's Button brings: focus ring, padding,
       sizing, interaction styling. It is a bare glyph. */
    <button
      type="button"
      data-testid="ProjectFolderIcon"
      // The glyph carries no text, so the control needs its own name and state.
      aria-label={open ? "Collapse project" : "Expand project"}
      aria-expanded={open}
      /* Above the tab's click overlay. `SidebarTab` lays an absolute
         `z-99` control over the whole row whenever it has an `onClick`, and a
         statically positioned element can never paint above it — so without
         this the click lands on the row and navigates instead of folding.
         `rightChildren` solves the same problem the same way. */
      className="relative z-100 p-0 cursor-pointer"
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => {
        setHovering(false);
        setPreviewEnabled(true);
      }}
      onClick={noProp(() => {
        setPreviewEnabled(false);
        onToggle();
      })}
    >
      <Glyph size={16} className="text-text-03" />
    </button>
  );
}
