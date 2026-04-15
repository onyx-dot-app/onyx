import "@opal/components/cards/message-card/styles.css";
import { cn } from "@opal/utils";
import type { RichStr, IconFunctionComponent } from "@opal/types";
import { ContentAction } from "@opal/layouts";
import { Button, Divider } from "@opal/components";
import {
  SvgAlertCircle,
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgX,
  SvgXOctagon,
} from "@opal/icons";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type MessageCardVariant = "default" | "info" | "success" | "warning" | "error";

interface MessageCardBaseProps {
  /** Visual variant controlling background, border, and icon. @default "default" */
  variant?: MessageCardVariant;

  /** Override the default variant icon. */
  icon?: IconFunctionComponent;

  /** Main title text. */
  title: string | RichStr;

  /** Optional description below the title. */
  description?: string | RichStr;

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
  MessageCardVariant,
  { icon: IconFunctionComponent; iconClass: string }
> = {
  default: { icon: SvgAlertCircle, iconClass: "stroke-text-03" },
  info: { icon: SvgAlertCircle, iconClass: "stroke-status-info-05" },
  success: { icon: SvgCheckCircle, iconClass: "stroke-status-success-05" },
  warning: { icon: SvgAlertTriangle, iconClass: "stroke-status-warning-05" },
  error: { icon: SvgXOctagon, iconClass: "stroke-status-error-05" },
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
  bottomChildren,
  rightChildren,
  onClose,
  ref,
}: MessageCardProps) {
  const { icon: DefaultIcon, iconClass } = VARIANT_CONFIG[variant];
  const Icon = iconOverride ?? DefaultIcon;

  const right = onClose ? (
    <Button
      icon={SvgX}
      prominence="internal"
      size="md"
      onClick={onClose}
      aria-label="Close"
    />
  ) : (
    rightChildren
  );

  return (
    <div className="opal-message-card" data-variant={variant} ref={ref}>
      <ContentAction
        icon={(props) => (
          <Icon {...props} className={cn(props.className, iconClass)} />
        )}
        title={title}
        description={description}
        sizePreset="main-ui"
        variant="section"
        paddingVariant="lg"
        rightChildren={right}
      />

      {bottomChildren && (
        <>
          <Divider paddingParallel="sm" paddingPerpendicular="xs" />
          {bottomChildren}
        </>
      )}
    </div>
  );
}

export { MessageCard, type MessageCardProps, type MessageCardVariant };
