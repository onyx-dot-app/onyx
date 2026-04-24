import { Card } from "@opal/components/cards/card/components";
import { Content } from "@opal/layouts";
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
  title: string | RichStr;

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
      /** Optional description text. */
      description?: string | RichStr;
    });

// ---------------------------------------------------------------------------
// EmptyMessageCard
// ---------------------------------------------------------------------------

function EmptyMessageCard(props: EmptyMessageCardProps) {
  const {
    sizePreset = "secondary",
    icon = SvgEmpty,
    title,
    padding = "md",
    ref,
  } = props;

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
          description={"description" in props ? props.description : undefined}
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
