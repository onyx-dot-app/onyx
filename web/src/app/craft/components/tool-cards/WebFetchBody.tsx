"use client";

import { Text } from "@opal/components";
import ToolCardSurface, {
  ToolCardSection,
} from "@/app/craft/components/tool-cards/ToolCardSurface";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

/**
 * WebFetchBody - Response body for webfetch. The URL is rendered by the
 * card header (toolCall.description), so we only show the body here.
 */
export default function WebFetchBody({ toolCall }: ToolCardBodyProps) {
  const body = toolCall.rawOutput;

  return (
    <ToolCardSurface>
      <ToolCardSection className="whitespace-pre-wrap wrap-break-word">
        <Text as="p" font="secondary-mono" color="text-03">
          {body || "No response body"}
        </Text>
      </ToolCardSection>
    </ToolCardSurface>
  );
}
