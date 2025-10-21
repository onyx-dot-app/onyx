"use client";

import { useState, useMemo, useEffect, useRef, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import Text from "@/components/ui/text";
import {
  parsePacketsFromText,
  processNewPackets,
} from "@/app/chat/services/packetUtils";
import { Packet } from "@/app/chat/services/streamingModels";
import { MemoizedAIMessage } from "@/app/chat/message/messageComponents/MemoizedAIMessage";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { ChatModalProvider } from "@/refresh-components/contexts/ChatModalContext";
import { useChatSessionStore } from "@/app/chat/stores/useChatSessionStore";
import { FeedbackType, Message } from "@/app/chat/interfaces";
import { LlmDescriptor } from "@/lib/hooks";

const IS_DEV = process.env.NODE_ENV === "development";
const DEBUG_SESSION_ID = "debug-packets-session";

const EXAMPLE_PACKETS = `{"user_message_id": 318, "reserved_assistant_message_id": 319}
{"ind": 1, "obj": {"type": "internal_search_tool_start", "is_internet_search": true}}
{"ind": 1, "obj": {"type": "internal_search_tool_delta", "queries": ["OpenAI Agent SDK"], "documents": [{"document_id": "doc1", "semantic_identifier": "https://onyx.app", "link": "https://onyx.app", "blurb": "Sample document", "source_type": "web", "boost": 0, "hidden": false, "score": 0.9, "match_highlights": [], "updated_at": "2024-01-01", "primary_owners": [], "secondary_owners": [], "is_internet": true, "db_doc_id": 1}]}}
{"ind": 1, "obj": {"type": "section_end"}}
{"ind": 2, "obj": {"type": "message_start", "id": "msg_123", "content": "", "final_documents": [{"document_id": "doc1", "semantic_identifier": "https://onyx.app", "link": "https://onyx.app", "blurb": "Sample document", "source_type": "web", "boost": 0, "hidden": false, "score": 0.9, "match_highlights": [], "updated_at": "2024-01-01", "primary_owners": [], "secondary_owners": [], "is_internet": true, "db_doc_id": 1}]}}
{"ind": 2, "obj": {"type": "message_delta", "content": "Onyx [[1]](https://onyx.app) is a powerful tool for building AI agents."}}
{"ind": 2, "obj": {"type": "section_end"}}
{"ind": 3, "obj": {"type": "citation_start"}}
{"ind": 3, "obj": {"type": "citation_delta", "citations": [{"citation_num": 1, "document_id": "doc1"}]}}
{"ind": 3, "obj": {"type": "section_end"}}
{"ind": 4, "obj": {"type": "stop"}}`;

function DebugPacketsContent() {
  const [inputText, setInputText] = useState("");
  const [packets, setPackets] = useState<Packet[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [hasRendered, setHasRendered] = useState(false);
  const [presentingDocument, setPresentingDocument] = useState<any>(null);

  // Use refs for incremental packet processing (same as production AIMessage)
  const lastProcessedIndexRef = useRef<number>(0);
  const citationsRef = useRef<
    Array<{ citation_num: number; document_id: string }>
  >([]);
  const seenCitationDocIdsRef = useRef<Set<string>>(new Set());
  const documentMapRef = useRef<Map<string, any>>(new Map());
  const groupedPacketsMapRef = useRef<Map<number, Packet[]>>(new Map());
  const [docsArray, setDocsArray] = useState<any[]>([]);

  // Initialize a debug session in the store
  const setCurrentSession = useChatSessionStore(
    (state) => state.setCurrentSession
  );
  const initializeSession = useChatSessionStore(
    (state) => state.initializeSession
  );

  useEffect(() => {
    // Initialize the debug session
    initializeSession(DEBUG_SESSION_ID);
    setCurrentSession(DEBUG_SESSION_ID);
  }, [initializeSession, setCurrentSession]);

  // Auto-parse on paste or text change
  useEffect(() => {
    if (inputText.trim()) {
      const result = parsePacketsFromText(inputText);
      setPackets(result.packets);
      setErrors(result.errors);
      setHasRendered(true);
      // Reset processing state when new packets are loaded
      lastProcessedIndexRef.current = 0;
      citationsRef.current = [];
      seenCitationDocIdsRef.current = new Set();
      documentMapRef.current = new Map();
      groupedPacketsMapRef.current = new Map();
    } else {
      setPackets([]);
      setErrors([]);
      setHasRendered(false);
      lastProcessedIndexRef.current = 0;
      citationsRef.current = [];
      seenCitationDocIdsRef.current = new Set();
      documentMapRef.current = new Map();
      groupedPacketsMapRef.current = new Map();
      setDocsArray([]);
    }
  }, [inputText]);

  const handleClear = () => {
    setInputText("");
    setPackets([]);
    setErrors([]);
    setHasRendered(false);
    lastProcessedIndexRef.current = 0;
    citationsRef.current = [];
    seenCitationDocIdsRef.current = new Set();
    documentMapRef.current = new Map();
    groupedPacketsMapRef.current = new Map();
    setDocsArray([]);
  };

  const handleLoadExample = () => {
    setInputText(EXAMPLE_PACKETS);
  };

  // Create a mock persona/assistant for rendering
  const mockAssistant: MinimalPersonaSnapshot = useMemo(
    () => ({
      id: 0,
      name: "Debug Assistant",
      is_visible: true,
      display_priority: 0,
      builtin_persona: false,
      description: "Debug assistant for testing packet rendering",
      icon_color: undefined,
      icon_shape: undefined,
      tools: [],
      llm_model_version_override: undefined,
      llm_model_provider_override: undefined,
      starter_messages: null,
      is_default_persona: false,
      document_sets: [],
      is_public: true,
      owner: null,
    }),
    []
  );

  // Incrementally process packets using shared utility (same as production AIMessage)
  useEffect(() => {
    // Reset if packets were cleared or reduced
    if (packets.length < lastProcessedIndexRef.current) {
      lastProcessedIndexRef.current = 0;
      citationsRef.current = [];
      seenCitationDocIdsRef.current = new Set();
      documentMapRef.current = new Map();
      groupedPacketsMapRef.current = new Map();
      setDocsArray([]);
      return;
    }

    if (packets.length > lastProcessedIndexRef.current) {
      // Use shared packet processing logic
      const result = processNewPackets(
        packets,
        lastProcessedIndexRef.current,
        documentMapRef.current,
        citationsRef.current,
        seenCitationDocIdsRef.current,
        groupedPacketsMapRef.current
      );

      lastProcessedIndexRef.current = result.lastProcessedIndex;

      // Rebuild docs array from current state
      const newDocsArray: any[] = [];
      citationsRef.current.forEach((citation: any) => {
        const doc = documentMapRef.current.get(citation.document_id);
        if (doc) {
          const index = citation.citation_num - 1;
          newDocsArray[index] = doc;
        }
      });

      // Fill remaining positions with any uncited documents
      const citedDocIds = new Set(
        citationsRef.current.map((c: any) => c.document_id)
      );
      const uncitedDocs = Array.from(documentMapRef.current.values()).filter(
        (doc: any) => !citedDocIds.has(doc.document_id)
      );

      // Merge cited and uncited documents
      const allDocs = [...newDocsArray.filter(Boolean), ...uncitedDocs];
      setDocsArray(allDocs);
    }
  }, [packets]);

  // Create stub functions for MemoizedAIMessage
  const handleFeedbackWithMessageId = useCallback(
    (feedback: FeedbackType, messageId: number) => {
      console.log("Debug: Feedback received", feedback, messageId);
    },
    []
  );

  const createRegenerator = useCallback(
    (regenerationRequest: {
      messageId: number;
      parentMessage: Message;
      forceSearch?: boolean;
    }) => {
      return async (modelOverride: LlmDescriptor) => {
        console.log(
          "Debug: Regenerate requested",
          regenerationRequest,
          modelOverride
        );
      };
    },
    []
  );

  // Build citations map from docsArray updates (which happen after citation processing)
  const citationsMap = useMemo(() => {
    const map: { [key: string]: number } = {};
    citationsRef.current.forEach((citation) => {
      map[citation.document_id] = citation.citation_num;
    });
    return map;
  }, [docsArray]);

  return (
    <div className="container mx-auto p-6 max-w-7xl">
      <div className="mb-6">
        <h1 className="text-3xl font-bold mb-2">Debug Packets Viewer</h1>
        <Text className="text-text-600">
          Paste SSE packets from /send-message to see how they render in
          production.
        </Text>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Input Section */}
        <div className="flex flex-col gap-4">
          <Card className="p-4">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-semibold">Input Packets</h2>
              <div className="flex gap-2">
                <Button onClick={handleLoadExample} variant="outline" size="sm">
                  Load Example
                </Button>
                <Button onClick={handleClear} variant="outline" size="sm">
                  Clear
                </Button>
              </div>
            </div>

            <textarea
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              className="w-full h-96 p-3 font-mono text-sm border rounded-md resize-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="Paste your SSE packets here (one JSON object per line)...
Packets will render automatically as you paste."
            />

            <div className="mt-4">
              <Text className="text-sm text-text-600">
                {inputText.split("\n").filter((l) => l.trim()).length} lines
              </Text>
            </div>

            {errors.length > 0 && (
              <div className="mt-4 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md">
                <h3 className="text-red-800 dark:text-red-200 font-semibold mb-2">
                  Parsing Errors:
                </h3>
                <ul className="list-disc list-inside text-sm text-red-700 dark:text-red-300 space-y-1">
                  {errors.map((error, idx) => (
                    <li key={idx}>{error}</li>
                  ))}
                </ul>
              </div>
            )}

            {hasRendered && packets.length > 0 && errors.length === 0 && (
              <div className="mt-4 p-4 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-md">
                <Text className="text-green-800 dark:text-green-200">
                  Successfully parsed {packets.length} packets
                </Text>
              </div>
            )}
          </Card>
        </div>

        {/* Render Section */}
        <div className="flex flex-col gap-4">
          <Card className="p-4">
            <h2 className="text-xl font-semibold mb-4">Rendered Output</h2>

            {!hasRendered && (
              <div className="flex items-center justify-center h-96 text-text-600">
                <Text>
                  No packets rendered yet. Parse some packets to see the output.
                </Text>
              </div>
            )}

            {hasRendered && packets.length === 0 && errors.length === 0 && (
              <div className="flex items-center justify-center h-96 text-text-600">
                <Text>No valid packets found in input.</Text>
              </div>
            )}

            {hasRendered && packets.length > 0 && (
              <div className="border rounded-md p-4 bg-white dark:bg-background-900">
                <MemoizedAIMessage
                  key={`packets-${packets.length}-${docsArray.length}`}
                  rawPackets={packets}
                  handleFeedbackWithMessageId={handleFeedbackWithMessageId}
                  assistant={mockAssistant}
                  docs={docsArray}
                  citations={citationsMap}
                  setPresentingDocument={setPresentingDocument}
                  createRegenerator={createRegenerator}
                  overriddenModel={undefined}
                  nodeId={1}
                  messageId={undefined}
                  parentMessage={undefined}
                  otherMessagesCanSwitchTo={[]}
                  onMessageSelection={() => {}}
                  llmManager={null}
                  projectFiles={[]}
                  researchType={null}
                />
              </div>
            )}
          </Card>
        </div>
      </div>

      {/* Presenting Document */}
      {presentingDocument && (
        <Card className="p-4 mt-6 bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800">
          <div className="flex justify-between items-start mb-2">
            <h2 className="text-xl font-semibold">Selected Document</h2>
            <Button
              onClick={() => setPresentingDocument(null)}
              variant="ghost"
              size="sm"
            >
              ✕
            </Button>
          </div>
          <div className="space-y-2">
            <div>
              <Text className="font-semibold">Title:</Text>
              <Text>{presentingDocument.semantic_identifier}</Text>
            </div>
            {presentingDocument.link && (
              <div>
                <Text className="font-semibold">Link:</Text>
                <a
                  href={presentingDocument.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 dark:text-blue-400 hover:underline"
                >
                  {presentingDocument.link}
                </a>
              </div>
            )}
            {presentingDocument.blurb && (
              <div>
                <Text className="font-semibold">Blurb:</Text>
                <Text>{presentingDocument.blurb}</Text>
              </div>
            )}
            <div>
              <Text className="font-semibold">Source:</Text>
              <Text>{presentingDocument.source_type}</Text>
            </div>
          </div>
        </Card>
      )}

      {/* Packet Details */}
      {packets.length > 0 && (
        <Card className="p-4 mt-6">
          <h2 className="text-xl font-semibold mb-4">
            Packet Details ({packets.length} packets)
          </h2>
          <div className="overflow-x-auto max-h-96 overflow-y-auto border rounded-md">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-background-100 dark:bg-background-800">
                <tr className="border-b">
                  <th className="text-left p-2">Index</th>
                  <th className="text-left p-2">Type</th>
                  <th className="text-left p-2">Content Preview</th>
                </tr>
              </thead>
              <tbody>
                {packets.map((packet, idx) => (
                  <tr
                    key={idx}
                    className="border-b hover:bg-background-100 dark:hover:bg-background-800"
                  >
                    <td className="p-2 font-mono">{packet.ind}</td>
                    <td className="p-2 font-mono">{packet.obj.type}</td>
                    <td className="p-2 font-mono text-xs truncate max-w-md">
                      {JSON.stringify(packet.obj).slice(0, 100)}...
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

export default function DebugPacketsPage() {
  if (!IS_DEV) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-red-600 mb-2">
            Access Denied
          </h1>
          <p className="text-text-600">
            This page is only available in development mode.
          </p>
        </div>
      </div>
    );
  }

  return (
    <ChatModalProvider>
      <DebugPacketsContent />
    </ChatModalProvider>
  );
}
