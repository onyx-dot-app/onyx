import { handleSSEStream } from "@/lib/search/streamingUtils";
import {
  OnyxDocument,
  SourceMetadata,
  AnswerPiecePacket,
  DocumentInfoPacket,
} from "@/lib/search/interfaces";
import { Persona } from "@/app/admin/assistants/interfaces";
import { buildFilters } from "@/lib/search/utils";
import { Tag } from "@/lib/types";
import { DateRangePickerValue } from "@/app/ee/admin/performance/DateRangeSelector";
import { StreamingError } from "@/app/chat/interfaces";

export interface SearchStreamResponse {
  answer: string | null;
  documents: OnyxDocument[];
  error: string | null;
}

export async function* streamSearchWithCitation({
  query,
  persona,
  sources,
  documentSets,
  timeRange,
  tags,
}: {
  query: string;
  persona: Persona;
  sources: SourceMetadata[];
  documentSets: string[];
  timeRange: DateRangePickerValue | null;
  tags: Tag[];
}): AsyncGenerator<SearchStreamResponse> {
  const filters = buildFilters(sources, documentSets, timeRange, tags);

  const response = await fetch("/api/query/search", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      persona_id: persona.id,
      messages: [
        {
          role: "user",
          message: query,
        },
      ],
      retrieval_options: {
        filters: filters,
        favor_recent: true,
      },
      skip_gen_ai_answer_generation: false,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    yield {
      answer: null,
      documents: [],
      error: `Error: ${response.status} - ${errorText}`,
    };
    return;
  }

  let currentAnswer = "";
  let documents: OnyxDocument[] = [];
  let error: string | null = null;

  for await (const packet of handleSSEStream(response)) {
    if ("error" in packet && packet.error) {
      error = (packet as StreamingError).error;
      yield {
        answer: currentAnswer,
        documents,
        error,
      };
      continue;
    }

    if ("answer_piece" in packet && packet.answer_piece) {
      currentAnswer += (packet as AnswerPiecePacket).answer_piece;
      yield {
        answer: currentAnswer,
        documents,
        error,
      };
    }

    if ("top_documents" in packet && packet.top_documents) {
      documents = (packet as DocumentInfoPacket).top_documents;
      yield {
        answer: currentAnswer,
        documents,
        error,
      };
    }
  }

  yield {
    answer: currentAnswer,
    documents,
    error,
  };
}
