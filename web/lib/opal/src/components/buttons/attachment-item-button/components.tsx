import "@opal/components/buttons/attachment-item-button/styles.css";
import type React from "react";
import { Interactive, type InteractiveStatefulProps } from "@opal/core";
import type {
  ExtremaSizeVariants,
  IconFunctionComponent,
  RichStr,
} from "@opal/types";
import { InputCheckbox, Tooltip, type TooltipSide } from "@opal/components";
import {
  composeKeyHandler,
  guardNestedInteractiveClick,
  handleRowKeyDown,
  handleRowKeyUp,
} from "@opal/components/buttons/row-interaction";
import { Content } from "@opal/layouts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * The leading tile shows exactly one thing: an icon on the tinted tile, or an
 * image filling it. The union keeps the two exclusive, and makes `imageAlt`
 * mandatory the moment an image appears — the tile owns its chrome (size,
 * rounding, fit), so neither arm is a free-form slot.
 */
type AttachmentItemButtonTileProps =
  | {
      /** Icon centered on the tinted tile. */
      icon: IconFunctionComponent;
      imageSrc?: never;
      imageAlt?: never;
    }
  | {
      /** Image filling the tile (`object-fit: cover`, tile rounding). */
      imageSrc: string;
      /** Alt text for the image. Required — the image is content, not chrome. */
      imageAlt: string;
      icon?: never;
    };

/**
 * The `Content` props a row actually uses — enumerated rather than spread,
 * so that everything a caller passes which is *not* here is DOM, and reaches
 * the row element (the `RowContentProps` doctrine from `LineItemButton`).
 *
 * `sizePreset` and `variant` are deliberately not exposed: every attachment
 * row renders the same `main-ui`/`section` Content. The tile is this
 * component's identity; the Content axis stays frozen.
 */
type AttachmentItemButtonContentProps = {
  /** Main label. */
  title: string | RichStr;

  /**
   * Cap the title at N lines and truncate the rest. Defaults to `1` — these
   * rows show user-authored names (file names, token names).
   *
   * @default 1
   */
  titleMaxLines?: number;

  /** Secondary line under the title. */
  description?: string | RichStr;

  /**
   * Cap the description at N lines and truncate the rest.
   *
   * @default 1
   */
  descriptionMaxLines?: number;

  /** Enable inline editing of the title (Content's pencil affordance). */
  editable?: boolean;

  /** Called when the user commits a title edit. */
  onTitleChange?: (newTitle: string) => void;
};

/**
 * `presentational` and `href` are mutually exclusive. An anchor is a native
 * control — focusable, activated by Enter — which is exactly what the
 * presentational mode promises the row will not be.
 */
type AttachmentItemButtonModeProps =
  | {
      /**
       * Render the row as plain markup inside another interactive primitive:
       * no button role, no tab stop, no Enter/Space activation. The row keeps
       * its interactive palette — drive it with `state` / `prominence` /
       * `interaction` from the owning control. `role`, `tabIndex` and the key
       * handlers still pass through, so the owner can substitute its own
       * semantics.
       */
      presentational: true;
      href?: never;
      target?: never;
    }
  | ({ presentational?: false } & Pick<
      InteractiveStatefulProps,
      "href" | "target"
    >);

type AttachmentItemButtonOwnProps = Pick<
  InteractiveStatefulProps,
  "state" | "interaction" | "onClick" | "group" | "ref" | "disabled"
> &
  AttachmentItemButtonModeProps & {
    /**
     * Surface intensity at rest — hover, selected and disabled palettes
     * stay the same across all three.
     *
     * - `"primary"` — rests on `background-tint-00` (elevated rows on a card)
     * - `"secondary"` — rests on `background-tint-01` (rows on a plain page surface)
     * - `"tertiary"` — transparent at rest
     *
     * @default "tertiary"
     */
    prominence?: "primary" | "secondary" | "tertiary";

    /** Container width. @default "full" */
    width?: ExtremaSizeVariants;

    /** Tooltip text shown on hover. */
    tooltip?: string;

    /** Which side the tooltip appears on. @default "top" */
    tooltipSide?: TooltipSide;

    /**
     * Content rendered between the title group and the action slot. Expands
     * to fill the free width, so callers place counts, metadata or timestamps
     * here and align them inside the slot.
     */
    centerChildren?: React.ReactNode;

    /**
     * Trailing action slot. Keeps a minimum width of `--spacing-block-36`
     * even when empty or hover-hidden, so rows with and without actions align
     * and hover-revealed buttons cause no layout shift.
     */
    rightChildren?: React.ReactNode;
  };

/**
 * `title` is omitted from the DOM attributes because the row already means
 * something by it — its label — and the native attribute would put two
 * meanings in one prop. `children` is omitted because a row renders none:
 * its content comes from `title` and friends.
 */
type AttachmentItemButtonProps = AttachmentItemButtonOwnProps &
  AttachmentItemButtonTileProps &
  AttachmentItemButtonContentProps &
  Omit<React.HTMLAttributes<HTMLDivElement>, "title" | "children">;

// ---------------------------------------------------------------------------
// AttachmentItemButton
// ---------------------------------------------------------------------------

function AttachmentItemButton({
  // Interactive surface
  prominence = "tertiary",
  state,
  interaction,
  onClick,
  href,
  target,
  group,
  ref,
  disabled,
  presentational,

  // Sizing
  width = "full",
  tooltip,
  tooltipSide = "top",

  // Tile
  icon: Icon,
  imageSrc,
  imageAlt,

  // Content
  title,
  titleMaxLines = 1,
  description,
  descriptionMaxLines = 1,
  editable,
  onTitleChange,
  centerChildren,
  rightChildren,

  /*
   * Named so the row can defer to a caller's value instead of overwriting it.
   * They would otherwise ride `rowProps` onto the container and be replaced
   * by the button semantics spread after it — accepted by the type, then
   * gone.
   */
  role,
  tabIndex,
  onKeyDown,
  onKeyUp,

  /*
   * Whatever is left is DOM — labels, handlers, `data-*` — and belongs on
   * the row.
   */
  ...rowProps
}: AttachmentItemButtonProps) {
  // See row-interaction.ts: the row is a focusable div (role="button") so
  // interactive `rightChildren` don't nest a <button> inside a <button>.
  const rowButtonProps: Pick<
    React.HTMLAttributes<HTMLDivElement>,
    "role" | "tabIndex" | "onKeyDown" | "onKeyUp"
  > = presentational
    ? { role: role ?? "presentation", tabIndex, onKeyDown, onKeyUp }
    : href
      ? { role, tabIndex, onKeyDown, onKeyUp }
      : {
          role: role ?? "button",
          tabIndex: tabIndex ?? 0,
          onKeyDown: composeKeyHandler(onKeyDown, handleRowKeyDown),
          onKeyUp: composeKeyHandler(onKeyUp, handleRowKeyUp),
        };

  const item = (
    <Interactive.Stateful
      variant="select-heavy"
      prominence={prominence}
      state={state}
      interaction={interaction}
      onClick={guardNestedInteractiveClick(onClick)}
      href={href}
      target={target}
      group={group}
      ref={ref}
      disabled={disabled}
    >
      <Interactive.Container
        width={width}
        size="fit"
        rounding={3}
        {...rowProps}
        {...rowButtonProps}
      >
        <div className="opal-attachment-item-button">
          <div className="opal-attachment-item-button-title">
            <div className="opal-attachment-item-button-tile">
              {state === "selected" ? (
                /* Purely a visual indicator. `inert` + aria-hidden take the
                   checkbox out of the tab order, the accessibility tree and
                   the event flow — the row alone owns activation, and its
                   own selected styling carries the state for AT. */
                <span inert aria-hidden className="contents">
                  <InputCheckbox checked readOnly />
                </span>
              ) : imageSrc ? (
                <img
                  src={imageSrc}
                  alt={imageAlt}
                  className="opal-attachment-item-button-image"
                />
              ) : (
                Icon && <Icon className="opal-attachment-item-button-icon" />
              )}
            </div>
            <Content
              sizePreset="main-ui"
              variant="section"
              color="interactive"
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
            <div className="opal-attachment-item-button-center">
              {centerChildren}
            </div>
          )}
          <div className="opal-attachment-item-button-action">
            {rightChildren}
          </div>
        </div>
      </Interactive.Container>
    </Interactive.Stateful>
  );

  return (
    <Tooltip tooltip={tooltip} side={tooltipSide}>
      {item}
    </Tooltip>
  );
}

export { AttachmentItemButton, type AttachmentItemButtonProps };
