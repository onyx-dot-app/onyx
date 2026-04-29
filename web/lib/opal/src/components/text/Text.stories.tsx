import type { Meta, StoryObj } from "@storybook/react";
import { Text } from "@opal/components";
import type { TextFont, TextColor } from "@opal/components";
import { markdown } from "@opal/utils";

const meta: Meta<typeof Text> = {
  title: "opal/components/Text",
  component: Text,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Text>;

// ---------------------------------------------------------------------------
// Basic
// ---------------------------------------------------------------------------

export const Default: Story = {
  args: {
    children: "The quick brown fox jumps over the lazy dog",
  },
};

export const AsHeading: Story = {
  args: {
    font: "heading-h2",
    color: "text-05",
    as: "h2",
    children: "Page Title",
  },
};

export const AsParagraph: Story = {
  args: {
    font: "main-content-body",
    color: "text-03",
    as: "p",
    children: "A full paragraph of body text rendered as a p element.",
  },
};

export const Nowrap: Story = {
  render: () => (
    <div className="w-48 border border-border-02 rounded p-2">
      <Text font="main-ui-body" color="text-05" nowrap>
        This text will not wrap even though the container is narrow
      </Text>
    </div>
  ),
};

// ---------------------------------------------------------------------------
// Fonts
// ---------------------------------------------------------------------------

const ALL_FONTS: TextFont[] = [
  "heading-h1",
  "heading-h2",
  "heading-h3",
  "heading-h3-muted",
  "main-content-body",
  "main-content-muted",
  "main-content-emphasis",
  "main-content-mono",
  "main-ui-body",
  "main-ui-muted",
  "main-ui-action",
  "main-ui-mono",
  "secondary-body",
  "secondary-action",
  "secondary-mono",
  "figure-small-label",
  "figure-small-value",
  "figure-keystroke",
];

export const AllFonts: Story = {
  render: () => (
    <div className="space-y-2">
      {ALL_FONTS.map((font) => (
        <div key={font} className="flex items-baseline gap-4">
          <span className="w-56 shrink-0 font-secondary-body text-text-03">
            {font}
          </span>
          <Text font={font} color="text-05">
            The quick brown fox
          </Text>
        </div>
      ))}
    </div>
  ),
};

// ---------------------------------------------------------------------------
// Colors
// ---------------------------------------------------------------------------

const STANDARD_COLORS: TextColor[] = [
  "text-01",
  "text-02",
  "text-03",
  "text-04",
  "text-05",
];

const INVERTED_COLORS: TextColor[] = [
  "text-inverted-01",
  "text-inverted-02",
  "text-inverted-03",
  "text-inverted-04",
  "text-inverted-05",
];

export const AllColors: Story = {
  render: () => (
    <div className="space-y-2">
      {STANDARD_COLORS.map((color) => (
        <div key={color} className="flex items-baseline gap-4">
          <span className="w-56 shrink-0 font-secondary-body text-text-03">
            {color}
          </span>
          <Text font="main-ui-body" color={color}>
            The quick brown fox
          </Text>
        </div>
      ))}
    </div>
  ),
};

export const InvertedColors: Story = {
  render: () => (
    <div className="bg-background-inverted-01 rounded-lg p-6 space-y-2">
      {INVERTED_COLORS.map((color) => (
        <div key={color} className="flex items-baseline gap-4">
          <span
            className="w-56 shrink-0 font-secondary-body"
            style={{ color: "rgba(255,255,255,0.5)" }}
          >
            {color}
          </span>
          <Text font="main-ui-body" color={color}>
            The quick brown fox
          </Text>
        </div>
      ))}
    </div>
  ),
};

// ---------------------------------------------------------------------------
// Markdown via RichStr
// ---------------------------------------------------------------------------

export const MarkdownBold: Story = {
  render: () => (
    <Text font="main-ui-body" color="text-05">
      {markdown("This is **bold** text")}
    </Text>
  ),
};

export const MarkdownItalic: Story = {
  render: () => (
    <Text font="main-ui-body" color="text-05">
      {markdown("This is *italic* text")}
    </Text>
  ),
};

export const MarkdownCode: Story = {
  render: () => (
    <Text font="main-ui-body" color="text-05">
      {markdown("Run `npm install` to get started")}
    </Text>
  ),
};

export const MarkdownLink: Story = {
  render: () => (
    <Text font="main-ui-body" color="text-05">
      {markdown("Visit [Onyx](https://www.onyx.app/) for more info")}
    </Text>
  ),
};

export const MarkdownStrikethrough: Story = {
  render: () => (
    <Text font="main-ui-body" color="text-05">
      {markdown("This is ~~deleted~~ text")}
    </Text>
  ),
};

export const MarkdownCombined: Story = {
  render: () => (
    <Text font="main-ui-body" color="text-05">
      {markdown(
        "*Hello*, **world**! Check out [Onyx](https://www.onyx.app/) and run `onyx start` to begin."
      )}
    </Text>
  ),
};

export const MarkdownAtDifferentSizes: Story = {
  render: () => (
    <div className="space-y-3">
      <Text font="heading-h2" color="text-05" as="h2">
        {markdown("**Heading** with *emphasis* and `code`")}
      </Text>
      <Text font="main-content-body" color="text-03" as="p">
        {markdown("**Main content** with *emphasis* and `code`")}
      </Text>
      <Text font="secondary-body" color="text-03">
        {markdown("**Secondary** with *emphasis* and `code`")}
      </Text>
    </div>
  ),
};

export const PlainStringNotParsed: Story = {
  render: () => (
    <div className="space-y-2">
      <Text font="main-ui-body" color="text-05">
        {
          "This has *asterisks* and **double asterisks** but they are NOT parsed."
        }
      </Text>
    </div>
  ),
};

// ---------------------------------------------------------------------------
// Tag Variants
// ---------------------------------------------------------------------------

export const TagVariants: Story = {
  render: () => (
    <div className="space-y-2">
      <Text font="main-ui-body" color="text-05">
        Default (span): inline text
      </Text>
      <Text font="main-ui-body" color="text-05" as="p">
        Paragraph (p): block text
      </Text>
      <Text font="heading-h2" color="text-05" as="h2">
        Heading (h2): semantic heading
      </Text>
      <ul className="list-disc pl-6">
        <Text font="main-ui-body" color="text-05" as="li">
          List item (li): inside a list
        </Text>
      </ul>
    </div>
  ),
};
