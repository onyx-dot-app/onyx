import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import messages from "@/i18n/messages/en.json";
import { InternalSearchToolRenderer } from "@/app/app/message/messageComponents/timeline/renderers/search/InternalSearchToolRenderer";
import { RenderType } from "@/app/app/message/messageComponents/interfaces";
import { ResponseItems } from "@/app/app/services/responseItems";
import {
  PacketIdentity,
  ResponseItem,
  SearchResult,
  ToolItem,
} from "@/app/app/services/streamingModels";
import { usePacedTurnGroups } from "@/app/app/message/messageComponents/timeline/hooks/usePacedTurnGroups";
import { ValidSources } from "@/lib/types";

const identity: PacketIdentity = {
  response_id: 1,
  run_id: "run",
  message_id: "search",
  tool_call_id: "call",
  part_id: "tool",
};
const tool: ToolItem = {
  kind: "tool",
  name: "internal_search",
  arguments: { queries: ["authorization design"] },
  status: "running",
  output: "",
  metadata: null,
};
const result: SearchResult = {
  type: "search_result",
  queries: [],
  sources: [],
  time_filter_start: null,
  time_filter_end: null,
  displayed_docs: null,
  citation_mapping: { 1: "architecture" },
  search_docs: [
    {
      document_id: "architecture",
      semantic_identifier: "Architecture guide",
      link: "https://example.com/architecture",
      source_type: ValidSources.Confluence,
      blurb: "Access control design",
      boost: 0,
      hidden: false,
      score: 1,
      chunk_ind: 0,
      match_highlights: [],
      metadata: {},
      updated_at: null,
      is_internet: false,
    },
  ],
};

function PacedSearch({
  items,
  renderType,
}: {
  items: ResponseItem[];
  renderType: RenderType;
}) {
  const { pacedTurnGroups } = usePacedTurnGroups(
    [
      {
        turnIndex: 0,
        isParallel: false,
        steps: [{ key: "0-0", turnIndex: 0, tabIndex: 0, items }],
      },
    ],
    [],
    false,
    1,
    false
  );
  const step = pacedTurnGroups[0]?.steps[0];
  if (!step) return null;
  return (
    <InternalSearchToolRenderer
      items={step.items}
      state={{}}
      renderType={renderType}
      onComplete={() => {}}
      animate={false}
      stopPacketSeen={false}
    >
      {(sections) => (
        <>
          {sections.map((section, index) => (
            <div key={index}>{section.content}</div>
          ))}
        </>
      )}
    </InternalSearchToolRenderer>
  );
}

it("shows known queries immediately, streamed sources, and saved sources without query metadata", () => {
  const response = new ResponseItems();
  response.apply({ identity, obj: { type: "item_update", item: tool } });
  function view(renderType: RenderType) {
    return (
      <NextIntlClientProvider locale="en" messages={messages}>
        <PacedSearch
          items={[...response.items.values()]}
          renderType={renderType}
        />
      </NextIntlClientProvider>
    );
  }
  const { rerender } = render(view(RenderType.INLINE));
  expect(screen.getByText("authorization design")).toBeInTheDocument();
  rerender(view(RenderType.HIGHLIGHT));
  expect(screen.getByText("authorization design")).toBeInTheDocument();

  response.apply({
    identity,
    obj: {
      type: "item_delta",
      delta: { kind: "tool_output", metadata: result },
    },
  });
  rerender(view(RenderType.INLINE));
  expect(screen.getByText("Architecture guide")).toBeInTheDocument();

  response.apply({
    identity,
    obj: {
      type: "item_update",
      item: { ...tool, arguments: {}, status: "complete", metadata: result },
    },
  });
  rerender(view(RenderType.FULL));
  expect(screen.getByText("Architecture guide")).toBeInTheDocument();
});
