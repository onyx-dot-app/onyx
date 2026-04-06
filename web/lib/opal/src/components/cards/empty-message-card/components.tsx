import { Card } from "@opal/components/cards/card/components";
import { Content, SizePreset } from "@opal/layouts";
import { SvgEmpty } from "@opal/icons";
import type { IconFunctionComponent, PaddingVariants } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type EmptyMessageCardProps = {
  sizePreset?: Extract<SizePreset, "main-ui" | "secondary">;
  /** Icon displayed alongside the title. */
  icon?: IconFunctionComponent;

  /** Primary message text. */
  title: string;

  /** Description text. */
  description?: string;

  /** Padding preset for the card. @default "md" */
  padding?: PaddingVariants;

  /** Ref forwarded to the root Card div. */
  ref?: React.Ref<HTMLDivElement>;
};

// ---------------------------------------------------------------------------
// EmptyMessageCard
// ---------------------------------------------------------------------------

function EmptyMessageCard({
  sizePreset = "secondary",
  icon = SvgEmpty,
  title,
  description,
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
      {sizePreset === "secondary" ? (
        <Content
          icon={icon}
          title={title}
          sizePreset="secondary"
          variant="body"
          prominence="muted"
        />
      ) : (
        <Content
          icon={icon}
          title={title}
          description={description}
          sizePreset={sizePreset}
          variant="section"
        />
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { EmptyMessageCard, type EmptyMessageCardProps };
