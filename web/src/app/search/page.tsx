"use client";

import React, { useRef, useState, useEffect } from "react";
import { ChatInputBar } from "@/app/chat/input/ChatInputBar";
import { FileDescriptor } from "@/app/chat/interfaces";
import { ChatState } from "@/app/chat/types";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { LlmManager, FilterManager } from "@/lib/hooks";
import { OnyxLogoTypeIcon } from "@/components/icons/icons";

type PageProps = {
  searchParams: Promise<{ [key: string]: string }>;
};

// Custom wrapper component to modify the placeholder
function SearchChatInputBar(props: any) {
  const textAreaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // Override the placeholder after the component mounts
    if (textAreaRef.current) {
      textAreaRef.current.placeholder = "Search for...";
    }
  }, []);

  return <ChatInputBar {...props} textAreaRef={textAreaRef} />;
}

export default function Page(props: PageProps) {
  const [message, setMessage] = useState("");
  const [files, setFiles] = useState<FileDescriptor[]>([]);
  const [chatState, setChatState] = useState<ChatState>("input");
  const [alternativeAssistant, setAlternativeAssistant] =
    useState<MinimalPersonaSnapshot | null>(null);
  const [proSearchEnabled, setProSearchEnabled] = useState(false);
  const textAreaRef = useRef<HTMLTextAreaElement>(null);

  // Mock data for required props
  const mockSelectedAssistant: MinimalPersonaSnapshot = {
    id: 1,
    name: "Default Assistant",
    description: "Default assistant for search",
    tools: [],
    starter_messages: null,
    document_sets: [],
    is_public: true,
    is_visible: true,
    display_priority: null,
    is_default_persona: true,
    builtin_persona: false,
    owner: null,
  };

  const mockLlmManager: LlmManager = {
    currentLlm: {
      name: "gpt-4",
      provider: "openai",
      modelName: "gpt-4",
    },
    updateCurrentLlm: () => {},
    temperature: 0.5,
    updateTemperature: () => {},
    updateModelOverrideBasedOnChatSession: () => {},
    imageFilesPresent: false,
    updateImageFilesPresent: () => {},
    liveAssistant: null,
    maxTemperature: 2.0,
  };

  const mockFilterManager: FilterManager = {
    timeRange: null,
    setTimeRange: () => {},
    selectedSources: [],
    setSelectedSources: () => {},
    selectedDocumentSets: [],
    setSelectedDocumentSets: () => {},
    selectedTags: [],
    setSelectedTags: () => {},
    getFilterString: () => "",
    buildFiltersFromQueryString: () => {},
    clearFilters: () => {},
  };

  const handleSubmit = () => {
    // Handle search submission here
    console.log("Search submitted:", message);
  };

  const handleFileUpload = (uploadedFiles: File[]) => {
    // Handle file upload here
    console.log("Files uploaded:", uploadedFiles);
  };

  const handleStopGenerating = () => {
    setChatState("input");
  };

  const handleToggleDocSelection = () => {
    // Handle document selection toggle
  };

  const handleRemoveDocs = () => {
    // Handle document removal
  };

  const handleShowConfigureAPIKey = () => {
    // Handle API key configuration
  };

  const handleToggleDocumentSidebar = () => {
    // Handle document sidebar toggle
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-background">
      <div className="w-full max-w-2xl px-4 flex flex-col items-center space-y-8">
        {/* Onyx Logo */}
        <div className="flex justify-center mb-8">
          <OnyxLogoTypeIcon size={200} />
        </div>

        {/* Search Bar */}
        <div className="w-full">
          <SearchChatInputBar
            toggleDocSelection={handleToggleDocSelection}
            removeDocs={handleRemoveDocs}
            showConfigureAPIKey={handleShowConfigureAPIKey}
            selectedDocuments={[]}
            message={message}
            setMessage={setMessage}
            stopGenerating={handleStopGenerating}
            onSubmit={handleSubmit}
            llmManager={mockLlmManager}
            chatState={chatState}
            alternativeAssistant={alternativeAssistant}
            selectedAssistant={mockSelectedAssistant}
            setAlternativeAssistant={setAlternativeAssistant}
            toggleDocumentSidebar={handleToggleDocumentSidebar}
            setFiles={setFiles}
            handleFileUpload={handleFileUpload}
            textAreaRef={textAreaRef}
            filterManager={mockFilterManager}
            availableSources={[]}
            availableDocumentSets={[]}
            availableTags={[]}
            retrievalEnabled={true}
            proSearchEnabled={proSearchEnabled}
            setProSearchEnabled={setProSearchEnabled}
          />
        </div>
      </div>
    </div>
  );
}
