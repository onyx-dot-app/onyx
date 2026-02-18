import "@opal/components/layouts/Content/styles.css";

import {
  HeadingLayout,
  type HeadingLayoutProps,
} from "@opal/components/layouts/Content/HeadingLayout";
import {
  LabelLayout,
  type LabelLayoutProps,
} from "@opal/components/layouts/Content/LabelLayout";
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
};

type BodyContentProps = ContentBaseProps & {
  sizePreset: "main-content" | "main-ui" | "secondary";
  variant: "body";
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

  // Body layout: main-content/main-ui/secondary with body variant (future)
  if (variant === "body") {
    // TODO (@raunakab): BodyLayout
    return null;
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
