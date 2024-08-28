import {
  BackendMessage,
  LLMRelevanceFilterPacket,
} from "@/app/chat/interfaces";
import {
  AnswerPiecePacket,
  DanswerDocument,
  DocumentInfoPacket,
  ErrorMessagePacket,
  Quote,
  QuotesInfoPacket,
  RelevanceChunk,
  SearchRequestArgs,
} from "./interfaces";
import { processRawChunkString } from "./streamingUtils";
import { buildFilters, endsWithLetterOrNumber } from "./utils";

export const searchRequestStreamed = async ({
  query,
  sources,
  documentSets,
  timeRange,
  tags,
  persona,
  agentic,
  updateCurrentAnswer,
  updateQuotes,
  updateDocs,
  updateSuggestedSearchType,
  updateSuggestedFlowType,
  updateSelectedDocIndices,
  updateError,
  updateMessageAndThreadId,
  finishedSearching,
  updateDocumentRelevance,
  updateComments,
}: SearchRequestArgs) => {
  let answer = "";
  let quotes: Quote[] | null = null;
  let relevantDocuments: DanswerDocument[] | null = null;

  try {
    const filters = buildFilters(sources, documentSets, timeRange, tags);

    const threadMessage = {
      message: query,
      sender: null,
      role: "user",
    };

    const response = await fetch("/api/query/stream-answer-with-quote", {
      method: "POST",
      body: JSON.stringify({
        messages: [threadMessage],
        persona_id: persona.id,
        agentic,
        prompt_id: persona.id === 0 ? null : persona.prompts[0]?.id,
        retrieval_options: {
          run_search: "always",
          real_time: true,
          filters: filters,
          enable_auto_detect_filters: false,
        },
        evaluation_type: agentic ? "agentic" : "basic",
      }),
      headers: {
        "Content-Type": "application/json",
      },
    });

    const reader = response.body?.getReader();
    const decoder = new TextDecoder("utf-8");

    let previousPartialChunk: string | null = null;
    while (true) {
      const rawChunk = await reader?.read();

      if (!rawChunk) {
        throw new Error("Unable to process chunk");
      }
      const { done, value } = rawChunk;
      if (done) {
        break;
      }

      // Process each chunk as it arrives
      const [completedChunks, partialChunk] = processRawChunkString<
        | AnswerPiecePacket
        | ErrorMessagePacket
        | QuotesInfoPacket
        | DocumentInfoPacket
        | LLMRelevanceFilterPacket
        | BackendMessage
        | RelevanceChunk
      >(decoder.decode(value, { stream: true }), previousPartialChunk);
      if (!completedChunks.length && !partialChunk) {
        break;
      }
      previousPartialChunk = partialChunk as string | null;
      completedChunks.forEach((chunk) => {
        // check for answer peice / end of answer

        if (Object.hasOwn(chunk, "relevance_summaries")) {
          const relevanceChunk = chunk as RelevanceChunk;
          updateDocumentRelevance(relevanceChunk.relevance_summaries);
        }

        if (Object.hasOwn(chunk, "answer_piece")) {
          const answerPiece = (chunk as AnswerPiecePacket).answer_piece;
          if (answerPiece !== null) {
            answer += (chunk as AnswerPiecePacket).answer_piece;
            updateCurrentAnswer(answer);
          } else {
            // set quotes as non-null to signify that the answer is finished and
            // we're now looking for quotes
            updateQuotes([]);
            if (
              answer &&
              !answer.endsWith(".") &&
              !answer.endsWith("?") &&
              !answer.endsWith("!") &&
              endsWithLetterOrNumber(answer)
            ) {
              answer += ".";
              updateCurrentAnswer(answer);
            }
          }
          return;
        }

        if (Object.hasOwn(chunk, "error")) {
          updateError((chunk as ErrorMessagePacket).error);
          return;
        }

        // These all come together
        if (Object.hasOwn(chunk, "top_documents")) {
          chunk = chunk as DocumentInfoPacket;
          const topDocuments = chunk.top_documents as DanswerDocument[] | null;
          if (topDocuments) {
            relevantDocuments = topDocuments;
            updateDocs(relevantDocuments);
          }

          if (chunk.predicted_flow) {
            updateSuggestedFlowType(chunk.predicted_flow);
          }

          if (chunk.predicted_search) {
            updateSuggestedSearchType(chunk.predicted_search);
          }

          return;
        }

        if (Object.hasOwn(chunk, "relevant_chunk_indices")) {
          const relevantChunkIndices = (chunk as LLMRelevanceFilterPacket)
            .relevant_chunk_indices;
          if (relevantChunkIndices) {
            updateSelectedDocIndices(relevantChunkIndices);
          }
          return;
        }

        // Check for quote section
        if (Object.hasOwn(chunk, "quotes")) {
          quotes = (chunk as QuotesInfoPacket).quotes;
          updateQuotes(quotes);
          return;
        }

        // Check for the final chunk
        if (Object.hasOwn(chunk, "message_id")) {
          const backendChunk = chunk as BackendMessage;
          updateComments(backendChunk.comments);
          updateMessageAndThreadId(
            backendChunk.message_id,
            backendChunk.chat_session_id
          );
        }
      });
    }
  } catch (err) {
    console.error("Fetch error:", err);
    let errorMessage = "An error occurred while fetching the answer.";

    if (err instanceof Error) {
      if (err.message.includes("rate_limit_error")) {
        errorMessage =
          "Rate limit exceeded. Please try again later or reduce the length of your query.";
      } else {
        errorMessage = err.message;
      }
    }

    updateError(errorMessage);
  }

  return { answer, quotes, relevantDocuments };
};
