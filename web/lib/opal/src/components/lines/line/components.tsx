"use client";

import { Text } from "@opal/components/text/components";
import { Collapsible } from "@opal/components/collapsible/components";
import { Presence } from "@opal/components/presence/components";
import {
  LineRoot,
  type LineExpandableProps,
  type LineVariant,
} from "@opal/components/lines/line-base/components";
import { ContentIcon } from "@opal/layouts/content/components";
import { TextLoader } from "@opal/loaders/text-loader/components";
import type { IconFunctionComponent, RichStr } from "@opal/types";

/** A card's header: its own title, or any content. */
type LineCardHeaderProps =
  | {
      /** The title's icon, in a box one line tall, as `Content` draws it. */
      icon?: IconFunctionComponent;
      /**
       * The header's title, as `Content` lays out an inline title. A new
       * title animates the old one out and the new one in; a card's header
       * that toggles it darkens the title and the icon on hover.
       */
      title: string | RichStr;
      /** The title's identity: a new key swaps it. Defaults to its text. */
      titleKey?: React.Key;
      /** Shimmer the title, e.g. while the card's work runs. */
      shimmer?: boolean;
      children?: never;
    }
  | {
      /** The header: any content, such as a title that animates. */
      children: React.ReactNode;
      icon?: never;
      title?: never;
      titleKey?: never;
      shimmer?: never;
    };

type LineProps = LineExpandableProps &
  LineCardHeaderProps & {
    /**
     * Where the body starts: `flush` with the card's padding, or `title`,
     * under the header's title text (past its icon). @default "flush"
     */
    bodyInset?: "flush" | "title";
    /** Trailing content at the end of the header, such as the fold button. */
    rightChildren?: React.ReactNode;
    /** Fills the card with `background-tint-00`, e.g. while it is open. */
    filled: boolean;
    /**
     * Status and weight: colours the icon and the title; heavy also tints
     * the card, e.g. `error-heavy` for a failed step. @default "default"
     */
    variant?: LineVariant;
    /**
     * The fold button's label, e.g. "3 steps": the header's own button, which
     * lights up while the header is hovered. Without one, a card with
     * `onClick` shows a chevron.
     */
    foldLabel?: string;
    /**
     * Makes the header toggle the card: a click on it, or on its fold button,
     * calls this, and a folded card fills on hover.
     */
    onClick?: () => void;
  };

/** A card's own title: the icon and the title inline, as `Content` lays
 *  them out, so a running (shimmering) and a finished title line up. */
function LineCardTitle({
  icon: Icon,
  title,
  titleKey,
  shimmer,
}: {
  icon?: IconFunctionComponent;
  title: string | RichStr;
  titleKey?: React.Key;
  shimmer: boolean;
}) {
  const text = typeof title === "string" ? title : title.raw;
  return (
    // The title font on the row: the text's line boxes (a shimmer's span is
    // inline) then match the icon box, one title line tall. Block wrappers:
    // the icon, the swap and the loader render divs.
    <div className="opal-line-title opal-line-card-title font-main-ui-action">
      {Icon && <ContentIcon icon={Icon} font="main-ui-action" />}
      <Presence.Swap swapKey={titleKey ?? text} axis="inline">
        {/* One line: a long title truncates, shimmering or settled. */}
        <div className="opal-line-card-title-text">
          {shimmer ? (
            <TextLoader font="main-ui-action">{title}</TextLoader>
          ) : (
            <Text
              as="p"
              font="main-ui-action"
              color="inherit"
              maxLines={1}
              overflowTooltip
            >
              {title}
            </Text>
          )}
        </div>
      </Presence.Swap>
    </div>
  );
}

/**
 * A run card: a header (its own title, or any content) with trailing
 * controls, and a body below it that opens and closes. 0.25rem of padding,
 * 0.75rem corners, and a neutral fill while `filled`. A card inside a card's
 * body has no padding of its own, so its title lines up with the outer one.
 */
function Line({
  children,
  icon,
  title,
  titleKey,
  shimmer = false,
  rightChildren,
  filled,
  foldLabel,
  onClick,
  expandable,
  expanded,
  expandedContent,
  bodyInset = "flush",
  variant = "default",
}: LineProps) {
  return (
    <LineRoot
      variant={variant}
      padding={0}
      card
      filled={filled}
      clickable={!!onClick && !filled}
    >
      <Collapsible.Root
        open={!!expandable && expanded}
        onOpenChange={() => onClick?.()}
        // A card without `onClick` (e.g. a run with no steps yet) cannot fold.
        disabled={!onClick}
      >
        {/* Always the same header, foldable or not, so the header's content
            (e.g. a title in Presence.Swap) keeps its place when the card
            becomes foldable, and swaps instead of remounting. Its fold
            button carries the label (e.g. "N steps") and lights up while the
            header is hovered. */}
        <Collapsible.Header
          // The fold button is named after the card, e.g. "Expand Searched
          // the web".
          name={title}
          rightChildren={rightChildren}
          size="md"
          foldButton={
            !onClick ? "none" : foldLabel !== undefined ? "icon" : "chevron"
          }
          foldLabel={foldLabel}
        >
          {title !== undefined ? (
            <LineCardTitle
              icon={icon}
              title={title}
              titleKey={titleKey}
              shimmer={shimmer}
            />
          ) : (
            children
          )}
        </Collapsible.Header>
        {expandable && (
          <Collapsible.Content>
            <div
              className="opal-line-body"
              data-opal-line-body-inset={bodyInset}
              // `title` passes the icon only when the header shows one.
              data-opal-line-has-icon={icon !== undefined || undefined}
            >
              {expandedContent}
            </div>
          </Collapsible.Content>
        )}
      </Collapsible.Root>
    </LineRoot>
  );
}

export { Line, type LineProps };
