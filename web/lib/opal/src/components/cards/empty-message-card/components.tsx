import { Card } from "@opal/components/cards/card/components";
import { Content, SizePreset } from "@opal/layouts";
import { SvgEmpty } from "@opal/icons";
import type {
  IconFunctionComponent,
  PaddingVariants,
  RichStr,
} from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type EmptyMessageCardBaseProps = {
  /** Icon displayed alongside the title. */
  icon?: IconFunctionComponent;

  /** Primary message text. */
  title: string;

  /** Padding preset for the card. @default "md" */
  padding?: PaddingVariants;

  /** Ref forwarded to the root Card div. */
  ref?: React.Ref<HTMLDivElement>;
};

type EmptyMessageCardProps =
  | (EmptyMessageCardBaseProps & {
      /** @default "secondary" */
      sizePreset?: "secondary";
    })
  | (EmptyMessageCardBaseProps & {
      sizePreset: "main-ui";
      /** Description text. Only supported when `sizePreset` is `"main-ui"`. */
      description?: string | RichStr;
    });

// ---------------------------------------------------------------------------
// EmptyMessageCard
// ---------------------------------------------------------------------------

function EmptyMessageCard({
  sizePreset = "secondary",
  icon = SvgEmpty,
  title,
  padding = "md",
  ref,
  ...rest
}: EmptyMessageCardProps) {
  const description = "description" in rest ? rest.description : undefined;
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
