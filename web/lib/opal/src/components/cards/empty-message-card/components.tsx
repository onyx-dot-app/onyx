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

  /** Padding preset for the card. @default "md" */
  padding?: PaddingVariants;

  /** Ref forwarded to the root Card div. */
  ref?: React.Ref<HTMLDivElement>;
};

// ---------------------------------------------------------------------------
// EmptyMessageCard
// ---------------------------------------------------------------------------

function EmptyMessageCard({
  icon = SvgEmpty,
  title,
  padding = "md",
  ref,
}: EmptyMessageCardProps) {
  return (
    <Card
      ref={ref}
      background="none"
      border="dashed"
      padding={padding}
      rounding="md"
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
