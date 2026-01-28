import type { Components } from "react-markdown";
import Text from "@/refresh-components/texts/Text";

export const mutedTextMarkdownComponents = {
  p: ({ children }: { children?: React.ReactNode }) => (
    <Text as="p" text03 mainUiMuted className="!my-1">
      {children}
    </Text>
  ),
  li: ({ children }: { children?: React.ReactNode }) => (
    <Text as="li" text03 mainUiMuted className="!my-0 !py-0 leading-normal">
      {children}
    </Text>
  ),
} satisfies Partial<Components>;
