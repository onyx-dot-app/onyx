import { handleSSEStream } from "@/lib/search/streamingUtils";
import { PacketType, SendMessageParams } from "./lib";
import { DeepAction } from "./deepResearchAction";

export async function* mockSendMessage(
  params: SendMessageParams
): AsyncGenerator<PacketType, void, unknown> {
  // const documentsAreSelected =
  //   selectedDocumentIds && selectedDocumentIds.length > 0;
  // const body = JSON.stringify({
  //   alternate_assistant_id: alternateAssistantId,
  //   chat_session_id: chatSessionId,
  //   parent_message_id: parentMessageId,
  //   message: message,
  //   // just use the default prompt for the assistant.
  //   // should remove this in the future, as we don't support multiple prompts for a
  //   // single assistant anyways
  //   prompt_id: null,
  //   search_doc_ids: documentsAreSelected ? selectedDocumentIds : null,
  //   file_descriptors: fileDescriptors,
  //   user_file_ids: userFileIds,
  //   user_folder_ids: userFolderIds,
  //   regenerate,
  //   retrieval_options: !documentsAreSelected
  //     ? {
  //         run_search: queryOverride || forceSearch ? "always" : "auto",
  //         real_time: true,
  //         filters: filters,
  //       }
  //     : null,
  //   query_override: queryOverride,
  //   prompt_override: systemPromptOverride
  //     ? {
  //         system_prompt: systemPromptOverride,
  //       }
  //     : null,
  //   llm_override:
  //     temperature || modelVersion
  //       ? {
  //           temperature,
  //           model_provider: modelProvider,
  //           model_version: modelVersion,
  //         }
  //       : null,
  //   use_existing_user_message: useExistingUserMessage,
  //   use_agentic_search: useLanggraph ?? false,
  // });

  // const response = await fetch(`/api/chat/send-message`, {
  //   method: "POST",
  //   headers: {
  //     "Content-Type": "application/json",
  //   },
  //   body,
  //   signal,
  // });
  //
  // if (!response.ok) {
  //   throw new Error(`HTTP error! status: ${response.status}`);
  // }

  // TODO: Override
  // TODO: add aborthandler
  yield* mockSseStream(params);
}

function getRandomNumber(min: number, max: number) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

const delay = (ms: number) => {
  return new Promise((resolve) => setTimeout(resolve, ms));
};
async function* mockSseStream(
  _params: SendMessageParams
): AsyncGenerator<PacketType, void, unknown> {
  await delay(100);
  // Run server packet simulation here
  const userMessageId = getRandomNumber(1, 1000);
  yield {
    user_message_id: userMessageId,
    reserved_assistant_message_id: userMessageId + 1,
  };
  yield {
    deepResearchAction: "deep_research_action",
    payload: {
      cmd: "ls",
      type: "run_command",
      id: "1",
      result: "",
    } satisfies DeepAction,
  };
  await delay(1000);
  yield {
    deepResearchAction: "deep_research_action",
    payload: {
      cmd: "ls",
      type: "run_command",
      id: "2",
      result: "",
    } satisfies DeepAction,
  };
  await delay(1000);
  yield {
    deepResearchAction: "deep_research_action",
    payload: {
      cmd: "ls",
      type: "run_command",
      id: "3",
      result: "",
    } satisfies DeepAction,
  };
  await delay(1000);
  yield {
    answer_piece: "Hello",
  };
  await delay(1000);
  yield {
    answer_piece: "World",
  };
}
