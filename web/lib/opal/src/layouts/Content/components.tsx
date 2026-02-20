import "@opal/layouts/Content/styles.css";
import {
  BodyLayout,
  type BodyOrientation,
  type BodyProminence,
} from "@opal/layouts/Content/BodyLayout";
import {
  HeadingLayout,
  type HeadingLayoutProps,
} from "@opal/layouts/Content/HeadingLayout";
import {
  LabelLayout,
  type LabelLayoutProps,
} from "@opal/layouts/Content/LabelLayout";
import type { TagProps } from "@opal/components/Tag/components";
import type { IconFunctionComponent } from "@opal/types";

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

type SizePreset =
  | "headline"
  | "section"
  | "main-content"
  | "main-ui"
  | "secondary";

type ContentVariant = "heading" | "section" | "body";

interface ContentBaseProps {
  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /** Main title text. */
  title: string;

  /** Optional description below the title. */
  description?: string;

  /** Enable inline editing of the title. */
  editable?: boolean;

  /** Called when the user commits an edit. */
  onTitleChange?: (newTitle: string) => void;
}

// ---------------------------------------------------------------------------
// Discriminated union: valid sizePreset × variant combinations
// ---------------------------------------------------------------------------

type HeadingContentProps = ContentBaseProps & {
  /** Size preset. Default: `"headline"`. */
  sizePreset?: "headline" | "section";
  /** Variant. Default: `"heading"` for heading-eligible presets. */
  variant?: "heading" | "section";
};

type LabelContentProps = ContentBaseProps & {
  sizePreset: "main-content" | "main-ui" | "secondary";
  variant?: "section";
  /** When `true`, renders "(Optional)" beside the title in the muted font variant. */
  optional?: boolean;
  /** Auxiliary status icon rendered beside the title. */
  auxIcon?: "info-gray" | "info-blue" | "warning" | "error";
  /** Tag rendered beside the title. */
  tag?: TagProps;
};

/** BodyLayout does not support descriptions or inline editing. */
type BodyContentProps = Omit<
  ContentBaseProps,
  "description" | "editable" | "onTitleChange"
> & {
  sizePreset: "main-content" | "main-ui" | "secondary";
  variant: "body";
  /** Layout orientation. Default: `"inline"`. */
  orientation?: BodyOrientation;
  /** Title prominence. Default: `"default"`. */
  prominence?: BodyProminence;
};

type ContentProps = HeadingContentProps | LabelContentProps | BodyContentProps;

// ---------------------------------------------------------------------------
// Content — routes to the appropriate internal layout
// ---------------------------------------------------------------------------

function Content(props: ContentProps) {
  const { sizePreset = "headline", variant = "heading", ...rest } = props;

  // Heading layout: headline/section presets with heading/section variant
  if (sizePreset === "headline" || sizePreset === "section") {
    return (
      <HeadingLayout
        sizePreset={sizePreset}
        variant={variant as HeadingLayoutProps["variant"]}
        {...rest}
      />
    );
  }

  // Label layout: main-content/main-ui/secondary with section variant
  if (variant === "section" || variant === "heading") {
    return (
      <LabelLayout
        sizePreset={sizePreset}
        {...(rest as Omit<LabelLayoutProps, "sizePreset">)}
      />
    );
  }

  // Body layout: main-content/main-ui/secondary with body variant
  if (variant === "body") {
    return (
      <BodyLayout
        sizePreset={sizePreset}
        {...(rest as Omit<
          React.ComponentProps<typeof BodyLayout>,
          "sizePreset"
        >)}
      />
    );
  }

  return null;
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export {
  Content,
  type ContentProps,
  type SizePreset,
  type ContentVariant,
  type HeadingContentProps,
  type LabelContentProps,
  type BodyContentProps,
};
