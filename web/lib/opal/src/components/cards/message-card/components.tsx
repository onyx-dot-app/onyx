import "@opal/components/cards/message-card/styles.css";
import type { RichStr, IconFunctionComponent } from "@opal/types";
import { Content } from "@opal/layouts";
import { Button, Card, Divider } from "@opal/components";
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

interface MessageCardProps {
  /** Visual variant controlling background, border, and icon. @default "default" */
  variant?: MessageCardVariant;

  /** Main title text. */
  title: string | RichStr;

  /** Optional description below the title. */
  description?: string | RichStr;

  /**
   * Content rendered below a divider, under the main content area.
   * When provided, a `Divider` is inserted between the `Content` and this node.
   */
  bottomChildren?: React.ReactNode;

  /**
   * Called when the close button is clicked. When omitted, no close button
   * is rendered.
   */
  onClose?: () => void;

  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;
}

// ---------------------------------------------------------------------------
// Default icons per variant
// ---------------------------------------------------------------------------

const DEFAULT_ICONS: Record<MessageCardVariant, IconFunctionComponent> = {
  default: SvgAlertCircle,
  info: SvgAlertCircle,
  success: SvgCheckCircle,
  warning: SvgAlertTriangle,
  error: SvgXOctagon,
};

// ---------------------------------------------------------------------------
// MessageCard
// ---------------------------------------------------------------------------

/**
 * A styled card for displaying messages, alerts, or status notifications.
 *
 * Uses `Card` as the structural base and `Content` internally for consistent
 * title/description/icon layout. Supports 5 variants with corresponding
 * background and border colors.
 *
 * @example
 * ```tsx
 * import { MessageCard } from "@opal/components";
 *
 * <MessageCard
 *   variant="info"
 *   title="Heads up"
 *   description="Changes apply to newly indexed documents only."
 * />
 *
 * <MessageCard
 *   variant="warning"
 *   title="Re-indexing required"
 *   description="Toggle this setting to re-index all documents."
 *   onClose={() => setDismissed(true)}
 *   bottomChildren={<Button>Re-index Now</Button>}
 * />
 * ```
 */
function MessageCard({
  variant = "default",
  title,
  description,
  bottomChildren,
  onClose,
  ref,
}: MessageCardProps) {
  const Icon = DEFAULT_ICONS[variant];

  return (
    <div className="opal-message-card" data-variant={variant}>
      <div className="opal-message-card-header">
        <div className="opal-message-card-content">
          <Content
            icon={Icon}
            title={title}
            description={description}
            sizePreset="main-ui"
            variant="section"
          />
        </div>

        {onClose && (
          <Button
            icon={SvgX}
            prominence="internal"
            size="sm"
            onClick={onClose}
            aria-label="Close"
          />
        )}
      </div>

      {bottomChildren && (
        <>
          <Divider paddingParallel="fit" paddingPerpendicular="xs" />
          {bottomChildren}
        </>
      )}
    </div>
  );
}

export { MessageCard, type MessageCardProps, type MessageCardVariant };
