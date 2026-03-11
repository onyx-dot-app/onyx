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
  size?: SizeVariant;

  /** Ref forwarded to the root Card div. */
  ref?: React.Ref<HTMLDivElement>;
};

// ---------------------------------------------------------------------------
// EmptyMessageCard
// ---------------------------------------------------------------------------

function EmptyMessageCard({
  icon = SvgEmpty,
  title,
  size = "lg",
  ref,
}: EmptyMessageCardProps) {
  return (
    <Card
      ref={ref}
      backgroundVariant="none"
      borderVariant="dashed"
      sizeVariant={size}
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
