import type { Components } from "react-markdown";
import Text from "@/refresh-components/texts/Text";

// Expanded view: normal spacing between paragraphs/lists
export const mutedTextMarkdownComponents = {
  p: ({ children, dir }: { children?: React.ReactNode; dir?: string }) => (
    <Text as="p" dir={dir} text03 mainUiMuted className="my-1!">
      {children}
    </Text>
  ),
  li: ({ children, dir }: { children?: React.ReactNode; dir?: string }) => (
    <Text
      as="li"
      dir={dir}
      text03
      mainUiMuted
      className="my-0! py-0! leading-normal"
    >
      {children}
    </Text>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="pl-0! ml-0! my-0.5! list-inside">{children}</ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="pl-0! ml-0! my-0.5! list-inside">{children}</ol>
  ),
  a: ({ children, href }: { children?: React.ReactNode; href?: string }) => (
    <a
      href={href}
      className="text-text-03 mainUiMuted underline"
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
    </a>
  ),
} satisfies Partial<Components>;

// Collapsed view: no spacing for compact display
export const collapsedMarkdownComponents = {
  p: ({ children, dir }: { children?: React.ReactNode; dir?: string }) => (
    <Text as="p" dir={dir} text03 mainUiMuted className="my-0!">
      {children}
    </Text>
  ),
  li: ({ children, dir }: { children?: React.ReactNode; dir?: string }) => (
    <Text
      as="li"
      dir={dir}
      text03
      mainUiMuted
      className="my-0! py-0! leading-normal"
    >
      {children}
    </Text>
  ),
  ul: ({ children, dir }: { children?: React.ReactNode; dir?: string }) => (
    <ul dir={dir} className="pl-0! ml-0! my-0! list-inside">
      {children}
    </ul>
  ),
  ol: ({ children, dir }: { children?: React.ReactNode; dir?: string }) => (
    <ol dir={dir} className="pl-0! ml-0! my-0! list-inside">
      {children}
    </ol>
  ),
  a: ({ children, href }: { children?: React.ReactNode; href?: string }) => (
    <a
      href={href}
      className="text-text-03 mainUiMuted underline"
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
    </a>
  ),
} satisfies Partial<Components>;
