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

export interface AttachmentProps
  extends WithoutStyles<React.ButtonHTMLAttributes<HTMLButtonElement>> {
  selected?: boolean;
  processing?: boolean;

  icon: React.FunctionComponent<IconProps>;
  children: string;
  description?: string;
  rightText?: string;
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
  const state = selected ? "selected" : processing ? "processing" : "default";

  return (
    <button
      type="button"
      className="attachment-button"
      data-state={state}
      {...props}
    >
      <div className="attachment-button__content">
        <div className="attachment-button__icon-wrapper">
          {selected ? (
            <Checkbox checked />
          ) : (
            <Icon className="attachment-button__icon" />
          )}
        </div>
        <div className="attachment-button__text-container">
          <div className="attachment-button__title-row">
            <div className="attachment-button__title-wrapper">
              <Truncated mainUiMuted text04 nowrap>
                {children}
              </Truncated>
            </div>
            {onView && (
              <IconButton
                icon={SvgExternalLink}
                onClick={noProp(onView)}
                internal
                className="attachment-button__view-button"
              />
            )}
          </div>
          {description && (
            <Truncated secondaryBody text03 className="w-full">
              {description}
            </Truncated>
          )}
        </div>
      </div>

      <div className="attachment-button__actions">
        {rightText && (
          <Text as="p" secondaryBody text03>
            {rightText}
          </Text>
        )}
        {actionIcon && onAction && (
          <div className="attachment-button__action-button">
            <IconButton icon={actionIcon} onClick={noProp(onAction)} internal />
          </div>
        )}
      </div>
    </button>
  );
}
