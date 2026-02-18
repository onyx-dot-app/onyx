import "@opal/components/layouts/LineItemLayout/styles.css";

import {
  ContentContainerHeading,
  type ContentContainerHeadingProps,
} from "@opal/components/layouts/LineItemLayout/Heading";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type LineItemLayoutVariant = "headline";

type LineItemLayoutProps = ContentContainerHeadingProps & {
  /** Content variant. Determines which internal layout is used. */
  variant?: LineItemLayoutVariant;
};

// ---------------------------------------------------------------------------
// LineItemLayout — routes to the appropriate ContentContainer sub-component
// ---------------------------------------------------------------------------

function LineItemLayout({
  variant = "headline",
  ...rest
}: LineItemLayoutProps) {
  switch (variant) {
    case "headline":
      return <ContentContainerHeading {...rest} />;
  }
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { LineItemLayout, type LineItemLayoutProps, type LineItemLayoutVariant };
