"use client";

import { CodePanel } from "@opal/components";
import { Section } from "@opal/layouts";
import { ValidSources } from "@/lib/connectors/types/source";
import { RetrievalBody } from "@/lib/timeline/components/bodies/RetrievalBody";
import type { ToolCardBodyProps } from "@/lib/timeline/craft/components/tool-cards/interfaces";

/**
 * WebFetchBody - The fetched URL in the shared retrieval layout, then the
 * response body in an Opal `CodePanel` with a copy button. The URL is in
 * `toolCall.description`.
 */
export default function WebFetchBody({ toolCall }: ToolCardBodyProps) {
  const url = toolCall.description;
  const isComplete =
    toolCall.status !== "pending" && toolCall.status !== "in_progress";

  return (
    <Section alignItems="stretch" gap={1} height="auto">
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
        <CodePanel>
          <CodePanel.Header
            title={toolCall.toolName ?? toolCall.title}
            copyText={toolCall.rawOutput}
          />
          <CodePanel.Output>{toolCall.rawOutput}</CodePanel.Output>
        </CodePanel>
      )}
    </Section>
  );
}
