import { Card } from "@opal/components/cards/card/components";
import { Content } from "@opal/layouts";
import { SvgEmpty } from "@opal/icons";
import type { SizeVariant } from "@opal/shared";
import type { IconFunctionComponent } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type EmptyMessageCardProps = {
  /** Icon displayed alongside the title. */
  icon?: IconFunctionComponent;

  /** Primary message text. */
  title: string;

  /** Size preset controlling padding and rounding of the card. */
  sizeVariant?: SizeVariant;

  /** Ref forwarded to the root Card div. */
  ref?: React.Ref<HTMLDivElement>;

  /** Additional CSS classes forwarded to the root Card div. */
  className?: string;
};

// ---------------------------------------------------------------------------
// EmptyMessageCard
// ---------------------------------------------------------------------------

function EmptyMessageCard({
  icon = SvgEmpty,
  title,
  sizeVariant = "lg",
  ref,
  className,
}: EmptyMessageCardProps) {
  return (
    <Card
      ref={ref}
      backgroundVariant="none"
      borderVariant="dashed"
      sizeVariant={sizeVariant}
      className={className}
    >
      <Content
        icon={icon}
        title={title}
        sizePreset="secondary"
        variant="body"
        prominence="muted"
      />
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { EmptyMessageCard, type EmptyMessageCardProps };
