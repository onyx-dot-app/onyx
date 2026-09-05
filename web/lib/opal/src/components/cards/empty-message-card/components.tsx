import { Card } from "@opal/components/cards/card/components";
import { Content } from "@opal/layouts";
import { SvgEmpty } from "@opal/icons";
import type { IconFunctionComponent, RichStr } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type EmptyMessageCardBaseProps = {
  /** Icon displayed alongside the title. */
  icon?: IconFunctionComponent;

  /** Primary message text. */
  title: string | RichStr;

  /**
   * Padding around the card, as a spacing step (`N / 4` rem).
   *
   * A closed set: an empty state is a fixed presentation, not a surface callers
   * lay out themselves, so it offers the densities the named scale did and no
   * more. `Card` stays open — it is the general-purpose container.
   *
   * @default 4
   */
  padding?: 0 | 0.5 | 1 | 2 | 4 | 6;

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
    padding = 4,
    ref,
  } = props;

  return (
    <Card
      ref={ref}
      background="none"
      border="dashed"
      padding={padding}
      rounding={3}
    >
      {sizePreset === "secondary" ? (
        <Content
          icon={icon}
          title={title}
          sizePreset="secondary"
          variant="body"
          color="muted"
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
