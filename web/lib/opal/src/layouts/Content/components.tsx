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
import { widthVariants, type WidthVariant } from "@opal/shared";
import { cn } from "@opal/utils";

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

  /**
   * Width preset controlling the component's horizontal size.
   * Uses the shared `WidthVariant` scale from `@opal/shared`.
   *
   * - `"auto"` — Shrink-wraps to content width
   * - `"full"` — Stretches to fill the parent's width
   *
   * @default "auto"
   */
  widthVariant?: WidthVariant;
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
  const {
    sizePreset = "headline",
    variant = "heading",
    widthVariant = "auto",
    ...rest
  } = props;

  const widthClass = widthVariants[widthVariant];

  let layout: React.ReactNode = null;

  // Heading layout: headline/section presets with heading/section variant
  if (sizePreset === "headline" || sizePreset === "section") {
    layout = (
      <HeadingLayout
        sizePreset={sizePreset}
        variant={variant as HeadingLayoutProps["variant"]}
        {...rest}
      />
    );
  }

  // Label layout: main-content/main-ui/secondary with section variant
  else if (variant === "section" || variant === "heading") {
    layout = (
      <LabelLayout
        sizePreset={sizePreset}
        {...(rest as Omit<LabelLayoutProps, "sizePreset">)}
      />
    );
  }

  // Body layout: main-content/main-ui/secondary with body variant
  else if (variant === "body") {
    layout = (
      <BodyLayout
        sizePreset={sizePreset}
        {...(rest as Omit<
          React.ComponentProps<typeof BodyLayout>,
          "sizePreset"
        >)}
      />
    );
  }

  // This case should NEVER be hit.
  if (!layout)
    throw new Error(
      `Content: no layout matched for sizePreset="${sizePreset}" variant="${variant}"`
    );

  // "auto" → return layout directly (a block div with w-auto still
  // stretches to its parent, defeating shrink-to-content).
  if (widthVariant === "auto") return layout;

  return <div className={widthClass}>{layout}</div>;
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
