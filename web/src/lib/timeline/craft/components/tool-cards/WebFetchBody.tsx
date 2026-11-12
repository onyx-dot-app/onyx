"use client";

import { Text } from "@opal/components";
import { ValidSources } from "@/lib/connectors/types/source";
import { RetrievalBody } from "@/lib/timeline/components/bodies/RetrievalBody";
import ToolCardSurface, {
  ToolCardSection,
} from "@/lib/timeline/craft/components/tool-cards/ToolCardSurface";
import type { ToolCardBodyProps } from "@/lib/timeline/craft/components/tool-cards/interfaces";

/**
 * WebFetchBody - The fetched URL in the shared retrieval layout, then the
 * response body. The URL is in `toolCall.description`.
 */
export default function WebFetchBody({ toolCall }: ToolCardBodyProps) {
  const url = toolCall.description;
  const isComplete =
    toolCall.status !== "pending" && toolCall.status !== "in_progress";

  return (
    <>
      <RetrievalBody
        queries={[]}
        results={
          url
            ? [
                {
                  id: url,
                  title: url,
                  sourceType: ValidSources.Web,
                  sourceUrl: url,
                },
              ]
            : []
        }
        isComplete={isComplete}
      />
      {toolCall.rawOutput && (
        <ToolCardSurface>
          <ToolCardSection className="whitespace-pre-wrap wrap-break-word">
            <Text as="p" font="secondary-mono" color="text-03">
              {toolCall.rawOutput}
            </Text>
          </ToolCardSection>
        </ToolCardSurface>
      )}
    </>
  );
}
