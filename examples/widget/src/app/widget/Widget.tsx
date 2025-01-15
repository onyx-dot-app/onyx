"use client";

import React, { useState } from "react";
import ReactMarkdown from "react-markdown";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "";

type NonEmptyObject = { [k: string]: any };

const processSingleChunk = <T extends NonEmptyObject>(
  chunk: string,
  currPartialChunk: string | null,
): [T | null, string | null] => {
  const completeChunk = (currPartialChunk || "") + chunk;
  try {
    // every complete chunk should be valid JSON
    const chunkJson = JSON.parse(completeChunk);
    return [chunkJson, null];
  } catch (err) {
    // if it's not valid JSON, then it's probably an incomplete chunk
    return [null, completeChunk];
  }
};

const processRawChunkString = <T extends NonEmptyObject>(
  rawChunkString: string,
  previousPartialChunk: string | null,
): [T[], string | null] => {
  /* This is required because, in practice, we see that nginx does not send over
  each chunk one at a time even with buffering turned off. Instead,
  chunks are sometimes in batches or are sometimes incomplete */
  if (!rawChunkString) {
    return [[], null];
  }
  const chunkSections = rawChunkString
    .split("\n")
    .filter((chunk) => chunk.length > 0);
  let parsedChunkSections: T[] = [];
  let currPartialChunk = previousPartialChunk;
  chunkSections.forEach((chunk) => {
    const [processedChunk, partialChunk] = processSingleChunk<T>(
      chunk,
      currPartialChunk,
    );
    if (processedChunk) {
      parsedChunkSections.push(processedChunk);
      currPartialChunk = null;
    } else {
      currPartialChunk = partialChunk;
    }
  });

  return [parsedChunkSections, currPartialChunk];
};

async function* handleStream<T extends NonEmptyObject>(
  streamingResponse: Response,
): AsyncGenerator<T[], void, unknown> {
  const reader = streamingResponse.body?.getReader();
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

    const [completedChunks, partialChunk] = processRawChunkString<T>(
      decoder.decode(value, { stream: true }),
      previousPartialChunk,
    );
    if (!completedChunks.length && !partialChunk) {
      break;
    }
    previousPartialChunk = partialChunk as string | null;

    yield await Promise.resolve(completedChunks);
  }
}

async function* sendMessage({
  message,
  chatSessionId,
  parentMessageId,
}: {
  message: string;
  chatSessionId?: number;
  parentMessageId?: number;
}) {
  if (!chatSessionId || !parentMessageId) {
    // Create a new chat session if one doesn't exist
    const createSessionResponse = await fetch(
      `${API_URL}/chat/create-chat-session`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${API_KEY}`,
        },
        body: JSON.stringify({
          // or specify an assistant you have defined
          persona_id: 0,
        }),
      },
    );

    if (!createSessionResponse.ok) {
      const errorJson = await createSessionResponse.json();
      const errorMsg = errorJson.message || errorJson.detail || "";
      throw Error(`Failed to create chat session - ${errorMsg}`);
    }

    const sessionData = await createSessionResponse.json();
    chatSessionId = sessionData.chat_session_id;
  }

  const sendMessageResponse = await fetch(`${API_URL}/chat/send-message`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${API_KEY}`,
    },
    body: JSON.stringify({
      chat_session_id: chatSessionId,
      parent_message_id: parentMessageId || null,
      message: message,
      prompt_id: null,
      search_doc_ids: null,
      file_descriptors: [],
      // checkout https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/search/models.py#L105 for
      // all available options
      retrieval_options: {
        run_search: "always",
        filters: null,
      },
      query_override: null,
    }),
  });
  if (!sendMessageResponse.ok) {
    const errorJson = await sendMessageResponse.json();
    const errorMsg = errorJson.message || errorJson.detail || "";
    throw Error(`Failed to send message - ${errorMsg}`);
  }

  yield* handleStream<NonEmptyObject>(sendMessageResponse);
}

export const ChatWidget = () => {
  const [messages, setMessages] = useState<{ text: string; isUser: boolean }[]>(
    [],
  );
  const [inputText, setInputText] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (inputText.trim()) {
      const initialPrevMessages = messages;
      setMessages([...initialPrevMessages, { text: inputText, isUser: true }]);
      setInputText("");
      setIsLoading(true);

      try {
        const messageGenerator = sendMessage({
          message: inputText,
          chatSessionId: undefined,
          parentMessageId: undefined,
        });
        let fullResponse = "";

        for await (const chunks of messageGenerator) {
          for (const chunk of chunks) {
            if ("answer_piece" in chunk) {
              fullResponse += chunk.answer_piece;
              setMessages([
                ...initialPrevMessages,
                { text: inputText, isUser: true },
                { text: fullResponse, isUser: false },
              ]);
            }
          }
        }
      } catch (error) {
        console.error("Error sending message:", error);
        setMessages((prevMessages) => [
          ...prevMessages,
          { text: "An error occurred. Please try again.", isUser: false },
        ]);
      } finally {
        setIsLoading(false);
      }
    }
  };

  return (
    <div
      className="
      fixed
      bottom-4
      right-4
      z-50
      bg-white
      rounded-lg
      shadow-xl
      w-96
      h-[32rem]
      flex
      flex-col
      overflow-hidden
      transition-all
      duration-300
      ease-in-out
    "
    >
      <div
        className="
        bg-gradient-to-r
        from-blue-600
        to-blue-800
        text-white
        p-4
        font-bold
        flex
        justify-between
        items-center
      "
      >
        <span>Chat Support</span>
      </div>
      <div
        className="
        flex-grow
        overflow-y-auto
        p-4
        space-y-4
        bg-gray-50
        border-b
        border-gray-200
      "
      >
        {messages.map((message, index) => (
          <div
            key={index}
            className={`
            flex
            ${message.isUser ? "justify-end" : "justify-start"}
          `}
          >
            <div
              className={`
              max-w-[75%]
              p-3
              rounded-lg
              ${
                message.isUser
                  ? "bg-blue-500 text-white"
                  : "bg-white text-black"
              }
              shadow
            `}
            >
              <ReactMarkdown>{message.text}</ReactMarkdown>
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex justify-center">
            <div className="animate-pulse flex space-x-2">
              <div className="w-2 h-2 bg-gray-500 rounded-full"></div>
              <div className="w-2 h-2 bg-gray-500 rounded-full"></div>
              <div className="w-2 h-2 bg-gray-500 rounded-full"></div>
            </div>
          </div>
        )}
      </div>
      <form
        onSubmit={handleSubmit}
        className="
        p-4
        bg-white
        border-t
        border-gray-200
      "
      >
        <div className="relative">
          <input
            type="text"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            placeholder="Type a message..."
            className="
              w-full
              p-2
              pr-10
              border
              border-gray-300
              rounded-full
              focus:outline-none
              focus:ring-2
              focus:ring-blue-500
              focus:border-transparent
            "
            disabled={isLoading}
          />
          <button
            type="submit"
            disabled={isLoading}
            className="
              absolute
              right-2
              top-1/2
              transform
              -translate-y-1/2
              text-blue-500
              hover:text-blue-600
              focus:outline-none
            "
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-6 w-6"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
              />
            </svg>
          </button>
        </div>
      </form>
    </div>
  );
};
