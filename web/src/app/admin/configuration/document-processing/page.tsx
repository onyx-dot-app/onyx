"use client";

import { useState } from "react";
import CardSection from "@/components/admin/CardSection";
import { Button } from "@/components/ui/button";
import { DocumentIcon2 } from "@/components/icons/icons";
import useSWR from "swr";
import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { Lock } from "@phosphor-icons/react";

function Main() {
  const {
    data: isApiKeySet,
    error,
    mutate,
    isLoading,
  } = useSWR<{
    unstructured_api_key: string | null;
  }>("/api/search-settings/unstructured-api-key-set", (url: string) =>
    fetch(url).then((res) => res.json())
  );

  const [apiKey, setApiKey] = useState("");

  const handleSave = async () => {
    try {
      await fetch(
        `/api/search-settings/upsert-unstructured-api-key?unstructured_api_key=${apiKey}`,
        {
          method: "PUT",
        }
      );
    } catch (error) {
      console.error("Failed to save API key:", error);
    }
    mutate();
  };

  const handleDelete = async () => {
    try {
      await fetch("/api/search-settings/delete-unstructured-api-key", {
        method: "DELETE",
      });
      setApiKey("");
    } catch (error) {
      console.error("Failed to delete API key:", error);
    }
    mutate();
  };

  if (isLoading) {
    return <ThreeDotsLoader />;
  }
  return (
    <div className="container mx-auto p-4">
      <CardSection className="mb-8 max-w-2xl bg-white text-text shadow-lg rounded-lg">
        <h3 className="text-2xl text-text-800 font-bold mb-4 text-text border-b border-b-border pb-2">
          Process with Unstructured API
        </h3>

        <div className="space-y-4">
          <p className="text-text-600">
            Unstructured extracts and transforms complex data from formats like
            .pdf, .docx, .png, .pptx, etc. into clean text for Onyx to ingest.
            Provide an API key to enable Unstructured document processing.
            <br />
            <br /> <strong>Note:</strong> this will send documents to
            Unstructured servers for processing.
          </p>
          <p className="text-text-600">
            Learn more about Unstructured{" "}
            <a
              href="https://docs.unstructured.io/welcome"
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
                placeholder="Enter API Key"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="w-full p-3 border rounded-md bg-background text-text focus:ring-2 focus:ring-blue-500 transition duration-200"
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
              <Button
                onClick={handleSave}
                className="bg-blue-500 text-white hover:bg-blue-600 transition duration-200"
              >
                Save API Key
              </Button>
            )}
          </div>
        </div>
      </CardSection>
    </div>
  );
}

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="Document Processing"
        icon={<DocumentIcon2 size={32} className="my-auto" />}
      />
      <Main />
    </div>
  );
}
