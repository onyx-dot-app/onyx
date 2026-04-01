import { Card } from "@opal/components/cards/card/components";
import { Content } from "@opal/layouts";
import { SvgEmpty } from "@opal/icons";
import type { IconFunctionComponent, PaddingVariants } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type EmptyMessageCardProps = {
  /** Icon displayed alongside the title. */
  icon?: IconFunctionComponent;

  /** Primary message text. */
  title: string;

  /** Padding preset for the card. */
  paddingVariant?: PaddingVariants;

  /** Ref forwarded to the root Card div. */
  ref?: React.Ref<HTMLDivElement>;
};

// ---------------------------------------------------------------------------
// EmptyMessageCard
// ---------------------------------------------------------------------------

function EmptyMessageCard({
  icon = SvgEmpty,
  title,
  paddingVariant = "sm",
  ref,
}: EmptyMessageCardProps) {
  return (
    <Card
      ref={ref}
      backgroundVariant="none"
      borderVariant="dashed"
      paddingVariant={paddingVariant}
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
