import { Card } from "@opal/components/cards/card/components";
import { Content } from "@opal/layouts";
import { SvgEmpty } from "@opal/icons";
import type { StandardDiscriminatedSizeVariants } from "@opal/shared";
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
  sizeVariant?: StandardDiscriminatedSizeVariants;

  /** Ref forwarded to the root Card div. */
  ref?: React.Ref<HTMLDivElement>;
};

// ---------------------------------------------------------------------------
// EmptyMessageCard
// ---------------------------------------------------------------------------

function EmptyMessageCard({
  icon = SvgEmpty,
  title,
  sizeVariant = "lg",
  ref,
}: EmptyMessageCardProps) {
  return (
    <Card
      ref={ref}
      backgroundVariant="none"
      borderVariant="dashed"
      sizeVariant={sizeVariant}
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
