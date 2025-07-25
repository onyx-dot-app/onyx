"use client";

import { useState } from "react";
import CardSection from "@/components/admin/CardSection";
import { Button } from "@/components/ui/button";
import { DocumentIcon2 } from "@/components/icons/icons";
import useSWR from "swr";
import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { Lock } from "@phosphor-icons/react";

type DocumentProcessor = "unstructured" | "reducto";

interface ProcessorConfig {
  title: string;
  description: string;
  learnMoreText: string;
  learnMoreUrl: string;
  note: string;
  checkUrl: string;
  upsertUrl: string;
  deleteUrl: string;
}

const API_CONFIGS: Record<DocumentProcessor, ProcessorConfig> = {
  unstructured: {
    title: "Process with Unstructured API",
    description:
      "Unstructured extracts and transforms complex data from formats like .pdf, .docx, .png, .pptx, etc. into clean text for Onyx to ingest. Provide an API key to enable Unstructured document processing.",
    learnMoreText: "Learn more about Unstructured",
    learnMoreUrl: "https://docs.unstructured.io/welcome",
    note: "this will send documents to Unstructured servers for processing.",
    checkUrl: "/api/search-settings/unstructured-api-key-set",
    upsertUrl: "/api/search-settings/upsert-unstructured-api-key",
    deleteUrl: "/api/search-settings/delete-unstructured-api-key",
  },
  reducto: {
    title: "Process with Reducto API",
    description:
      "Reducto provides advanced document parsing and extraction capabilities for complex documents. Provide an API key to enable Reducto document processing.",
    learnMoreText: "Learn more about Reducto",
    learnMoreUrl: "https://docs.reducto.ai/overview",
    note: "this will send documents to Reducto servers for processing.",
    checkUrl: "/api/search-settings/reducto-api-key-set",
    upsertUrl: "/api/search-settings/upsert-reducto-api-key",
    deleteUrl: "/api/search-settings/delete-reducto-api-key",
  },
};

function Main({
  documentProcessor,
  activeProcessor,
  onMutate,
}: {
  documentProcessor: DocumentProcessor;
  activeProcessor: DocumentProcessor | null;
  onMutate: () => void;
}) {
  const config = API_CONFIGS[documentProcessor];
  const [apiKey, setApiKey] = useState<string>("");

  const isApiKeySet = activeProcessor === documentProcessor;
  const isDisabled =
    activeProcessor !== null && activeProcessor !== documentProcessor;

  const handleSave = async () => {
    try {
      const paramName =
        documentProcessor === "unstructured"
          ? "unstructured_api_key"
          : "reducto_api_key";
      await fetch(`${config.upsertUrl}?${paramName}=${apiKey}`, {
        method: "PUT",
      });
    } catch (error) {
      console.error("Failed to save API key:", error);
    }
    onMutate();
  };

  const handleDelete = async () => {
    try {
      await fetch(config.deleteUrl, {
        method: "DELETE",
      });
      setApiKey("");
    } catch (error) {
      console.error("Failed to delete API key:", error);
    }
    onMutate();
  };

  return (
    <div className="container mx-auto p-4">
      <CardSection
        className={`mb-8 max-w-2xl bg-white text-text shadow-lg rounded-lg h-3/4 flex flex-col ${isDisabled ? "opacity-60" : ""}`}
      >
        <h3 className="text-2xl text-text-800 font-bold mb-4 text-text border-b border-b-border pb-2">
          {config.title}
        </h3>

        <div className="space-y-4">
          <p className="text-text-600">
            {config.description}
            <br />
            <br /> <strong>Note:</strong> {config.note}
          </p>
          <p className="text-text-600">
            {config.learnMoreText}{" "}
            <a
              href={config.learnMoreUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-500 hover:underline font-medium"
            >
              here
            </a>
            .
          </p>
          <div className="mt-4">
            {isApiKeySet ? (
              <div className="w-full p-3 border rounded-md bg-background text-text flex items-center">
                <span className="flex-grow">••••••••••••••••</span>
                <Lock className="h-5 w-5 text-text-400" />
              </div>
            ) : (
              <input
                type="text"
                placeholder={
                  isDisabled ? "Delete other API key first" : "Enter API Key"
                }
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                disabled={isDisabled}
                className={`w-full p-3 border rounded-md bg-background text-text focus:ring-2 focus:ring-blue-500 transition duration-200 ${
                  isDisabled ? "cursor-not-allowed opacity-50" : ""
                }`}
              />
            )}
          </div>
          <div className="flex space-x-4 mt-6">
            {isApiKeySet ? (
              <>
                <Button onClick={handleDelete} variant="destructive">
                  Delete API Key
                </Button>
                <p className="text-text-600 my-auto">
                  Delete the current API key before updating.
                </p>
              </>
            ) : (
              <>
                <Button
                  onClick={handleSave}
                  disabled={isDisabled || !apiKey.trim()}
                  className={`bg-blue-500 text-white hover:bg-blue-600 transition duration-200 ${
                    isDisabled ? "cursor-not-allowed opacity-50" : ""
                  }`}
                >
                  Save API Key
                </Button>
                {isDisabled && (
                  <p className="text-amber-300 my-auto text-sm">
                    Only one document processor can be active at a time. Delete
                    the other API key first.
                  </p>
                )}
              </>
            )}
          </div>
        </div>
      </CardSection>
    </div>
  );
}

export default function Page() {
  const {
    data: activeProcessor,
    error,
    mutate,
    isLoading,
  } = useSWR<DocumentProcessor | null>(
    "/api/search-settings/active-document-processor",
    (url: string) => fetch(url).then((res) => res.json())
  );

  if (isLoading) {
    return <ThreeDotsLoader />;
  }

  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="Document Processing"
        icon={<DocumentIcon2 size={32} className="my-auto" />}
      />
      <div className="flex flex-row gap-4 items-stretch h-full">
        <Main
          documentProcessor="unstructured"
          activeProcessor={activeProcessor ?? null}
          onMutate={mutate}
        />
        <Main
          documentProcessor="reducto"
          activeProcessor={activeProcessor ?? null}
          onMutate={mutate}
        />
      </div>
    </div>
  );
}
