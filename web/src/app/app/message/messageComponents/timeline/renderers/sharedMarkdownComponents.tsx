import type { Components } from "react-markdown";
import { Text } from "@opal/components";
import { richNodes } from "@opal/utils";

// Expanded view: normal spacing between paragraphs/lists
export const mutedTextMarkdownComponents = {
  p: ({ children, dir }: { children?: React.ReactNode; dir?: string }) => (
    // Text takes no className; the wrapper keeps this margin over prose's.
    <div className="[&>p]:my-1!">
      <Text as="p" dir={dir} font="main-ui-muted" color="text-03">
        {richNodes(children)}
      </Text>
    </div>
  ),
  li: ({ children, dir }: { children?: React.ReactNode; dir?: string }) => (
    <Text as="li" dir={dir} font="main-ui-muted" color="text-03">
      {richNodes(children)}
    </Text>
  ),
  ul: ({ children, dir }: { children?: React.ReactNode; dir?: string }) => (
    <ul
      dir={dir}
      className="ps-0! ms-0! my-0.5! list-inside [&>li]:my-0! [&>li]:py-0! [&>li]:leading-normal"
    >
      {children}
    </ul>
  ),
  ol: ({ children, dir }: { children?: React.ReactNode; dir?: string }) => (
    <ol
      dir={dir}
      className="ps-0! ms-0! my-0.5! list-inside [&>li]:my-0! [&>li]:py-0! [&>li]:leading-normal"
    >
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

// Collapsed view: no spacing for compact display
export const collapsedMarkdownComponents = {
  p: ({ children, dir }: { children?: React.ReactNode; dir?: string }) => (
    // Text takes no className; the wrapper keeps this margin over prose's.
    <div className="[&>p]:my-0!">
      <Text as="p" dir={dir} font="main-ui-muted" color="text-03">
        {richNodes(children)}
      </Text>
    </div>
  ),
  li: ({ children, dir }: { children?: React.ReactNode; dir?: string }) => (
    <Text as="li" dir={dir} font="main-ui-muted" color="text-03">
      {richNodes(children)}
    </Text>
  ),
  ul: ({ children, dir }: { children?: React.ReactNode; dir?: string }) => (
    <ul
      dir={dir}
      className="ps-0! ms-0! my-0! list-inside [&>li]:my-0! [&>li]:py-0! [&>li]:leading-normal"
    >
      {children}
    </ul>
  ),
  ol: ({ children, dir }: { children?: React.ReactNode; dir?: string }) => (
    <ol
      dir={dir}
      className="ps-0! ms-0! my-0! list-inside [&>li]:my-0! [&>li]:py-0! [&>li]:leading-normal"
    >
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
