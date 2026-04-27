"use client";

import "@opal/layouts/content/styles.css";
import {
  ContentSm,
  type ContentSmOrientation,
} from "@opal/layouts/content/ContentSm";
import {
  ContentXl,
  type ContentXlProps,
} from "@opal/layouts/content/ContentXl";
import {
  ContentLg,
  type ContentLgProps,
} from "@opal/layouts/content/ContentLg";
import {
  ContentMd,
  type ContentMdProps,
} from "@opal/layouts/content/ContentMd";
import type { TagProps } from "@opal/components";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { widthVariants } from "@opal/shared";
import type { ExtremaSizeVariants } from "@opal/types";

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
type ContentColor = "default" | "muted" | "danger" | "interactive";

interface ContentBaseProps {
  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /** Main title text. */
  title: string | RichStr;

  /** Optional description below the title. */
  description?: string | RichStr;

  /** Enable inline editing of the title. */
  editable?: boolean;

  /** Called when the user commits an edit. */
  onTitleChange?: (newTitle: string) => void;

  /**
   * Width preset controlling the component's horizontal size.
   *
   * - `"auto"` — Shrink-wraps to content width
   * - `"fit"` — Shrink-wraps to content width
   * - `"full"` — Stretches to fill the parent's width
   *
   * @default "full"
   */
  width?: ExtremaSizeVariants;

  /**
   * Color mode for the icon + title pair.
   *
   * - `"default"` — `text-04` for both icon and title
   * - `"muted"` — `text-03` for both
   * - `"danger"` — `status-error-05` for both
   * - `"interactive"` — inherits from the parent `.interactive` element's
   *   `--interactive-foreground` / `--interactive-foreground-icon` variables
   *
   * @default "default"
   */
  color?: ContentColor;

  /** Ref forwarded to the root `<div>` of the resolved layout. */
  ref?: React.Ref<HTMLDivElement>;
}

// ---------------------------------------------------------------------------
// Discriminated union: valid sizePreset × variant combinations
// ---------------------------------------------------------------------------

type XlContentProps = ContentBaseProps & {
  /** Size preset. Default: `"headline"`. */
  sizePreset?: "headline" | "section";
  /** Variant. Default: `"heading"` for heading-eligible presets. */
  variant?: "heading";
  /** Optional secondary icon rendered in the icon row (ContentXl only). */
  moreIcon1?: IconFunctionComponent;
  /** Optional tertiary icon rendered in the icon row (ContentXl only). */
  moreIcon2?: IconFunctionComponent;
};

type LgContentProps = ContentBaseProps & {
  /** Size preset. Default: `"headline"`. */
  sizePreset?: "headline" | "section";
  /** Variant. */
  variant: "section";
};

type MdContentProps = ContentBaseProps & {
  sizePreset: "main-content" | "main-ui" | "secondary";
  variant?: "section";
  /** Muted suffix rendered beside the title. Use `"optional"` for "(Optional)". */
  suffix?: "optional" | (string & {});
  /** Auxiliary status icon rendered beside the title. */
  auxIcon?: "info-gray" | "info-blue" | "warning" | "error";
  /** Tag rendered beside the title. */
  tag?: TagProps;
};

/** ContentSm does not support descriptions or inline editing. */
type SmContentProps = Omit<
  ContentBaseProps,
  "description" | "editable" | "onTitleChange"
> & {
  sizePreset: "main-content" | "main-ui" | "secondary";
  variant: "body";
  /** Layout orientation. Default: `"inline"`. */
  orientation?: ContentSmOrientation;
};

type ContentProps =
  | XlContentProps
  | LgContentProps
  | MdContentProps
  | SmContentProps;

// ---------------------------------------------------------------------------
// Content — routes to the appropriate internal layout
// ---------------------------------------------------------------------------

function Content(props: ContentProps) {
  const {
    sizePreset = "headline",
    variant = "heading",
    width = "full",
    color = "default",
    ref,
    ...rest
  } = props;

  let layout: React.ReactNode = null;

  // ContentXl / ContentLg: headline/section presets
  if (sizePreset === "headline" || sizePreset === "section") {
    if (variant === "heading") {
      layout = (
        <ContentXl
          sizePreset={sizePreset}
          ref={ref}
          {...(rest as Omit<ContentXlProps, "sizePreset">)}
        />
      );
    } else {
      layout = (
        <ContentLg
          sizePreset={sizePreset}
          ref={ref}
          {...(rest as Omit<ContentLgProps, "sizePreset">)}
        />
      );
    }
  }

  // ContentMd: main-content/main-ui/secondary with section/heading variant
  // (variant defaults to "heading" when omitted on MdContentProps, so both arms are needed)
  else if (variant === "section" || variant === "heading") {
    layout = (
      <ContentMd
        sizePreset={sizePreset}
        ref={ref}
        {...(rest as Omit<ContentMdProps, "sizePreset">)}
      />
    );
  }

  // ContentSm: main-content/main-ui/secondary with body variant
  else if (variant === "body") {
    layout = (
      <ContentSm
        sizePreset={sizePreset}
        ref={ref}
        {...(rest as Omit<
          React.ComponentProps<typeof ContentSm>,
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

  return (
    <div className={widthVariants[width]} data-content-color={color}>
      {layout}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export {
  Content,
  type ContentProps,
  type ContentColor,
  type SizePreset,
  type ContentVariant,
  type XlContentProps,
  type LgContentProps,
  type MdContentProps,
  type SmContentProps,
};
