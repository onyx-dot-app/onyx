import "@opal/layouts/attachment-item/styles.css";
import type React from "react";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { Content } from "@opal/layouts/content/components";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * The leading tile shows exactly one thing: an icon on the tinted tile, or an
 * image filling it. The union keeps the two exclusive, and makes `imageAlt`
 * mandatory the moment an image appears.
 */
type AttachmentItemTileProps =
  | {
      /** Icon centered on the tinted tile. */
      icon: IconFunctionComponent;
      imageSrc?: never;
      imageAlt?: never;
    }
  | {
      /** Image filling the tile (`object-fit: cover`, tile rounding). */
      imageSrc: string;
      /** Alt text for the image. Required: the image is content. */
      imageAlt: string;
      icon?: never;
    };

type AttachmentItemProminence = "primary" | "secondary" | "tertiary";

interface AttachmentItemContentProps {
  /** Main label. */
  title: string | RichStr;
  /** Cap the title at N lines. @default 1 */
  titleMaxLines?: number;
  /** Secondary line under the title. */
  description?: string | RichStr;
  /** Cap the description at N lines. @default 1 */
  descriptionMaxLines?: number;
  /** Content between the title group and the action slot; fills the width. */
  centerChildren?: React.ReactNode;
  /** Trailing slot, reserved even when empty so rows align. */
  rightChildren?: React.ReactNode;
}

/** `title` is the row's label, so the native attribute is left out. */
type AttachmentItemDomProps = Omit<
  React.HTMLAttributes<HTMLDivElement>,
  "title" | "children"
>;

/**
 * The row the static `AttachmentItem` and the interactive
 * `AttachmentItemButton` share. Internal to Opal: callers use one of those
 * two.
 */
type AttachmentItemBodyProps = AttachmentItemContentProps &
  AttachmentItemTileProps &
  AttachmentItemDomProps & {
    /**
     * The row's own surface. Left out, the row paints none and takes the
     * surface it sits on, such as `Interactive.Container`.
     */
    surface?: AttachmentItemProminence;
    /** Replaces the tile's icon or image, e.g. a selected checkbox. */
    tileOverride?: React.ReactNode;
    /** Enable inline editing of the title (Content's pencil affordance). */
    editable?: boolean;
    /** Called when the user commits a title edit. */
    onTitleChange?: (newTitle: string) => void;
  };

type AttachmentItemProps = AttachmentItemContentProps &
  AttachmentItemTileProps &
  AttachmentItemDomProps & {
    /**
     * The row's surface: `"primary"` on `background-tint-00`, `"secondary"`
     * on `background-tint-01`, `"tertiary"` transparent.
     *
     * @default "tertiary"
     */
    prominence?: AttachmentItemProminence;
  };

// ---------------------------------------------------------------------------
// AttachmentItemBody
// ---------------------------------------------------------------------------

function AttachmentItemBody({
  icon: Icon,
  imageSrc,
  imageAlt,
  title,
  titleMaxLines = 1,
  description,
  descriptionMaxLines = 1,
  centerChildren,
  rightChildren,
  surface,
  tileOverride,
  editable,
  onTitleChange,
  ...rowProps
}: AttachmentItemBodyProps) {
  return (
    <div {...rowProps} className="opal-attachment-item" data-surface={surface}>
      <div className="opal-attachment-item-title">
        <div className="opal-attachment-item-tile">
          {tileOverride ??
            (imageSrc ? (
              <img
                src={imageSrc}
                alt={imageAlt}
                className="opal-attachment-item-image"
              />
            ) : (
              Icon && <Icon className="opal-attachment-item-icon" />
            ))}
        </div>
        {/* Inside AttachmentItemButton the title follows the row's
            Interactive palette. A static row keeps its own colors, so an
            unrelated Interactive ancestor cannot restyle it. */}
        <Content
          sizePreset="main-ui"
          variant="section"
          color={surface ? "default" : "interactive"}
          title={title}
          titleMaxLines={titleMaxLines}
          description={description}
          descriptionMaxLines={descriptionMaxLines}
          editable={editable}
          onTitleChange={onTitleChange}
          width="full"
        />
      </div>
      {centerChildren != null && (
        <div className="opal-attachment-item-center">{centerChildren}</div>
      )}
      <div className="opal-attachment-item-action">{rightChildren}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AttachmentItem
// ---------------------------------------------------------------------------

/**
 * A static row for a file-like resource: the `AttachmentItemButton` layout
 * (tile, title and description, center slot, action slot) with no
 * interactive surface. It has no hover, focus or click of its own; controls
 * go in `rightChildren`.
 */
function AttachmentItem({
  prominence = "tertiary",
  ...props
}: AttachmentItemProps) {
  return <AttachmentItemBody {...props} surface={prominence} />;
}

export {
  AttachmentItem,
  AttachmentItemBody,
  type AttachmentItemProps,
  type AttachmentItemBodyProps,
  type AttachmentItemTileProps,
};
