/**
 * AttachmentButton - A button component for displaying file attachments or similar items
 *
 * Displays an attachment item with an icon, title, description, metadata text,
 * and optional action buttons. Commonly used for file lists, attachment pickers,
 * and similar UI patterns where items can be viewed or acted upon.
 *
 * Features:
 * - Three visual states: default, selected (shows checkbox), processing
 * - Left icon that changes to checkbox when selected
 * - Truncated title and description text
 * - Right-aligned metadata text (e.g., file size, date)
 * - Optional view button (external link icon) that appears on hover
 * - Optional action button (custom icon) that appears on hover
 * - Full-width button with hover states
 * - Prevents event bubbling for nested action buttons
 *
 * @example
 * ```tsx
 * import AttachmentButton from "@/refresh-components/buttons/AttachmentButton";
 * import { SvgFileText, SvgTrash } from "@opal/icons";
 *
 * // Basic attachment
 * <AttachmentButton
 *   icon={SvgFileText}
 *   description="document.pdf"
 *   rightText="2.4 MB"
 * >
 *   Project Proposal
 * </AttachmentButton>
 *
 * // Selected state with view button
 * <AttachmentButton
 *   icon={SvgFileText}
 *   selected
 *   description="document.pdf"
 *   rightText="2.4 MB"
 *   onView={() => window.open('/view/doc')}
 * >
 *   Project Proposal
 * </AttachmentButton>
 *
 * // With action button (delete)
 * <AttachmentButton
 *   icon={SvgFileText}
 *   description="document.pdf"
 *   rightText="2.4 MB"
 *   actionIcon={SvgTrash}
 *   onAction={() => handleDelete()}
 * >
 *   Project Proposal
 * </AttachmentButton>
 *
 * // Processing state
 * <AttachmentButton
 *   icon={SvgFileText}
 *   processing
 *   description="Uploading..."
 *   rightText="45%"
 * >
 *   Project Proposal
 * </AttachmentButton>
 * ```
 */

import React from "react";
import { cn, noProp } from "@/lib/utils";
import Truncated from "@/refresh-components/texts/Truncated";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";
import type { IconProps } from "@opal/types";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import { SvgExternalLink } from "@opal/icons";
import { WithoutStyles } from "@/types";

const bgClassNames = {
  defaulted: ["bg-background-tint-00"],
  selected: ["bg-action-link-01"],
  processing: ["bg-background-tint-00"],
} as const;

const iconClassNames = {
  defaulted: ["stroke-text-02"],
  selected: [],
  processing: ["stroke-text-01"],
} as const;

export interface AttachmentProps
  extends WithoutStyles<React.ButtonHTMLAttributes<HTMLButtonElement>> {
  selected?: boolean;
  processing?: boolean;

  icon: React.FunctionComponent<IconProps>;
  children: string;
  description: string;
  rightText: string;
  onView?: () => void;

  // Action button: An optional secondary action button that appears on hover.
  // Commonly used for actions like delete, download, or remove.
  // Both `actionIcon` and `onAction` must be provided for the button to appear.
  actionIcon?: React.FunctionComponent<IconProps>;
  onAction?: () => void;
}

export default function AttachmentButton({
  selected,
  processing,
  icon: Icon,
  children,
  description,
  rightText,
  onView,
  actionIcon,
  onAction,
  ...props
}: AttachmentProps) {
  const variant = selected
    ? "selected"
    : processing
      ? "processing"
      : "defaulted";

  return (
    <button
      type="button"
      className={cn(
        "flex flex-row w-full p-1 bg-background-tint-00 hover:bg-background-tint-02 rounded-12 gap-2 group/Attachment",
        bgClassNames[variant]
      )}
      {...props}
    >
      <div className="flex-1 flex flex-row gap-2 min-w-0">
        <div className="h-full aspect-square bg-background-tint-01 rounded-08 flex flex-col items-center justify-center shrink-0">
          {selected ? (
            <Checkbox checked />
          ) : (
            <Icon
              className={cn(iconClassNames[variant], "h-[1rem] w-[1rem]")}
            />
          )}
        </div>
        <div className="flex flex-col items-start justify-center min-w-0 flex-1">
          <div className="flex flex-row items-center gap-2 w-full min-w-0">
            <div className="max-w-[70%] min-w-0 shrink overflow-hidden">
              <Truncated mainUiMuted text04 nowrap className="truncate !w-full">
                {children}
              </Truncated>
            </div>
            {onView && (
              <IconButton
                icon={SvgExternalLink}
                onClick={noProp(onView)}
                internal
                className="invisible group-hover/Attachment:visible shrink-0"
              />
            )}
          </div>
          <Truncated secondaryBody text03 className="w-full">
            {description}
          </Truncated>
        </div>
      </div>

      <div className="flex flex-row self-stretch justify-end items-center gap-2 p-1 shrink-0">
        <Text as="p" secondaryBody text03>
          {rightText}
        </Text>
        {actionIcon && onAction && (
          <div className="invisible group-hover/Attachment:visible">
            <IconButton icon={actionIcon} onClick={noProp(onAction)} internal />
          </div>
        )}
      </div>
    </button>
  );
}
