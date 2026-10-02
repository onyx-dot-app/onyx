"use client";

import "@opal/components/cards/message-card/styles.css";
import { cn } from "@opal/utils";
import type {
  CardColor,
  IconFunctionComponent,
  RichStr,
  ShadowVariants,
  StatusVariants,
} from "@opal/types";
import { spacingToRem } from "@opal/shared";
import { ContentAction } from "@opal/layouts";
import { Card } from "@opal/components/cards/card/components";
import { Button, Divider } from "@opal/components";
import {
  SvgAlertCircle,
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgClock,
  SvgX,
  SvgXOctagon,
} from "@opal/icons";
import { useState } from "react";
import { useOpalStrings } from "@opal/strings";
import usePresence from "@opal/hooks/usePresence";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MessageCardBaseProps {
  /** Visual variant controlling background, border, and icon. @default "default" */
  variant?: StatusVariants;

  /** Override the default variant icon. */
  icon?: IconFunctionComponent;

  /** Main title text. */
  title: string | RichStr;

  /** Optional description below the title. */
  description?: string | RichStr;

  /** Clamp the title to N lines with ellipsis. Default: `1`. Pass `undefined` to wrap freely. */
  titleMaxLines?: number;

  /**
   * Padding of the outer card, as a spacing step (`N / 4` rem). Narrowed on
   * purpose — a message card is a fixed-density surface, so only these two
   * densities are offered.
   *
   * @default 2
   */
  outerPadding?: 1 | 2;

  /**
   * Padding around the header Content area, as a spacing step. Narrowed like
   * `outerPadding`: cards inside a modal or popover use 1 for both, cards on
   * a page use 2 for both.
   *
   * @default 2
   */
  innerPadding?: 1 | 2;

  /**
   * Padding of the `ContentAction` itself, inside `innerPadding`, as a
   * spacing step.
   *
   * @default 0
   */
  contentPadding?: 0 | 1 | 2;

  /**
   * Drop-shadow depth of the card, passed to `Card`.
   *
   * @default "none"
   */
  shadow?: ShadowVariants;

  /**
   * Content rendered below a divider, under the main content area.
   * When provided, a `Divider` is inserted between the `ContentAction` and this node.
   * Adding or removing it animates the section open or closed; a card that
   * mounts with it does not animate.
   */
  bottomChildren?: React.ReactNode;

  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;
}

type MessageCardProps = MessageCardBaseProps &
  (
    | {
        /** Content rendered on the right side of the card. Mutually exclusive with `onClose`. */
        rightChildren?: React.ReactNode;
        onClose?: never;
      }
    | {
        rightChildren?: never;
        /** Close button callback. Mutually exclusive with `rightChildren`. */
        onClose?: () => void;
      }
  );

// ---------------------------------------------------------------------------
// Variant config
// ---------------------------------------------------------------------------

const VARIANT_CONFIG: Record<
  StatusVariants,
  { icon: IconFunctionComponent; iconClass: string; color: CardColor }
> = {
  default: {
    icon: SvgAlertCircle,
    iconClass: "stroke-text-03",
    color: "background-tint-01",
  },
  info: {
    icon: SvgAlertCircle,
    iconClass: "stroke-status-info-05",
    color: "status-info-00",
  },
  success: {
    icon: SvgCheckCircle,
    iconClass: "stroke-status-success-05",
    color: "status-success-00",
  },
  warning: {
    icon: SvgAlertTriangle,
    iconClass: "stroke-status-warning-05",
    color: "status-warning-00",
  },
  pending: {
    icon: SvgClock,
    iconClass: "stroke-theme-amber-05",
    color: "theme-amber-01",
  },
  error: {
    icon: SvgXOctagon,
    iconClass: "stroke-status-error-05",
    color: "status-error-00",
  },
};

// ---------------------------------------------------------------------------
// MessageCard
// ---------------------------------------------------------------------------

/**
 * A styled card for displaying messages, alerts, or status notifications.
 *
 * Uses `ContentAction` internally for consistent title/description/icon layout
 * with optional right-side actions. Supports 5 variants with corresponding
 * background, border, and icon colors.
 *
 * `onClose` and `rightChildren` are mutually exclusive — specify one or neither.
 *
 * @example
 * ```tsx
 * import { MessageCard } from "@opal/components";
 *
 * // Simple message
 * <MessageCard
 *   variant="info"
 *   title="Heads up"
 *   description="Changes apply to newly indexed documents only."
 * />
 *
 * // With close button
 * <MessageCard
 *   variant="warning"
 *   title="Re-indexing required"
 *   onClose={() => setDismissed(true)}
 * />
 *
 * // With right children
 * <MessageCard
 *   variant="error"
 *   title="Connection failed"
 *   rightChildren={<Button>Retry</Button>}
 * />
 * ```
 */
function MessageCard({
  variant = "default",
  icon: iconOverride,
  title,
  description,
  titleMaxLines,
  outerPadding = 2,
  innerPadding = 2,
  contentPadding = 0,
  shadow = "none",
  bottomChildren,
  rightChildren,
  onClose,
  ref,
}: MessageCardProps) {
  const { icon: DefaultIcon, iconClass, color } = VARIANT_CONFIG[variant];
  const Icon = iconOverride ?? DefaultIcon;
  const strings = useOpalStrings();
  const expanded = bottomChildren != null;
  const presence = usePresence(expanded, 200);
  // Animate only once the section has come or gone, so a card that mounts
  // with it does not play the opening on page load.
  const [toggled, setToggled] = useState(false);
  const [prevExpanded, setPrevExpanded] = useState(expanded);
  if (expanded !== prevExpanded) {
    setPrevExpanded(expanded);
    setToggled(true);
  }
  // The last section shown, kept so it can animate out after the caller
  // drops it.
  const [shownBottom, setShownBottom] = useState(bottomChildren);
  if (bottomChildren != null && bottomChildren !== shownBottom) {
    setShownBottom(bottomChildren);
  }

  const right = onClose ? (
    <Button
      icon={SvgX}
      prominence="internal"
      size="md"
      onClick={onClose}
      aria-label={strings.close}
      data-message-card-close=""
    />
  ) : (
    rightChildren
  );

  // Built on Card: the root owns color, border, rounding, and padding, so
  // this component keeps only its message layout. The wrapper preserves the
  // stretch behavior the old root class carried, since Card takes no
  // className.
  return (
    <div className="opal-message-card" ref={ref} data-variant={variant}>
      <Card
        color={color}
        border="solid"
        borderColor={variant}
        rounding={4}
        padding={outerPadding}
        shadow={shadow}
      >
        <div className="opal-message-card-layout">
          <div style={{ padding: spacingToRem(innerPadding) }}>
            <ContentAction
              icon={(props) => (
                <Icon {...props} className={cn(props.className, iconClass)} />
              )}
              title={title}
              description={description}
              titleMaxLines={titleMaxLines}
              sizePreset="main-ui"
              variant="section"
              rightChildren={right}
              padding={contentPadding}
            />
          </div>

          {presence.mounted && (
            <div
              className="opal-message-card-bottom"
              data-state={presence.state}
              data-animate={toggled || undefined}
              onAnimationEnd={presence.onAnimationEnd}
            >
              <div className="opal-message-card-bottom-inner">
                <Divider paddingParallel={3} paddingPerpendicular={0} />
                {bottomChildren ?? shownBottom}
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

export { MessageCard, type MessageCardProps };
