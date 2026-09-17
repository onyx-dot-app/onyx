"use client";

import "@opal/components/cards/message-card/styles.css";
import { cn } from "@opal/utils";
import type {
  CardColor,
  IconFunctionComponent,
  Spacing,
  RichStr,
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
import { useOpalStrings } from "@opal/strings";

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
   * Padding, as a spacing step (`N / 4` rem). Narrowed on purpose — a message
   * card is a fixed-density surface, so only these two densities are offered.
   *
   * @default 2
   */
  padding?: 1 | 2;

  /** Padding around the header Content area, as a spacing step. @default 0 */
  headerPadding?: Spacing;

  /**
   * Content rendered below a divider, under the main content area.
   * When provided, a `Divider` is inserted between the `ContentAction` and this node.
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
  padding = 2,
  headerPadding = 0,
  bottomChildren,
  rightChildren,
  onClose,
  ref,
}: MessageCardProps) {
  const { icon: DefaultIcon, iconClass, color } = VARIANT_CONFIG[variant];
  const Icon = iconOverride ?? DefaultIcon;
  const strings = useOpalStrings();

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
        padding={padding}
      >
        <div className="opal-message-card-layout">
          <div style={{ padding: spacingToRem(headerPadding) }}>
            <ContentAction
              icon={(props) => (
                <Icon {...props} className={cn(props.className, iconClass)} />
              )}
              title={title}
              description={description}
              titleMaxLines={titleMaxLines}
              sizePreset="main-ui"
              variant="section"
              padding={1}
              rightChildren={right}
            />
          </div>

          {bottomChildren && (
            <>
              <Divider paddingParallel={2} paddingPerpendicular={1} />
              {bottomChildren}
            </>
          )}
        </div>
      </Card>
    </div>
  );
}

export { MessageCard, type MessageCardProps };
